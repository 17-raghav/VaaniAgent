"""Turns a user utterance into a tool call with ONE Sarvam-105B chat call."""
import json
import re

TOOL_NAMES = {"web_search", "play_youtube", "open_app", "send_whatsapp", "ask_user"}

SYSTEM_PROMPT = """You are VaaniAgent, a voice assistant on a Windows PC. Users speak Hindi, Bangla, Hinglish, English or other Indian languages.
Reply with ONLY one JSON object and nothing else:
{"english": "<the instruction translated to English>", "user_lang": "<code like hi-IN, bn-IN, en-IN>", "tool": "<tool name>", "args": {...}, "reply": "<one short spoken sentence in the user's language>"}

Tools:
- web_search: {"query": str}
- play_youtube: {"song": str}
- open_app: {"name": str}  (only "notepad", "calculator", "file explorer", "kivi" work; for any other app still use open_app with that name)
- send_whatsapp: {"contact": str (name or phone digits), "message": str}
- ask_user: {"question": "<question in the user's language>"}

Rules:
- If anything required is missing (for example the message text or contact for send_whatsapp), use ask_user.
- Write "reply" in native script: Devanagari for Hindi and Hinglish, Bengali script for Bangla.
- For send_whatsapp, "reply" asks the user to confirm sending.
- When the user answers your question, use the earlier turns to complete the task.

Examples:
User: YouTube pe Kishore Kumar ka gaana chalao
{"english": "Play a Kishore Kumar song on YouTube", "user_lang": "hi-IN", "tool": "play_youtube", "args": {"song": "Kishore Kumar songs"}, "reply": "यूट्यूब पर किशोर कुमार का गाना चला रही हूँ।"}
User: নোটপ্যাড খোলো
{"english": "Open notepad", "user_lang": "bn-IN", "tool": "open_app", "args": {"name": "notepad"}, "reply": "নোটপ্যাড খুলছি।"}
User: Papa ko message bhejo
{"english": "Send a message to Papa", "user_lang": "hi-IN", "tool": "ask_user", "args": {"question": "पापा को क्या मैसेज भेजना है?"}, "reply": ""}
User: search weather in Kolkata
{"english": "Search weather in Kolkata", "user_lang": "en-IN", "tool": "web_search", "args": {"query": "weather in Kolkata"}, "reply": "Searching Google for weather in Kolkata."}"""

RETRY_NOTE = "Your last reply was not valid JSON. Reply with ONLY the JSON object."
MAX_HISTORY = 8  # messages kept (user + assistant)


def parse_plan(text):
    """Extract and validate the plan JSON. Returns a dict, or None if invalid."""
    if not text:
        return None
    text = re.sub(r"```(?:json)?", "", text)  # strip code fences
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        plan = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(plan, dict) or plan.get("tool") not in TOOL_NAMES:
        return None
    if not isinstance(plan.get("args"), dict):
        return None
    plan.setdefault("english", "")
    plan.setdefault("user_lang", "hi-IN")
    plan.setdefault("reply", "")
    return plan


def enforce_rules(plan):
    """Safety net: never let send_whatsapp through with a missing message or contact."""
    if plan["tool"] == "send_whatsapp":
        a = plan["args"]
        if not str(a.get("message", "")).strip() or not str(a.get("contact", "")).strip():
            q = "किसे और क्या मैसेज भेजना है?" if plan["user_lang"] == "hi-IN" else \
                "Who should I message, and what should it say?"
            plan.update(tool="ask_user", args={"question": q}, reply="")
    return plan


class Planner:
    def __init__(self, client):
        self.client = client
        self.history = []

    def plan(self, user_text):
        """One chat call (plus at most one retry). Returns a plan dict.
        tool == "please_repeat" means the model failed twice."""
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, *self.history,
                    {"role": "user", "content": user_text}]
        raw = self.client.chat(messages)
        plan = parse_plan(raw)
        if plan is None:  # retry once
            messages += [{"role": "assistant", "content": raw or "(empty)"},
                         {"role": "user", "content": RETRY_NOTE}]
            raw = self.client.chat(messages)
            plan = parse_plan(raw)
        if plan is None:
            return {"english": "", "user_lang": "en-IN", "tool": "please_repeat",
                    "args": {}, "reply": ""}
        plan = enforce_rules(plan)
        self.history += [{"role": "user", "content": user_text},
                         {"role": "assistant", "content": json.dumps(plan, ensure_ascii=False)}]
        self.history = self.history[-MAX_HISTORY:]
        return plan
