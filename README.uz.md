# uz-tts-tool

[English](README.md) · **O'zbekcha**

> **O'zbekcha matnni tabiiy ovozga aylantiradi** — uzun o'zbekcha matndan bitta toza, tabiiy eshitiladigan MP3 yasaydi.

Bitta fayldan iborat Python CLI: istalgan uzunlikdagi o'zbekcha matnni (qisqa postdan tortib butun audiokitobgacha) Google'ning Gemini TTS modellariga beradi va sizga **balandligi normallashtirilgan bitta MP3 hamda vaqt belgilari ro'yxatini** qaytaradi. To'xtagan joyidan davom etadi, parallel ishlaydi va o'nlab TTS kliplarni bir-biriga ulaganda chiqadigan audio muammolarini tuzatadi.

```text
$ python uztts.py kitob.txt          # masalan, to'liq hajmdagi kitob
Matn: 184,320 belgi · 296 bo'lak · taxminan 3:47:33 · gemini-3.8-flash-tts, ovoz Iapetus
Keshda tayyor: 0 · yaratiladi: 296
  296/296 bo'lak · 0:41:12 o'tdi · ~0:00:00 qoldi
Tayyor: kitob.mp3 · 3:45:02 · 216.4 MB
```

## Avval eshitib ko'ring

| Namuna | Matn | Izoh |
| --- | --- | --- |
| [`samples/toshkent.mp3`](samples/toshkent.mp3) | [toshkent.txt](samples/toshkent.txt) | 37 soniya, standart ovoz `Iapetus`, `gemini-3.8-flash-tts`; [vaqt belgilari fayli](samples/toshkent_vaqtlar.txt) bilan |
| [`samples/sevgi.mp3`](samples/sevgi.mp3) | [sevgi.txt](samples/sevgi.txt) | 52 soniya, hissiyotli nasr, `gemini-3.8-flash-tts` |
| [`samples/mayus.mp3`](samples/mayus.mp3) | [mayus.txt](samples/mayus.txt) | 59 soniya, sekin, o'ychan hikoya, Gemini 2.5 Pro TTS |

**Ovoz tanlash:** [`samples/voices/`](samples/voices/) papkasida turli Gemini ovozlari — `Charon`, `Fenrir`, `Orus`, `Enceladus`, `Iapetus`, `Puck`, `Zephyr` — o'qigan o'nta qisqa personaj gapi bor (keksa askar, qo'rqib ketgan yigit, yovuz qahramon). Ularni yonma-yon solishtirish uchun [`samples/voices/index.html`](samples/voices/index.html) ni brauzerda oching (yoki GitHub Pages orqali ko'ring).

## Nega

Yaxshi o'zbekcha TTS topish qiyin. Ko'pchilik dvigatellar o'zbek tilini umuman qo'llab-quvvatlamaydi yoki robotga o'xshab gapiradi, yaxshi eshitiladiganlari (Gemini audio modellari) esa faqat qisqa so'rovlarni qabul qiladi. Ularga butun kitobni berish degani:

- matnni gaplarni o'rtasidan kesmasdan bo'lish,
- soatlab davom etadigan generatsiya davomida rate limit'lar, kunlik kvotalar va uzilib qolgan ulanishlardan omon chiqish,
- Gemini har bir klip oxirida qoldiradigan shovqin portlashini olib tashlash,
- va yuzlab kliplarni playlist emas, bitta uzluksiz o'qishdek eshitiladigan qilib ulash.

`uztts.py` bularning hammasini ~280 qatorda, ffmpeg binary'sidan boshqa hech qanday bog'liqliksiz bajaradi.

## Imkoniyatlar

Quyidagilarning barchasi [`uztts.py`](uztts.py) da amalga oshirilgan:

- **Cheksiz uzunlik** — matn gap chegaralari bo'yicha ~650 belgilik bo'laklarga bo'linadi (`--chunk`). Bo'lak hech qachon paragrafdan oshib o'tmaydi; haddan tashqari uzun gaplar `, ; : —` belgilarida, so'ng so'zlar orasida kesiladi.
- **O'zbek tiliga moslashgan matn tozalash** — barcha apostrof variantlari (`ʻ ʼ ‘ ’ \` ´`) bir xil ko'rinishga keltiriladi, shunda `o'` / `g'` doim bir xil talaffuz qilinadi; lotin va kirill bosh harflari (shu jumladan `Ў Қ Ғ Ҳ`) gap boshi deb taniladi; yakka qator tashlanishi oddiy satr ko'chishi, bo'sh qator esa yangi paragraf deb hisoblanadi.
- **Davom ettirsa bo'ladigan kesh** — har bir tayyor bo'lak `cache/` ga saqlanadi (backend, model, ovoz va matnning MD5 hash'i bo'yicha). Jarayonni to'xtating, kvotaga duch keling, xuddi shu buyruqni qayta ishga tushiring — u to'xtagan joyidan davom etadi.
- **Parallel generatsiya** — `429` / `5xx` / tarmoq xatolarida qayta urinish va eksponensial kutish bilan (`--workers`, standart 2).
- **Bir nechta API kalit** — kalit kunlik limitga yetganda (`429 … PerDay`) yoki bloklanganda keyingisi ishlatiladi, shuning uchun butun kitob davomida ovoz va model bir xil qoladi.
- **Kliplarni tozalash** — Gemini'ning klip oxiridagi ~0,13 soniyalik shovqin portlashini kesadi, jimlikni olib tashlaydi, chirsillash bo'lmasligi uchun qisqa fade-in/out qo'shadi.
- **Tabiiy sur'at** — paragraf ichidagi bo'laklar orasida 0,45 soniya, paragraflar orasida 1 soniya pauza.
- **Efir darajasidagi natija** — bo'laklar diskda ulanadi (bir necha soatlik audioda ham xotira sarfi o'smaydi), keyin ffmpeg `loudnorm` bilan bir marta **-16 LUFS**, 44,1 kHz mono MP3 ga kodlanadi (`--bitrate`, standart `128k`).
- **Vaqt belgilari ro'yxati** — `<nom>_vaqtlar.txt` har bir bo'lak qachon boshlanishini ko'rsatadi, shunda boblar yasash yoki kerakli joyni tez topish mumkin.
- **Sinov rejimi** — `--dry-run` hech narsa yaratmasdan belgilar soni, bo'laklar soni, taxminiy davomiylik va API so'rovlari sonini chiqaradi.
- **Ikki xil backend**
  - `vertex` (standart): Google Cloud Vertex AI. `GOOGLE_CLOUD_PROJECT` berilgan bo'lsa, `gcloud` login'ingiz orqali autentifikatsiya qiladi (token har 45 daqiqada avtomatik yangilanadi, shuning uchun soatlab davom etadigan ishlar uzilmaydi) va to'lov Cloud loyihasidan yechiladi — API kalit kerak emas.
  - `aistudio`: AI Studio kalitlari bilan Gemini API.

## O'rnatish

Talablar: **Python 3.9+**, standart backend uchun esa [gcloud CLI](https://cloud.google.com/sdk/docs/install).

```bash
git clone https://github.com/xoliddev/uz-tts-tool.git
cd uz-tts-tool
pip install -r requirements.txt   # faqat imageio-ffmpeg (ffmpeg PATH'da bo'lsa, o'tkazib yuboring)
cp .env.example .env              # keyin to'ldiring, pastga qarang
```

## Sozlash

Sozlamalar avval haqiqiy muhit o'zgaruvchilaridan, keyin skript yonidagi `.env` yoki `.env.txt` faylidan o'qiladi.

| O'zgaruvchi | Nima uchun |
| --- | --- |
| `GOOGLE_CLOUD_PROJECT` | `gcloud auth login` sessiyangiz orqali Vertex AI; to'lov shu loyihadan yechiladi. |
| `GOOGLE_CLOUD_ACCOUNT` | Ixtiyoriy. Token qaysi gcloud akkauntidan olinishi. |
| `GOOGLE_TTS_API_KEY` | API kalit (`--backend aistudio` uchun AI Studio kaliti yoki service account'ga bog'langan Vertex kaliti). |
| `GEMINI_API_KEYS` | Qo'shimcha kalitlar, vergul bilan. Kunlik kvotalar tugagan sari shu tartibda ishlatiladi. |
| `UZTTS_KEYS`, `GEMINI_API_KEY` | Bular ham qabul qilinadi, ma'nosi bir xil. |

**A variant — Google Cloud (uzun matnlar uchun tavsiya etiladi):**

```bash
gcloud auth login
# .env
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
```

**B variant — AI Studio kaliti:**

```bash
# .env
GEMINI_API_KEYS=key1,key2
python uztts.py kitob.txt --backend aistudio
```

> Bepul AI Studio kalitlari kuniga atigi bir necha TTS so'roviga ruxsat beradi (taxminan 10 ta). Boshlashdan oldin matn uchun nechta so'rov kerakligini bilish uchun `--dry-run` dan foydalaning.

## Foydalanish

```bash
python uztts.py kitob.txt                         # -> kitob.mp3 + kitob_vaqtlar.txt, ovoz Iapetus
python uztts.py kitob.txt --voice Kore -o out.mp3 # boshqa ovoz, o'zingiz bergan fayl nomi
python uztts.py kitob.txt --dry-run               # faqat hisob-kitob: bo'laklar, davomiylik, so'rovlar
python uztts.py kitob.txt --workers 4 --bitrate 192k
python uztts.py kitob.txt --model gemini-2.5-flash-preview-tts
```

| Parametr | Standart | Tavsif |
| --- | --- | --- |
| `input` | — | UTF-8 matn fayli. Bo'sh qator = yangi paragraf. |
| `-o, --output` | `<input>.mp3` | Natija MP3 fayl yo'li. |
| `--voice` | `Iapetus` | Gemini'ning tayyor ovozi: `Iapetus` (vazmin), `Puck` (quvnoq), `Charon` (axborot uslubida), `Kore`, `Leda` (ayol ovozi), `Achird`, `Fenrir`, `Zephyr`, … |
| `--model` | `gemini-3.8-flash-tts` | Istalgan Gemini TTS model id'si. |
| `--style` | o'chiq | Ixtiyoriy uslub prefiksi, masalan `"Say calmly"`. Standart holatda o'chiq, chunki model ba'zan ko'rsatmaning o'zini ovoz chiqarib o'qib yuboradi. |
| `--chunk` | `650` | Bitta so'rovdagi maksimal belgilar soni (bitta javob ~45 soniyadan oshmasin). |
| `--workers` | `2` | Parallel so'rovlar soni. |
| `--backend` | `vertex` | `vertex` yoki `aistudio`. |
| `--bitrate` | `128k` | MP3 bitreyti. |
| `--dry-run` | — | Rejani chiqaradi, hech narsa yaratmaydi. |

CLI xabarlari o'zbek tilida, chunki vosita aynan o'zbekcha so'zlashuvchilar uchun.

## Qanday ishlaydi

```text
text.txt ─► normallashtirish ─► bo'laklarga bo'lish ─► Gemini TTS (parallel, qayta urinish bilan)
                                                           │  24 kHz PCM
                                                           ▼
                                           cache/<backend_model_voice>/<md5>.pcm
                                                           │  portlash + jimlikni kesish, fade'lar
                                                           ▼
                     pauzalar bilan ulash (diskda) ─► ffmpeg loudnorm -16 LUFS ─► out.mp3
                                                                                 └► out_vaqtlar.txt
```

## Litsenziya

[MIT](LICENSE) © 2026 xoliddev
