"""Uzbek long-text to speech with Gemini (generateContent, response_modalities=['AUDIO']) -> one MP3.

Any length (an hour or more): the text is split on sentence boundaries into chunks, each chunk is sent to
the Gemini TTS model with responseModalities ['AUDIO'], the audio is cached on disk (an interrupted run
resumes where it stopped), cleaned (silence trim, fades, Gemini's end-of-clip noise burst removed),
joined with natural pauses and encoded to a single MP3.

The API key comes from .env: GOOGLE_TTS_API_KEY (more keys can be added in GEMINI_API_KEYS, comma separated;
when one key hits its daily limit the next is used, so voice and model stay the same).

  python uztts.py kitob.txt                         # -> kitob.mp3, voice Iapetus
  python uztts.py kitob.txt --voice Kore -o out.mp3
  python uztts.py kitob.txt --dry-run               # chunks, expected length and requests; nothing generated
"""
import argparse, array, base64, concurrent.futures as cf, hashlib, json, os, re, subprocess, sys, threading, time, wave
import urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SR = 24000                                   # Gemini returns 24 kHz mono 16-bit PCM
# vertex: Google Cloud (Agent Platform / Vertex AI), billed to the Cloud project and its credits.
#         Needs an API key bound to a service account (Credentials -> Create API key -> Agent Platform API).
# aistudio: Gemini API from AI Studio.
APIS = {'vertex': 'https://aiplatform.googleapis.com/v1/publishers/google/models/{model}:generateContent',
        'aistudio': 'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'}
DEFAULT_MODEL, DEFAULT_VOICE = 'gemini-3.8-flash-tts', 'Iapetus'

# ---------------------------------------------------------------- config
def load_env():
    env = {}
    for name in ('.env', '.env.txt'):
        p = os.path.join(HERE, name)
        if os.path.exists(p):
            for line in open(p, encoding='utf-8-sig'):
                k, sep, v = line.strip().partition('=')
                if sep and not k.startswith('#'):
                    env.setdefault(k.strip(), v.strip().strip('"\''))
    return env

def api_keys(env):
    keys = []
    for name in ('UZTTS_KEYS', 'GOOGLE_TTS_API_KEY', 'GEMINI_API_KEYS', 'GEMINI_API_KEY'):
        for k in (os.environ.get(name) or env.get(name, '')).split(','):
            if k.strip() and k.strip() not in keys:
                keys.append(k.strip())
    return keys

def ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return 'ffmpeg'

FF = ffmpeg()

# ---------------------------------------------------------------- text
APOS = str.maketrans({'ʻ': "'", 'ʼ': "'", '‘': "'", '’': "'", '`': "'", '´': "'"})

def normalize(text):
    text = text.replace('\r\n', '\n').replace('\r', '\n').translate(APOS)
    text = re.sub(r'[ \t ]+', ' ', text)
    text = re.sub(r'\n[ \t]*\n\s*', '\n\n', text)              # paragraph = blank line
    text = re.sub(r'(?<!\n)\n(?!\n)', ' ', text)                # a single line break is only wrapping
    return text.strip()

SENT = re.compile(r'(?<=[.!?…])["»”)]*\s+(?=["«“(]?[A-ZА-ЯЁЎҚҒҲ\'0-9])')

def split_long(s, limit):
    """A sentence longer than the limit is cut at , ; : — and, failing that, between words."""
    if len(s) <= limit:
        return [s]
    out, cur = [], ''
    for piece in re.split(r'(?<=[,;:—])\s+', s):
        words = [piece] if len(piece) <= limit else piece.split(' ')
        for w in words:
            if cur and len(cur) + len(w) + 1 > limit:
                out.append(cur); cur = w
            else:
                cur = (cur + ' ' + w).strip()
    if cur: out.append(cur)
    return out

def chunk(text, limit):
    """-> [(chunk_text, pause_after_seconds)]; a chunk never crosses a paragraph"""
    out = []
    for par in text.split('\n\n'):
        cur = ''
        for s in (p for sent in SENT.split(par) if sent.strip() for p in split_long(sent.strip(), limit)):
            if cur and len(cur) + len(s) + 1 > limit:
                out.append([cur, .45]); cur = s
            else:
                cur = (cur + ' ' + s).strip()
        if cur: out.append([cur, .45])
        if out: out[-1][1] = 1.0                                  # longer breath between paragraphs
    return [tuple(c) for c in out]

# ---------------------------------------------------------------- audio
def clean(a):
    # Gemini ends every clip with a ~0.13 s full-scale noise burst: cut it off before it starts
    b = next((i for i in range(max(0, len(a) - SR // 2), len(a)) if abs(a[i]) >= 30000), None)
    if b is not None:
        a = a[:max(0, b - int(.03 * SR))]
    th, m = 300, int(.05 * SR)
    lo = next((i for i, v in enumerate(a) if abs(v) > th), 0)
    hi = next((i for i in range(len(a) - 1, -1, -1) if abs(a[i]) > th), len(a) - 1)
    a = a[max(0, lo - m):hi + m]
    fi, fo = int(.015 * SR), int(.05 * SR)
    for i in range(min(fi, len(a))): a[i] = int(a[i] * i / fi)
    for i in range(min(fo, len(a))): a[-1 - i] = int(a[-1 - i] * i / fo)
    return a

# ---------------------------------------------------------------- Gemini
class QuotaExhausted(Exception):
    pass

class KeyBlocked(Exception):
    pass

class GcloudToken:
    """OAuth token of the account logged in with `gcloud auth login`; refreshed before its hour runs out.
    account: the Google account that owns the project (GOOGLE_CLOUD_ACCOUNT), so a different active gcloud account does not matter."""
    def __init__(self, account=None):
        self.tok, self.at, self.lock = None, 0, threading.Lock()
        self.cmd = 'gcloud auth print-access-token' + (f' --account {account}' if account else '')

    def get(self):
        with self.lock:
            if not self.tok or time.time() - self.at > 45 * 60:
                r = subprocess.run(self.cmd, shell=True, capture_output=True, text=True)
                if r.returncode or not r.stdout.strip():
                    raise KeyBlocked('gcloud token olinmadi: avval "gcloud auth login" qiling.\n' + r.stderr[-300:])
                self.tok, self.at = r.stdout.strip(), time.time()
            return self.tok

class Gemini:
    def __init__(self, keys, model, voice, style, backend, project=None, account=None):
        self.keys, self.model, self.voice, self.style, self.url = keys, model, voice, style, APIS[backend]
        self.project = project if backend == 'vertex' else None
        if self.project:
            # Vertex with the gcloud account: billed to this project (and its credits), no API key needed
            self.url = f'https://aiplatform.googleapis.com/v1/projects/{project}/locations/global/publishers/google/models/{{model}}:generateContent'
            self.token, self.keys = GcloudToken(account), ['gcloud']
        self.dead, self.lock = set(), threading.Lock()

    def headers(self, k):
        if self.project:
            return {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + self.token.get(), 'x-goog-user-project': self.project}
        return {'Content-Type': 'application/json', 'x-goog-api-key': k}

    def key(self):
        with self.lock:
            for k in self.keys:
                if k not in self.dead:
                    return k
        raise QuotaExhausted('Hamma kalitlarning kunlik limiti tugadi. Tayyor bo\'laklar keshda: ertaga shu buyruq qolganidan davom etadi.')

    def synth(self, text):
        # a style instruction tends to be read aloud by the model, so it is off unless asked for
        prompt = (self.style.strip() + ':\n\n' + text) if self.style else text
        body = {'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
                'generationConfig': {'responseModalities': ['AUDIO'],
                                     'speechConfig': {'voiceConfig': {'prebuiltVoiceConfig': {'voiceName': self.voice}}}}}
        for attempt in range(8):
            k = self.key()
            req = urllib.request.Request(self.url.format(model=self.model), json.dumps(body).encode(), self.headers(k))
            try:
                d = json.load(urllib.request.urlopen(req, timeout=240))
                part = d['candidates'][0]['content']['parts'][0]['inlineData']
                return clean(array.array('h', base64.b64decode(part['data'])))
            except urllib.error.HTTPError as e:
                msg = e.read().decode('utf-8', 'replace')
                if e.code == 429 and 'PerDay' in msg:
                    with self.lock: self.dead.add(k)
                    continue
                if e.code == 401 or e.code == 403 and ('blocked' in msg or 'API_KEY_SERVICE_BLOCKED' in msg or 'has not been used' in msg):
                    with self.lock: self.dead.add(k)
                    if all(x in self.dead for x in self.keys):
                        raise KeyBlocked(msg)
                    continue
                if e.code in (429, 500, 502, 503, 504):
                    time.sleep(min(60, 5 * 2 ** attempt)); continue
                raise RuntimeError(f'Gemini {e.code}: {msg[:300]}')
            except (urllib.error.URLError, TimeoutError, ConnectionError, KeyError, IndexError):
                time.sleep(min(60, 5 * 2 ** attempt))
        raise RuntimeError('bo\'lak 8 urinishda ham chiqmadi')

KEY_HELP = """
Kalit Google Cloud'dagi Gemini'ga (Agent Platform API) ruxsat bermayapti. Bir martalik sozlash:
  1. https://console.cloud.google.com/apis/library/aiplatform.googleapis.com  ->  "Enable"
  2. https://console.cloud.google.com/apis/credentials  ->  "Create credentials" -> "API key"
     -> "Agent Platform API" ni tanlang -> service account'ga bog'lang -> Create
  3. Yangi kalitni .env faylidagi GOOGLE_TTS_API_KEY= ga yozing va skriptni qayta ishga tushiring.
"""

# ---------------------------------------------------------------- main
def hms(s):
    s = int(s); return f'{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}'

def main():
    ap = argparse.ArgumentParser(description="O'zbekcha uzun matnni Gemini ovozi bilan bitta MP3 ga aylantirish")
    ap.add_argument('input', help='matn fayli (.txt, UTF-8)')
    ap.add_argument('-o', '--output', help='natija .mp3 (default: matn nomi bilan)')
    ap.add_argument('--voice', default=DEFAULT_VOICE, help='Iapetus, Puck, Charon, Kore, Leda, Achird, Fenrir, Zephyr...')
    ap.add_argument('--model', default=DEFAULT_MODEL, help='masalan gemini-3.8-flash-tts, gemini-2.5-flash-preview-tts')
    ap.add_argument('--style', default='', help='ixtiyoriy uslub, masalan "Say calmly" (model uni ovoz chiqarib o\'qib qo\'yishi mumkin)')
    ap.add_argument('--chunk', type=int, default=650, help="bo'lak uzunligi, belgi (bitta javob ~45 soniyagacha bo'lsin)")
    ap.add_argument('--workers', type=int, default=2, help="parallel so'rovlar")
    ap.add_argument('--backend', choices=list(APIS), default='vertex', help='vertex = Google Cloud (kredit), aistudio = AI Studio')
    ap.add_argument('--bitrate', default='128k')
    ap.add_argument('--dry-run', action='store_true', help="faqat hisob-kitob, hech narsa yaratilmaydi")
    a = ap.parse_args()

    env = load_env()
    keys = api_keys(env)
    project = os.environ.get('GOOGLE_CLOUD_PROJECT') or env.get('GOOGLE_CLOUD_PROJECT')
    if not keys and not project:
        sys.exit("Sozlama topilmadi: .env da GOOGLE_CLOUD_PROJECT=... (gcloud bilan) yoki GOOGLE_TTS_API_KEY=... bo'lishi kerak.")
    text = normalize(open(a.input, encoding='utf-8-sig').read())
    chunks = chunk(text, a.chunk)
    print(f"Matn: {len(text):,} belgi · {len(chunks)} bo'lak · taxminan {hms(len(text) / 13.5)} · {a.model}, ovoz {a.voice}")
    if a.dry_run:
        print(f"So'rovlar soni: {len(chunks)} (bepul kalitda kuniga ~10 ta; uzun matn uchun to'lovli kalit kerak). Kalitlar: {len(keys)}")
        return

    out = a.output or os.path.splitext(a.input)[0] + '.mp3'
    cache = os.path.join(HERE, 'cache', re.sub(r'\W', '_', f'{a.backend}_{a.model}_{a.voice}_{a.style}')[:80])
    os.makedirs(cache, exist_ok=True)
    path = lambda t: os.path.join(cache, hashlib.md5(t.encode()).hexdigest() + '.pcm')
    todo = list(dict.fromkeys(c for c, _ in chunks if not os.path.exists(path(c))))
    print(f"Keshda tayyor: {len(chunks) - len(todo)} · yaratiladi: {len(todo)}")

    account = os.environ.get('GOOGLE_CLOUD_ACCOUNT') or env.get('GOOGLE_CLOUD_ACCOUNT')
    eng = Gemini(keys, a.model, a.voice, a.style, a.backend, project, account)
    def work(c):
        pcm = eng.synth(c)
        with open(path(c) + '.tmp', 'wb') as f: f.write(pcm.tobytes())
        os.replace(path(c) + '.tmp', path(c))

    done, t0, stop = 0, time.time(), None
    with cf.ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(work, c): c for c in todo}
        for f in cf.as_completed(futs):
            try:
                f.result(); done += 1
            except (QuotaExhausted, KeyBlocked) as e:
                stop = e; ex.shutdown(cancel_futures=True); break
            except Exception as e:
                print(f'\n  xato: {e}')
            el = time.time() - t0
            print(f"\r  {done}/{len(todo)} bo'lak · {hms(el)} o'tdi · ~{hms(el / max(done, 1) * (len(todo) - done))} qoldi   ", end='', flush=True)
    print()
    if isinstance(stop, KeyBlocked):
        sys.exit(KEY_HELP)
    if stop:
        print(stop)
    missing = [c for c, _ in chunks if not os.path.exists(path(c))]
    if missing:
        sys.exit(f"{len(missing)} ta bo'lak yetishmayapti. Tayyorlari saqlandi: buyruqni qayta ishga tushirsangiz, qolganidan davom etadi.")

    # join on disk (an hour of 24 kHz PCM is ~170 MB), then one encode with loudness normalisation
    tmp_wav, marks, pos = os.path.splitext(out)[0] + '.tmp.wav', [], 0
    with wave.open(tmp_wav, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        for i, (c, pause) in enumerate(chunks):
            data = open(path(c), 'rb').read()
            marks.append((pos / SR, c[:70])); w.writeframes(data); pos += len(data) // 2
            if i < len(chunks) - 1:
                gap = bytes(2 * int(pause * SR)); w.writeframes(gap); pos += len(gap) // 2
    subprocess.run([FF, '-y', '-loglevel', 'error', '-i', tmp_wav, '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11',
                    '-ar', '44100', '-ac', '1', '-c:a', 'libmp3lame', '-b:a', a.bitrate, out], check=True)
    os.remove(tmp_wav)
    with open(os.path.splitext(out)[0] + '_vaqtlar.txt', 'w', encoding='utf-8') as f:
        f.writelines(f'{hms(t)}  {c}\n' for t, c in marks)
    print(f"Tayyor: {out} · {hms(pos / SR)} · {os.path.getsize(out) / 1e6:.1f} MB")

if __name__ == '__main__':
    main()
