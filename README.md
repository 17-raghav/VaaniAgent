# VaaniAgent

Voice agent for Windows. Speak an instruction in Hindi, Bangla, Hinglish or English; VaaniAgent understands it and does one simple action on the PC.

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
| `py -m pytest -q` | 0 |
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
