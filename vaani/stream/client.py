"""Test harness: behaves like the organiser's client and scores latency.

  python -m vaani.stream.client --wav sample.wav [--url ws://localhost:8000/ws] [--server-log logs]

Protocol (PS 5.1): session_start, then frame k of 80 ms at t = k * 80 ms, the last
frame zero-padded; input_end with valid_samples; then silent frames every 80 ms
until session_complete. Output frames are played in arrival order: each starts
when it arrives or when the previous one finishes, whichever is later.
"""
import argparse
import asyncio
import json
import time
from pathlib import Path

import numpy as np
import soundfile as sf
from websockets.asyncio.client import connect

from .metrics import compute_metrics, render_playback

SR = 24000
FRAME = 1920                      # samples per 80 ms frame


def load_pcm(path):
    x, sr = sf.read(path, dtype="float32")
    if x.ndim == 2:
        x = x.mean(1)
    if sr != SR:
        from math import gcd
        from scipy.signal import resample_poly
        g = gcd(sr, SR)
        x = resample_poly(x, SR // g, sr // g).astype(np.float32)
    return (np.clip(x, -1, 1) * 32767).astype("<i2")


async def run_session(url, pcm: np.ndarray, sid="s-0001", speed=1.0):
    """Returns (arrivals [(t_seconds, bytes)], timings dict, problems list).
    speed > 1 compresses wall-clock time (tests only); reported times are session time."""
    valid = len(pcm)
    n_frames = -(-valid // FRAME)
    padded = np.zeros(n_frames * FRAME, dtype="<i2")
    padded[:valid] = pcm
    arrivals, problems, texts = [], [], []
    done = asyncio.Event()

    async with connect(url, max_size=2**21, compression=None, open_timeout=10) as ws:
        await ws.send(json.dumps({"type": "session_start", "session_id": sid, "sample_rate": SR,
                                  "encoding": "pcm_s16le", "source_language": "hi",
                                  "target_language": "en"}))
        t0 = time.monotonic()
        clock = lambda: (time.monotonic() - t0) * speed

        async def receive():
            async for msg in ws:
                if isinstance(msg, bytes):
                    if texts:
                        problems.append("audio after session_complete")
                    if len(msg) > SR * 2:
                        problems.append(f"output frame longer than 1 s ({len(msg)} bytes)")
                    arrivals.append((clock(), msg))
                else:
                    texts.append(msg)
                    m = json.loads(msg)
                    if m.get("type") != "session_complete" or len(texts) > 1:
                        problems.append(f"unexpected text frame: {msg}")
                    done.set()
                    return

        rx = asyncio.create_task(receive())
        for k in range(n_frames):
            await asyncio.sleep(max(0.0, t0 + k * 0.08 / speed - time.monotonic()))
            await ws.send(padded[k * FRAME:(k + 1) * FRAME].tobytes())
        await ws.send(json.dumps({"type": "input_end", "session_id": sid, "valid_samples": valid}))
        t_end = clock()
        silence = bytes(FRAME * 2)
        k = n_frames
        while not done.is_set():
            await asyncio.sleep(max(0.0, t0 + k * 0.08 / speed - time.monotonic()))
            if done.is_set():
                break
            await ws.send(silence)
            k += 1
            if clock() - t_end > 30:
                problems.append("no session_complete within 30 s of input_end")
                break
        await asyncio.wait_for(rx, timeout=5)
    return arrivals, {"input_end": t_end, "valid_s": valid / SR}, problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wav", required=True, nargs="+", help="wav files and/or folders of wavs")
    ap.add_argument("--url", default="ws://localhost:8000/ws")
    ap.add_argument("--server-log", default="logs", help="server log dir for LAAL (optional)")
    ap.add_argument("--out", default="results")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(exist_ok=True)
    wavs = []
    for w in a.wav:                       # a folder means: every .wav inside it, sorted
        p = Path(w)
        wavs += sorted(str(x) for x in p.glob("*.wav")) if p.is_dir() else [w]
    if not wavs:
        raise SystemExit("no .wav files found")
    rows = []
    for i, wav in enumerate(wavs):
        sid = f"s-{i + 1:04d}"
        pcm = load_pcm(wav)
        arrivals, timing, problems = asyncio.run(run_session(a.url, pcm, sid))
        time.sleep(2)                          # PS: 2 s gap between sessions
        log = Path(a.server_log) / f"{sid}.json"
        clauses = json.loads(log.read_text(encoding="utf-8"))["clauses"] if log.exists() else None
        m = compute_metrics(arrivals, pcm, timing, clauses)
        m.update(wav=wav, problems=problems)
        sf.write(out / f"{sid}_out.wav", render_playback(arrivals), SR, subtype="PCM_16")
        rows.append(m)
        print(json.dumps(m, ensure_ascii=False))
    keys = [k for k in ("start_lag_s", "end_offset_s", "laal_s") if all(r.get(k) is not None for r in rows)]
    summary = {k: round(float(np.mean([r[k] for r in rows])), 3) for k in keys}
    summary["sessions"], summary["failed"] = len(rows), sum(bool(r["problems"]) for r in rows)
    (out / "summary.json").write_text(json.dumps({"summary": summary, "sessions": rows},
                                                 ensure_ascii=False, indent=1), encoding="utf-8")
    print("summary:", summary)


if __name__ == "__main__":
    main()
