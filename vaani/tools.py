"""The only actions the agent can take. Model output is mapped to these fixed
functions by name; nothing from the model is ever run as a shell command."""
import os
import re
import subprocess
import urllib.request
import webbrowser
from urllib.parse import quote_plus

# Whitelist: spoken name -> executable
APPS = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "file explorer": "explorer.exe",
    "explorer": "explorer.exe",
    "kivi": os.path.expandvars(r"%LOCALAPPDATA%\Kivi\Kivi.App.exe"),
}
YES_WORDS = {"y", "yes", "haan", "han", "haa", "ha", "hya", "ok", "okay",
             "हाँ", "हां", "হ্যাঁ", "হ্যা"}


def web_search(query):
    webbrowser.open("https://www.google.com/search?q=" + quote_plus(query))
    return True


def play_youtube(song):
    """Open the first matching video so it starts playing.
    Falls back to the search results page if the lookup fails."""
    search_url = "https://www.youtube.com/results?search_query=" + quote_plus(song)
    try:
        req = urllib.request.Request(search_url, headers={"User-Agent": "Mozilla/5.0"})
        html = urllib.request.urlopen(req, timeout=5).read().decode("utf-8", "ignore")
        video_id = re.search(r'"videoId":"([\w-]{11})"', html).group(1)
        webbrowser.open("https://www.youtube.com/watch?v=" + video_id)
    except Exception:
        webbrowser.open(search_url)
    return True


def open_app(name):
    exe = APPS.get(name.strip().lower())
    if exe is None:
        return False  # not whitelisted: refuse
    subprocess.Popen([exe])
    return True


def is_yes(reply):
    words = re.findall(r"\w+|[^\w\s]+", reply.strip().lower())
    return any(w in YES_WORDS for w in words) or reply.strip().lower() in YES_WORDS


def send_whatsapp(contact, message, confirm):
    """Open WhatsApp Web with the message pre-filled. Never sends by itself.
    `confirm` is a function that returns the user's reply; we only proceed on yes."""
    if not is_yes(confirm()):
        return False
    url = "https://web.whatsapp.com/send?text=" + quote_plus(message)
    digits = re.sub(r"\D", "", contact)
    if len(digits) >= 10:
        url += "&phone=" + digits
    webbrowser.open(url)
    print("  WhatsApp opened. Pick the chat if needed and click Send yourself.")
    return True
