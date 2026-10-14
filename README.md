# VaaniAgent

Two modes on one Sarvam client:

1. **Voice agent** (Windows): speak an instruction in Hindi, Bangla, Hinglish or English; VaaniAgent understands it and does one simple action on the PC.
2. **Streaming interpreter** (`vaani/stream`, any OS / Docker): Hindi speech in, English speech out *while the speaker is still talking*, over WebSockets, following the Inter IIT 15.0 / Sarvam speech-to-speech protocol. See [Streaming interpreter](#streaming-interpreter).

Pipeline per turn: mic (press Enter to start, Enter again to stop; max 30 s) -> Saaras `saaras:v4` STT -> Sarvam-105B (translation + plan in one JSON) -> tool. Reply is printed; add `--tts` to also speak it with Bulbul `bulbul:v4-flash`.

Tools: `web_search`, `play_youtube`, `open_app` (only the apps listed below), `send_whatsapp` (opens WhatsApp Web pre-filled, never sends), `ask_user`.

## Setup (Command Prompt, not PowerShell)

```
cd /d D:\Sarvam
py -m venv .venv
.venv\Scripts\activate
py -m pip install -r requirements.txt
```

`SARVAM_API_KEY` must be set in the session (`set SARVAM_API_KEY=...`).

## Apps it can open

| App | Say (Hindi) | Say (Bangla) |
|---|---|---|
| Notepad | नोटपैड खोलो | নোটপ্যাড খোলো |
| Calculator | कैलकुलेटर खोलो | ক্যালকুলেটর খোলো |
| File Explorer | फ़ाइल एक्सप्लोरर खोलो | ফাইল এক্সপ্লোরার খোলো |
| Kivi | कीवी खोलो | কিভি খোলো |

Anything else is refused: "माफ़ कीजिए, मैं सिर्फ़ नोटपैड, कैलकुलेटर, फ़ाइल एक्सप्लोरर या कीवी खोल सकती हूँ।"

To add an app, add its name and exe path to `APPS` in `vaani/tools.py`.

## Run

| Command | API calls per turn |
|---|---|
| `py -m pytest -q` (29 tests) | 0 |
| `py -m vaani.main --mock` | 0 |
| `py -m vaani.main --text` | 1 chat |
| `py -m vaani.main` | 1 STT + 1 chat |
| `py -m vaani.main --tts` | 1 STT + 1 chat + 1 TTS |

With `--tts`, a WhatsApp turn adds one TTS call for the confirmation question. An `ask_user` turn adds one chat call (plus STT/TTS in voice mode). Invalid JSON from the model triggers one retry.

Every real call is appended to `calls.log` and the running count is printed.

## Safety

- The model only picks a tool name from a fixed list; each name maps to a fixed Python function. Nothing from the model is run as a shell command.
- `open_app` uses a whitelist. Anything else (cmd, powershell, ...) is refused.
- `send_whatsapp` asks for confirmation first (type `y` / `haan` / `ok`). It only opens WhatsApp Web; you click Send.
- `send_whatsapp` with an empty message or contact is converted to `ask_user` in code.

## Files

- `vaani/main.py` - CLI and agent loop
- `vaani/sarvam_client.py` - STT, chat, TTS wrappers, call logging, mock mode
- `vaani/planner.py` - system prompt, JSON parsing, retry, history
- `vaani/tools.py` - the five tools
- `vaani/audio.py` - record and play
- `tests/test_planner.py` - acceptance tests (zero API calls)
- `vaani/stream/` - streaming interpreter: `server.py`, `policy.py`, `backend.py`, `client.py` (test harness), `metrics.py`
- `tests/test_stream_*.py` - policy unit tests + a full WebSocket round trip on a mock backend

## Streaming interpreter

v1 above is push-to-talk: record, then one STT call. v2 listens continuously and must decide
*when to speak*. Hindi is verb-final: in "मैंने कल अपना पुराना बैंक खाता बंद करवा दिया" the meaning
(opened? closed?) arrives with the last words, and audio once played can't be taken back.

Three layers decide (`vaani/stream/policy.py`):

1. **Pause detection**: cut the audio into segments at ≥350 ms of silence.
2. **LocalAgreement-2**: re-run ASR on the open segment every 1 s; commit only the words two consecutive passes agree on.
3. **Clause gate**: hold committed words until a clause closes (a clause-final verb or auxiliary such as है/था/दिया/कीजिए, a pause, or punctuation). Never cut inside an amount ("दो लाख | पचास हज़ार").

Per session, three asyncio tasks (`vaani/stream/server.py`): a **reader** that never blocks (the harness fails a session if a frame waits > 1 s), a **listener** (ASR + policy; model calls in threads), and a **speaker** (MT + TTS in order, ≤1 s PCM frames, then exactly one `session_complete`).

Models: Saaras v3 → Mayura → Bulbul v3 voice `shubh` at 24 kHz, all through `SarvamClient` (same `calls.log`). This is a cascade. The competition bans cascades in its submission (errors compound across three models, latencies add, prosody is lost); its end-to-end checkpoint must translate audio to audio itself.

### Run

```
py -m pip install -r requirements.txt
set SARVAM_API_KEY=...
py -m vaani.stream.server                          # terminal 1: ws://localhost:8000/ws, /health
py -m vaani.stream.client --wav input.wav          # terminal 2: results\summary.json, results\s-0001_out.wav
```

Docker:

```
docker build -t vaani-stream .
docker run --rm -p 8000:8000 -e SARVAM_API_KEY=%SARVAM_API_KEY% -v %cd%\logs:/app/logs vaani-stream
py -m vaani.stream.client --wav clip1.wav clip2.wav --server-log logs
```

### Latency metrics (`vaani/stream/metrics.py`, on the listener's playback timeline)

| Metric | Definition |
|---|---|
| Start lag | first English sound − first Hindi speech |
| End Offset | last English sound − last Hindi speech |
| LAAL (approx.) | average lag of each English word behind the source (Papi et al. 2022); word times spread uniformly within each clause's audio |

### Measured (2026-10-14, 3 real IndicVoices Hindi clips, 9–11 s each, ASR every 2 s)

| Clip | Length | Start lag | End Offset | LAAL |
|---|---|---|---|---|
| rec-r00003 | 10.8 s | 7.6 s | 8.2 s | 6.8 s |
| rec-r00001 | 9.6 s | 3.2 s | 3.1 s | 5.5 s |
| rec-r00004 | 9.3 s | 6.1 s | 5.4 s | 6.0 s |
| **Mean** | | **5.6 s** | **5.6 s** | **6.1 s** |

3/3 sessions passed the protocol (no late frames, one `session_complete`). Sarvam spend ₹1.92
(STT ₹0.45, translate ₹0.52, TTS ₹0.95). Entities survived: "100 किलोमीटर" → "100 kilometers",
"पचमढ़ी" → "Pachmarhi".

Where the latency goes, and what would cut it:
- **LocalAgreement waits for two agreeing ASR passes** 2 s apart, so a word is committed 2–4 s after it is
  spoken. A 1 s step roughly halves this at twice the ASR cost.
- **MT and TTS run one after another per clause** (REST calls). Bulbul's streaming TTS would start audio
  before the whole sentence is synthesised.
- **Extempore speech has hesitation pauses**, so the pause rule flushes fragments ("काफी।" → "Enough.").
  Requiring a minimum clause length before a pause flush would trade a little lag for much better translations.
