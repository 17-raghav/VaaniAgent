"""Thin wrappers around the Sarvam SDK: STT, chat, TTS (agent) and in-memory
STT, translation and 24 kHz English TTS (streaming interpreter, vaani/stream).

Every real API call is logged to calls.log and counted on the console.
In mock mode no API call is ever made; canned responses are returned instead.
"""
import base64
import io
import json
import os
from datetime import datetime

LOG_FILE = "calls.log"
TTS_LANGS = {"bn-IN", "en-IN", "gu-IN", "hi-IN", "kn-IN", "ml-IN", "mr-IN",
             "od-IN", "pa-IN", "ta-IN", "te-IN"}


class SarvamClient:
    def __init__(self, mock=False, mock_replies=None, max_credits=None):
        self.mock = mock
        # optional hard cap on Sarvam spend (₹) for the streaming interpreter
        self.ledger = None
        if max_credits is not None:
            from vaani.budget import Ledger
            self.ledger = Ledger("stream_spend.json", max_credits)
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

    # ---- streaming interpreter (vaani/stream) ----
    def _charge(self, kind, cost):
        """Refuse the call if it would pass the cap; otherwise record it."""
        if self.ledger is not None:
            self.ledger.check(kind, cost)
            self.ledger.record(kind, cost)

    def stt_pcm(self, wav_bytes: bytes) -> str:
        """Hindi ASR on an in-memory WAV (the open streaming segment). Saaras v3, transcribe mode."""
        if self.mock:
            return ""
        import soundfile as sf
        from vaani.budget import stt_cost
        self._charge("stt", stt_cost(sf.info(io.BytesIO(wav_bytes)).duration))
        self._log("stt saaras:v3 (stream)")
        r = self.client.speech_to_text.transcribe(
            file=("segment.wav", io.BytesIO(wav_bytes), "audio/wav"),
            model="saaras:v3", mode="transcribe", language_code="hi-IN")
        return r.transcript

    def translate(self, hindi: str) -> str:
        """Hindi -> English with Mayura; digits kept as digits."""
        if self.mock:
            return f"EN[{hindi}]"
        from vaani.budget import text_cost
        self._charge("translate", text_cost(hindi))
        self._log("translate mayura:v1")
        r = self.client.text.translate(input=hindi, source_language_code="hi-IN",
                                       target_language_code="en-IN", model="mayura:v1",
                                       numerals_format="international")
        return r.translated_text

    def tts_english_24k(self, text: str, pace: float = 1.1) -> bytes:
        """English speech, Bulbul v3 voice 'shubh' at 24 kHz (the voice the
        competition requires for its English targets). Returns WAV bytes."""
        if self.mock:
            return b""
        from vaani.budget import tts_cost
        self._charge("tts", tts_cost(text))
        self._log("tts bulbul:v3 shubh (stream)")
        r = self.client.text_to_speech.convert(
            text=text, language_code="en-IN", model="bulbul:v3", speaker="shubh",
            pace=pace, speech_sample_rate=24000)
        return base64.b64decode(r.audios[0])

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
