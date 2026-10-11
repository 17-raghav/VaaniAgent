"""Thin wrappers around the Sarvam SDK: STT, chat, TTS.

Every real API call is logged to calls.log and counted on the console.
In mock mode no API call is ever made; canned responses are returned instead.
"""
import json
import os
from datetime import datetime

LOG_FILE = "calls.log"
TTS_LANGS = {"bn-IN", "en-IN", "gu-IN", "hi-IN", "kn-IN", "ml-IN", "mr-IN",
             "od-IN", "pa-IN", "ta-IN", "te-IN"}


class SarvamClient:
    def __init__(self, mock=False, mock_replies=None):
        self.mock = mock
        self.mock_replies = mock_replies  # optional list of raw chat replies (tests)
        self.count = 0
        if not mock:
            from sarvamai import SarvamAI
            self.client = SarvamAI(api_subscription_key=os.environ["SARVAM_API_KEY"])

    def _log(self, kind):
        self.count += 1
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')} {kind}\n")
        print(f"  [API call #{self.count}: {kind}]")

    # ---- speech to text (Saaras) ----
    def stt(self, wav_path):
        """Return (transcript, language_code)."""
        if self.mock:
            return input("  (mock STT) type what you said: "), "hi-IN"
        self._log("stt saaras:v4")
        with open(wav_path, "rb") as f:
            r = self.client.speech_to_text.transcribe(
                file=f, model="saaras:v4", mode="transcribe")
        return r.transcript, r.language_code

    # ---- chat (Sarvam-105B) ----
    def chat(self, messages):
        """Return the raw text content of one chat completion."""
        if self.mock:
            return self._mock_chat(messages)
        self._log("chat sarvam-105b")
        r = self.client.chat.completions(
            messages=messages, model="sarvam-105b",
            temperature=0.2, reasoning_effort="low")
        return r.choices[0].message.content or ""

    # ---- text to speech (Bulbul) ----
    def tts(self, text, lang, out_path="reply.wav"):
        """Synthesize text to a WAV file. Returns the path, or None in mock mode."""
        if self.mock:
            return None
        from sarvamai.play import save
        if lang not in TTS_LANGS:
            lang = "en-IN"
        self._log("tts bulbul:v4-flash")
        r = self.client.text_to_speech.convert(
            text=text, language_code=lang, model="bulbul:v4-flash")
        save(r, out_path)  # decodes the base64 audio chunks into one WAV
        return out_path

    # ---- canned chat replies for --mock ----
    def _mock_chat(self, messages):
        if self.mock_replies is not None:
            return self.mock_replies.pop(0)
        text = messages[-1]["content"].lower()
        prev = messages[-2]["content"] if len(messages) > 2 else ""

        def plan(english, tool, args, reply):
            return json.dumps({"english": english, "user_lang": "hi-IN", "tool": tool,
                               "args": args, "reply": reply}, ensure_ascii=False)

        # Answer to an earlier "what message?" question.
        if '"ask_user"' in prev and "message" in prev.lower():
            return plan(f"Send '{messages[-1]['content']}' to Mummy", "send_whatsapp",
                        {"contact": "Mummy", "message": messages[-1]["content"]},
                        "क्या मैं मम्मी को यह मैसेज भेजूँ?")
        if "youtube" in text or "gaana" in text:
            singer = "Arijit Singh" if "arijit" in text else text
            return plan("Play Arijit's song on YouTube", "play_youtube",
                        {"song": f"{singer} songs"}, "यूट्यूब पर गाना चला रही हूँ।")
        if "message" in text or "whatsapp" in text:
            return plan("Send a message to Mummy", "ask_user",
                        {"question": "मम्मी को क्या मैसेज भेजना है?"}, "")
        for app in ("notepad", "calculator", "explorer", "kivi", "cmd"):
            if app in text:
                return plan(f"Open {app}", "open_app", {"name": app}, f"{app} खोल रही हूँ।")
        if "search" in text or "dhundo" in text:
            return plan(f"Search for {text}", "web_search", {"query": text},
                        "गूगल पर खोज रही हूँ।")
        return plan("Unclear", "ask_user", {"question": "आप क्या करना चाहते हैं?"}, "")
