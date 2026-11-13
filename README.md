# uz-tts-tool

**English** · [O'zbekcha](README.uz.md)

[![▶ Live demo](https://img.shields.io/badge/%E2%96%B6_Live_demo-xoliddev.github.io-22b8f0?style=for-the-badge)](https://xoliddev.github.io/demos/uz-tts-tool/)

> **O'zbekcha matnni tabiiy ovozga aylantiradi** — turns long Uzbek text into one clean, natural-sounding MP3.

A single-file Python CLI that feeds Uzbek text of any length (a short post or a whole audiobook) to Google's Gemini TTS models and gives you back **one loudness-normalised MP3 plus a timestamp index**. It is resumable, parallel, and fixes the audio quirks you hit when you stitch dozens of TTS clips together.

```text
$ python uztts.py kitob.txt          # e.g. a full-length book
Matn: 184,320 belgi · 296 bo'lak · taxminan 3:47:33 · gemini-3.8-flash-tts, ovoz Iapetus
Keshda tayyor: 0 · yaratiladi: 296
  296/296 bo'lak · 0:41:12 o'tdi · ~0:00:00 qoldi
Tayyor: kitob.mp3 · 3:45:02 · 216.4 MB
```

## Listen first

| Sample | Text | Notes |
| --- | --- | --- |
| [`samples/toshkent.mp3`](samples/toshkent.mp3) | [toshkent.txt](samples/toshkent.txt) | 37 s, default voice `Iapetus`, `gemini-3.8-flash-tts`; with its [timestamp file](samples/toshkent_vaqtlar.txt) |
| [`samples/sevgi.mp3`](samples/sevgi.mp3) | [sevgi.txt](samples/sevgi.txt) | 52 s, emotional prose, `gemini-3.8-flash-tts` |
| [`samples/mayus.mp3`](samples/mayus.mp3) | [mayus.txt](samples/mayus.txt) | 59 s, slow reflective narration, Gemini 2.5 Pro TTS |

**Voice picker:** [`samples/voices/`](samples/voices/) holds ten short character lines (an old soldier, a frightened young man, a villain) read by different Gemini voices — `Charon`, `Fenrir`, `Orus`, `Enceladus`, `Iapetus`, `Puck`, `Zephyr`. Open [`samples/voices/index.html`](samples/voices/index.html) in a browser to compare them side by side (or view it through GitHub Pages).

## Why

Good Uzbek TTS is hard to come by. Most engines either don't support Uzbek at all or sound robotic, and the ones that sound good (Gemini's audio models) only accept short requests. Feeding them a book means:

- splitting text without cutting sentences in half,
- surviving rate limits, daily quotas and dropped connections over hours of generation,
- removing the noise burst Gemini leaves at the end of every clip,
- and joining hundreds of clips so it sounds like one continuous reading, not a playlist.

`uztts.py` does all of that in ~280 lines with no dependencies beyond an ffmpeg binary.

## Features

Everything below is implemented in [`uztts.py`](uztts.py):

- **Unlimited length** — text is split on sentence boundaries into ~650-character chunks (`--chunk`). A chunk never crosses a paragraph; over-long sentences are cut at `, ; : —`, then between words.
- **Uzbek-aware text cleanup** — all apostrophe variants (`ʻ ʼ ‘ ’ \` ´`) are normalised so `o'` / `g'` are pronounced consistently; Latin and Cyrillic capitals (incl. `Ў Қ Ғ Ҳ`) are recognised as sentence starts; single line breaks are treated as wrapping, blank lines as paragraphs.
- **Resumable cache** — every finished chunk is saved to `cache/` (keyed by backend, model, voice and an MD5 of the text). Interrupt the run, hit a quota, re-run the same command — it continues where it stopped.
- **Parallel generation** with retries and exponential back-off on `429` / `5xx` / network errors (`--workers`, default 2).
- **Multiple API keys** — when a key hits its daily limit (`429 … PerDay`) or is blocked, the next key is used, so voice and model stay identical across the whole book.
- **Clip cleanup** — trims Gemini's ~0.13 s end-of-clip noise burst, trims silence, adds short fade-in/out to avoid clicks.
- **Natural pacing** — 0.45 s pause between chunks inside a paragraph, 1 s between paragraphs.
- **Broadcast-level output** — chunks are joined on disk (memory stays flat even for multi-hour audio), then encoded once with ffmpeg `loudnorm` to **-16 LUFS**, 44.1 kHz mono MP3 (`--bitrate`, default `128k`).
- **Timestamp index** — `<name>_vaqtlar.txt` lists when each chunk starts, so you can build chapters or find a passage quickly.
- **Dry run** — `--dry-run` prints character count, chunk count, expected duration and number of API requests without generating anything.
- **Two backends**
  - `vertex` (default): Google Cloud Vertex AI. With `GOOGLE_CLOUD_PROJECT` set it authenticates with your `gcloud` login (token auto-refreshed every 45 min, so hour-long jobs don't break) and bills the Cloud project — no API key needed.
  - `aistudio`: Gemini API with AI Studio keys.

## Install

Requirements: **Python 3.9+**, and for the default backend the [gcloud CLI](https://cloud.google.com/sdk/docs/install).

```bash
git clone https://github.com/xoliddev/uz-tts-tool.git
cd uz-tts-tool
pip install -r requirements.txt   # only imageio-ffmpeg (skip it if ffmpeg is on your PATH)
cp .env.example .env              # then fill it in, see below
```

## Configuration

Settings are read from real environment variables first, then from `.env` or `.env.txt` next to the script.

| Variable | Used for |
| --- | --- |
| `GOOGLE_CLOUD_PROJECT` | Vertex AI via your `gcloud auth login` session; billed to this project. |
| `GOOGLE_CLOUD_ACCOUNT` | Optional. Which gcloud account to take the token from. |
| `GOOGLE_TTS_API_KEY` | An API key (AI Studio key for `--backend aistudio`, or a Vertex key bound to a service account). |
| `GEMINI_API_KEYS` | More keys, comma separated. Used in order as daily quotas run out. |
| `UZTTS_KEYS`, `GEMINI_API_KEY` | Also accepted, same meaning. |

**Option A — Google Cloud (recommended for long texts):**

```bash
gcloud auth login
# .env
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
```

**Option B — AI Studio key:**

```bash
# .env
GEMINI_API_KEYS=key1,key2
python uztts.py kitob.txt --backend aistudio
```

> Free AI Studio keys allow only a handful of TTS requests per day (roughly 10). Use `--dry-run` to see how many requests a text needs before you start.

## Usage

```bash
python uztts.py kitob.txt                         # -> kitob.mp3 + kitob_vaqtlar.txt, voice Iapetus
python uztts.py kitob.txt --voice Kore -o out.mp3 # another voice, custom output name
python uztts.py kitob.txt --dry-run               # estimate only: chunks, duration, requests
python uztts.py kitob.txt --workers 4 --bitrate 192k
python uztts.py kitob.txt --model gemini-2.5-flash-preview-tts
```

| Option | Default | Description |
| --- | --- | --- |
| `input` | — | UTF-8 text file. Blank line = new paragraph. |
| `-o, --output` | `<input>.mp3` | Output MP3 path. |
| `--voice` | `Iapetus` | Gemini prebuilt voice: `Iapetus` (calm), `Puck` (upbeat), `Charon` (informative), `Kore`, `Leda` (female), `Achird`, `Fenrir`, `Zephyr`, … |
| `--model` | `gemini-3.8-flash-tts` | Any Gemini TTS model id. |
| `--style` | off | Optional style prefix, e.g. `"Say calmly"`. Off by default because the model sometimes reads the instruction aloud. |
| `--chunk` | `650` | Max characters per request (keep one response under ~45 s). |
| `--workers` | `2` | Parallel requests. |
| `--backend` | `vertex` | `vertex` or `aistudio`. |
| `--bitrate` | `128k` | MP3 bitrate. |
| `--dry-run` | — | Print the plan, generate nothing. |

The CLI messages are in Uzbek, since that's who it's for.

## How it works

```text
text.txt ─► normalise ─► split into chunks ─► Gemini TTS (parallel, retried)
                                                    │  24 kHz PCM
                                                    ▼
                                    cache/<backend_model_voice>/<md5>.pcm
                                                    │  trim burst + silence, fades
                                                    ▼
                     join with pauses (on disk) ─► ffmpeg loudnorm -16 LUFS ─► out.mp3
                                                                            └► out_vaqtlar.txt
```

## License

[MIT](LICENSE) © 2026 xoliddev
