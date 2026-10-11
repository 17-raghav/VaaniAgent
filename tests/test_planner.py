"""Acceptance tests. All run in mock mode: zero Sarvam API calls."""
import json

import pytest

from vaani import tools
from vaani.planner import Planner, parse_plan
from vaani.sarvam_client import SarvamClient


def make_planner(replies=None):
    return Planner(SarvamClient(mock=True, mock_replies=replies))


@pytest.fixture
def opened(monkeypatch):
    """Capture URLs instead of opening a browser."""
    urls = []
    monkeypatch.setattr(tools.webbrowser, "open", urls.append)
    return urls


def test_youtube_arijit():
    plan = make_planner().plan("YouTube pe Arijit ka gaana chalao")
    assert plan["tool"] == "play_youtube"
    assert "Arijit" in plan["args"]["song"]


def test_message_without_text_asks_first():
    planner = make_planner()
    first = planner.plan("Mummy ko message bhejo")
    assert first["tool"] == "ask_user"
    second = planner.plan("Khana kha liya?")  # user's answer, uses history
    assert second["tool"] == "send_whatsapp"
    assert second["args"]["message"] == "Khana kha liya?"


def test_send_whatsapp_with_empty_message_is_forced_to_ask_user():
    bad = json.dumps({"english": "msg mummy", "user_lang": "hi-IN", "tool": "send_whatsapp",
                      "args": {"contact": "Mummy", "message": ""}, "reply": ""})
    assert make_planner([bad]).plan("Mummy ko message bhejo")["tool"] == "ask_user"


@pytest.mark.parametrize("answer", ["n", "nahi", "", "no thanks"])
def test_whatsapp_not_opened_without_yes(opened, answer):
    assert tools.send_whatsapp("Mummy", "hi", confirm=lambda: answer) is False
    assert opened == []


@pytest.mark.parametrize("answer", ["y", "haan", "Hya", "ok bhejo", "हाँ"])
def test_whatsapp_opened_after_yes(opened, answer):
    assert tools.send_whatsapp("9876543210", "hello maa", confirm=lambda: answer) is True
    assert opened == ["https://web.whatsapp.com/send?text=hello+maa&phone=9876543210"]


def test_play_youtube_opens_first_video(monkeypatch, opened):
    page = b'..."videoId":"abcDEF12345"...'
    monkeypatch.setattr(tools.urllib.request, "urlopen",
                        lambda req, timeout: type("R", (), {"read": lambda self: page})())
    tools.play_youtube("Fitoor Arijit Singh")
    assert opened == ["https://www.youtube.com/watch?v=abcDEF12345"]


def test_play_youtube_falls_back_to_search(monkeypatch, opened):
    def fail(req, timeout):
        raise OSError("offline")
    monkeypatch.setattr(tools.urllib.request, "urlopen", fail)
    tools.play_youtube("Fitoor")
    assert opened == ["https://www.youtube.com/results?search_query=Fitoor"]


def test_invalid_json_retries_once_then_please_repeat():
    replies = ["not json", "still {broken"]
    plan = make_planner(replies).plan("kuch bhi")
    assert plan["tool"] == "please_repeat"
    assert replies == []  # exactly two chat calls were made


def test_invalid_json_then_valid_on_retry():
    good = '```json\n{"english": "open notepad", "user_lang": "hi-IN", "tool": "open_app", "args": {"name": "notepad"}}\n```'
    replies = ["oops", good]
    assert make_planner(replies).plan("notepad kholo")["tool"] == "open_app"


def test_parse_plan_rejects_unknown_tool():
    assert parse_plan('{"tool": "run_shell", "args": {"cmd": "del *"}}') is None


@pytest.mark.parametrize("name", ["cmd", "powershell", "regedit", "cmd.exe", ""])
def test_open_app_refuses_non_whitelisted(monkeypatch, name):
    launched = []
    monkeypatch.setattr(tools.subprocess, "Popen", launched.append)
    assert tools.open_app(name) is False
    assert launched == []


def test_open_app_kivi_is_allowed(monkeypatch):
    launched = []
    monkeypatch.setattr(tools.subprocess, "Popen", launched.append)
    assert tools.open_app("Kivi") is True
    assert launched[0][0].endswith(r"Kivi\Kivi.App.exe")


def test_mock_client_makes_no_api_calls():
    client = SarvamClient(mock=True)
    Planner(client).plan("YouTube pe Arijit ka gaana chalao")
    assert client.count == 0
    assert client.tts("hello", "hi-IN") is None
