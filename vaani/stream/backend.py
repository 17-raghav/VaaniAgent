"""ASR, MT and TTS behind one small interface, so the streaming logic is testable
without any network (MockBackend) and runs for real through VaaniAgent's
SarvamClient (same call log and API-call counter as the voice agent).

This is a cascade (ASR -> MT -> TTS). That is fine for a portfolio system and is
exactly what the competition bans in the submitted model: errors compound across
three models, latencies add up, and prosody is lost. The competition's
end-to-end checkpoint translates audio -> audio directly.
"""
import io
import time
from math import gcd

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from vaani.sarvam_client import SarvamClient

OUT_SR = 24000


def _resample(x, sr_in, sr_out):
    if sr_in == sr_out:
        return x
    g = gcd(sr_in, sr_out)
    return resample_poly(x, sr_out // g, sr_in // g).astype(np.float32)


def _wav_bytes(x: np.ndarray, sr: int) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, (np.clip(x, -1, 1) * 32767).astype(np.int16), sr, subtype="PCM_16", format="WAV")
    return buf.getvalue()


class SarvamBackend:
    """Saaras v3 (ASR) -> Mayura (MT) -> Bulbul v3 'shubh' (TTS, 24 kHz).

    With a credit cap: once a call would pass it, the backend goes quiet
    (no more ASR, MT or TTS) instead of crashing the session, and says so once.
    """

    def __init__(self, tts_pace=1.1, max_credits=None):
        self.client = SarvamClient(mock=False, max_credits=max_credits)
        self.tts_pace = tts_pace
        self.out_of_credits = False

    def _guard(self, fn, empty):
        from vaani.budget import BudgetExceeded
        if self.out_of_credits:
            return empty
        try:
            return fn()
        except BudgetExceeded as e:
            self.out_of_credits = True
            print(f"  CREDIT CAP REACHED, going quiet: {e}")
            return empty

    def asr(self, x: np.ndarray, sr: int, offset: float = 0.0) -> list[str]:
        return self._guard(lambda: self.client.stt_pcm(
            _wav_bytes(_resample(x, sr, 16000), 16000)).split(), [])

    def mt(self, hindi: str) -> str:
        return self._guard(lambda: self.client.translate(hindi), "")

    def tts(self, english: str) -> np.ndarray:
        if not english.strip():
            return np.zeros(0, dtype=np.float32)

        def run():
            x, sr = sf.read(io.BytesIO(self.client.tts_english_24k(english, self.tts_pace)), dtype="float32")
            return _resample(x if x.ndim == 1 else x.mean(1), sr, OUT_SR)
        return self._guard(run, np.zeros(0, dtype=np.float32))


class MockBackend:
    """Deterministic stand-in: 'hears' a known script at a fixed speaking rate.

    ASR on a buffer starting at `offset` seconds returns the words spoken in that
    window; every second call garbles the last word (to exercise LocalAgreement).
    """

    def __init__(self, script: list[str], words_per_sec=2.5, delay=0.0):
        self.script, self.rate, self.delay = script, words_per_sec, delay
        self.calls = {"asr": 0, "mt": 0, "tts": 0}

    def asr(self, x, sr, offset=0.0):
        time.sleep(self.delay)
        self.calls["asr"] += 1
        a = int(round(offset * self.rate))
        b = int((offset + len(x) / sr) * self.rate)
        words = self.script[a:b]
        if words and self.calls["asr"] % 2 == 0:
            words = words[:-1] + [words[-1] + "~"]
        return words

    def mt(self, hindi):
        self.calls["mt"] += 1
        return f"EN[{hindi}]"

    def tts(self, english):
        self.calls["tts"] += 1
        n = int(0.25 * OUT_SR * max(1, len(english.split()) // 2))
        t = np.arange(n) / OUT_SR
        return (0.1 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
