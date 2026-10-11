"""VaaniAgent CLI.

  py -m vaani.main            voice: mic -> Saaras -> Sarvam-105B -> tool (reply printed)
  py -m vaani.main --text     type instead of speaking (no mic, no STT call)
  py -m vaani.main --mock     canned responses, ZERO API calls
  py -m vaani.main --tts      also speak replies with Bulbul (1 extra call per reply)
"""
import argparse
import os
import sys

from vaani import audio, tools
from vaani.planner import Planner
from vaani.sarvam_client import SarvamClient

# Fixed replies for cases the model does not phrase (refusal, cancel, repeat).
MESSAGES = {
    "hi-IN": {"refused": "माफ़ कीजिए, मैं सिर्फ़ नोटपैड, कैलकुलेटर, फ़ाइल एक्सप्लोरर या कीवी खोल सकती हूँ।",
              "cancelled": "ठीक है, मैसेज नहीं भेजा।",
              "repeat": "माफ़ कीजिए, समझ नहीं आया। कृपया फिर से बोलिए।",
              "done": "हो गया।"},
    "bn-IN": {"refused": "দুঃখিত, আমি শুধু নোটপ্যাড, ক্যালকুলেটর, ফাইল এক্সপ্লোরার বা কিভি খুলতে পারি।",
              "cancelled": "ঠিক আছে, মেসেজ পাঠানো হয়নি।",
              "repeat": "দুঃখিত, বুঝতে পারিনি। আবার বলুন।",
              "done": "হয়ে গেছে।"},
    "en-IN": {"refused": "Sorry, I can only open notepad, calculator, file explorer or Kivi.",
              "cancelled": "Okay, I did not send the message.",
              "repeat": "Sorry, I didn't understand. Please say that again.",
              "done": "Done."},
}


def msg(lang, key):
    return MESSAGES.get(lang, MESSAGES["en-IN"])[key]


class Agent:
    def __init__(self, text_mode, mock, tts):
        self.client = SarvamClient(mock=mock)
        self.planner = Planner(self.client)
        self.text_mode = text_mode or mock  # mock never records audio
        self.tts = tts and not mock

    def listen(self):
        """Get one user utterance (typed or spoken). Returns '' to skip, None to quit."""
        if self.text_mode:
            text = input("\nYou (q to quit): ").strip()
            return None if text.lower() == "q" else text
        if input("\nPress Enter to start speaking (q to quit): ").strip().lower() == "q":
            return None
        wav = audio.record()
        if wav is None:  # accidental double Enter: don't waste an STT credit
            print("  Too short, try again.")
            return ""
        transcript, lang = self.client.stt(wav)
        print(f"  Transcript [{lang}]: {transcript}")
        return transcript.strip()

    def speak(self, text, lang):
        print(f"Vaani: {text}")
        if text and self.tts:
            audio.play(self.client.tts(text, lang))

    def handle(self, text):
        """Plan and act. ask_user loops back here with the user's answer (max 3 rounds)."""
        for _ in range(3):
            plan = self.planner.plan(text)
            lang, tool, args = plan["user_lang"], plan["tool"], plan["args"]
            print(f"  English: {plan['english']}\n  Plan: {tool} {args}")

            if tool == "please_repeat":
                return self.speak(msg("hi-IN", "repeat"), "hi-IN")
            if tool == "ask_user":
                self.speak(args.get("question", ""), lang)
                text = self.listen()
                if not text:
                    return
                continue
            return self.execute(tool, args, plan["reply"], lang)

    def execute(self, tool, args, reply, lang):
        if tool == "send_whatsapp":
            self.speak(reply or f"Send to {args['contact']}: {args['message']}?", lang)
            confirm = lambda: input("  Confirm send? (y/n, haan/nahi): ")
            if tools.send_whatsapp(args["contact"], args["message"], confirm):
                return self.speak(msg(lang, "done"), lang)
            return self.speak(msg(lang, "cancelled"), lang)
        if tool == "open_app":
            ok = tools.open_app(args.get("name", ""))
        elif tool == "web_search":
            ok = tools.web_search(args.get("query", ""))
        elif tool == "play_youtube":
            ok = tools.play_youtube(args.get("song", ""))
        else:
            ok = False
        if ok:
            self.speak(reply or msg(lang, "done"), lang)
        else:
            self.speak(msg(lang, "refused"), lang)

    def run(self):
        mode = "MOCK (no API calls)" if self.client.mock else ("text" if self.text_mode else "voice")
        print(f"VaaniAgent ready - {mode} mode")
        while True:
            text = self.listen()
            if text is None:
                break
            if text:
                self.handle(text)
        print(f"Bye. API calls this session: {self.client.count}")


def main():
    p = argparse.ArgumentParser(description="VaaniAgent - Indian-language voice agent")
    p.add_argument("--text", action="store_true", help="type instead of speaking (no STT)")
    p.add_argument("--mock", action="store_true", help="canned responses, zero API calls")
    p.add_argument("--tts", action="store_true", help="speak replies with Bulbul")
    a = p.parse_args()
    if not a.mock and not os.environ.get("SARVAM_API_KEY"):
        sys.exit("SARVAM_API_KEY is not set. Run: set SARVAM_API_KEY=<your key>")
    Agent(a.text, a.mock, a.tts).run()


if __name__ == "__main__":
    main()
