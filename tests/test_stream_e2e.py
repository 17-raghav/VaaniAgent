"""Full protocol round trip with the mock backend (no network beyond localhost)."""
import asyncio
import json

import numpy as np

from vaani.stream.backend import MockBackend
from vaani.stream.client import run_session
from vaani.stream.server import serve_forever

SCRIPT = ("मैंने कल अपना पुराना बैंक खाता बंद करवा दिया। मुझे ढाई लाख रुपये "
          "वापस मिलने हैं लेकिन अभी तक नहीं मिले।").split()


def speechy(seconds_on, gap, sr=24000):
    rng = np.random.default_rng(1)
    parts = []
    for i, s in enumerate(seconds_on):
        parts.append(0.3 * rng.standard_normal(int(s * sr)))
        if i < len(seconds_on) - 1:
            parts.append(np.zeros(int(gap * sr)))
    return (np.concatenate(parts) * 32767).astype("<i2")


def test_protocol_round_trip(tmp_path):
    async def go():
        ready = asyncio.Event()
        srv = asyncio.create_task(serve_forever(lambda: MockBackend(SCRIPT, words_per_sec=2.5),
                                                host="127.0.0.1", port=8765, log_dir=tmp_path, ready=ready))
        await ready.wait()
        try:
            return await run_session("ws://127.0.0.1:8765/ws", speechy([3.0, 3.0], 0.6), "s-test", speed=3.0)
        finally:
            srv.cancel()
            await asyncio.gather(srv, return_exceptions=True)   # let the server close cleanly
    arrivals, timing, problems = asyncio.run(go())
    assert problems == []
    assert arrivals, "server produced no audio"
    assert all(len(b) <= 48000 for _, b in arrivals)
    log = json.loads((tmp_path / "s-test.json").read_text(encoding="utf-8"))
    said = " ".join(c["hi"] for c in log["clauses"]).replace("~", "").split()
    spoken = SCRIPT[: int(6.6 * 2.5)]          # what the fake speaker says in 6.6 s
    assert said == spoken                      # no word lost or repeated across segment cuts
    assert all("out_start" in c for c in log["clauses"])
