"""VaaniAgent streaming interpreter: Hindi -> English speech over WebSockets,
implementing the Inter IIT / Sarvam protocol (PS section 5.1).

  ws://host:8000/ws   one connection = one session
  GET /health         200 when ready

Three asyncio tasks per session, so slow model calls never stop us reading
(the harness fails a session if a frame waits > 1 s to be read):

  reader   receives 80 ms PCM frames, session_start, input_end   (never blocks)
  listener every STEP seconds: ASR on the open segment -> LocalAgreement ->
           ClauseGate; cuts the segment at pauses           (model calls in threads)
  speaker  MT + TTS per clause, in order; sends <= 1 s PCM frames; after the last
           clause sends the single session_complete text frame
"""
import argparse
import asyncio
import json
import time
from http import HTTPStatus
from pathlib import Path

import numpy as np
from websockets.asyncio.server import serve

from .policy import ClauseGate, LocalAgreement, PauseDetector

SR = 24000
FRAME_BYTES = 3840                 # 80 ms of 16-bit mono at 24 kHz
MAX_OUT = SR * 2                   # 1 s of output per frame (bytes = samples * 2)
STEP = 2.0                         # seconds of new audio between ASR passes (1.0 = lower lag, ~2x ASR cost)
MAX_SEG = 25.0                     # force a cut (Saaras REST takes <= 30 s)
FINISH_BUDGET = 25.0               # PS: session_complete within 30 s of input_end


class Session:
    def __init__(self, ws, backend, log_dir: Path | None):
        self.ws, self.backend, self.log_dir = ws, backend, log_dir
        self.pcm = bytearray()
        self.sid = "unknown"
        self.valid = None
        self.started = asyncio.Event()
        self.ended = asyncio.Event()
        self.t0 = None
        self.seg_start = 0          # sample index where the open segment starts
        self.la, self.gate = LocalAgreement(), ClauseGate()
        self.pause = PauseDetector(SR)
        self.clauses: asyncio.Queue = asyncio.Queue()
        self.sent_bytes = 0
        self.events = []
        self.end_time = None

    def now(self):
        return time.monotonic() - self.t0 if self.t0 else 0.0

    # ---------------- reader ----------------
    async def reader(self):
        async for msg in self.ws:
            if isinstance(msg, bytes):
                if not self.ended.is_set():          # post-input_end silence is ignored
                    self.pcm.extend(msg)
                continue
            m = json.loads(msg)
            if m.get("type") == "session_start":
                self.sid, self.t0 = m.get("session_id", "s"), time.monotonic()
                self.started.set()
            elif m.get("type") == "input_end":
                self.valid = int(m["valid_samples"])
                self.end_time = time.monotonic()
                self.ended.set()

    def audio(self, a, b):
        x = np.frombuffer(bytes(self.pcm[2 * a: 2 * b]), dtype=np.int16)
        return x.astype(np.float32) / 32768

    def n_samples(self):
        n = len(self.pcm) // 2
        return min(n, self.valid) if self.valid is not None else n

    # ---------------- listener ----------------
    async def _asr(self, a, b):
        return await asyncio.to_thread(self.backend.asr, self.audio(a, b), SR, a / SR)

    async def _emit(self, words, flush=False):
        clauses = self.gate.push(words) + (self.gate.flush() if flush else [])
        for c in clauses:
            self.events.append({"t": round(self.now(), 3), "src_s": round(self.n_samples() / SR, 3),
                                "hi": c})
            await self.clauses.put((c, self.events[-1]))

    async def listener(self):
        await self.started.wait()
        last_pass = 0
        while True:
            n = self.n_samples()
            if self.ended.is_set():
                if n > self.seg_start:
                    hyp = await self._asr(self.seg_start, n)
                    await self._emit(self.la.finalize(hyp), flush=True)
                else:
                    await self._emit([], flush=True)
                break
            if n - last_pass < STEP * SR:
                await asyncio.sleep(0.02)
                continue
            last_pass = n
            buf = self.audio(self.seg_start, n)
            cut = self.pause.last_pause(buf)
            if cut is not None and cut > 0.5 * SR:
                hyp = await self._asr(self.seg_start, self.seg_start + cut)
                self.seg_start += cut
                await self._emit(self.la.finalize(hyp), flush=True)
            elif len(buf) > MAX_SEG * SR:
                hyp = await self._asr(self.seg_start, n)
                self.seg_start = n
                await self._emit(self.la.finalize(hyp), flush=True)
            else:
                hyp = await self._asr(self.seg_start, n)
                await self._emit(self.la.update(hyp))
        await self.clauses.put(None)

    # ---------------- speaker ----------------
    async def speaker(self):
        while True:
            item = await self.clauses.get()
            if item is None:
                break
            hi, ev = item
            if self.end_time and time.monotonic() - self.end_time > FINISH_BUDGET:
                ev["skipped"] = "time budget"      # better silent than a failed session
                continue
            en = await asyncio.to_thread(self.backend.mt, hi)
            x = await asyncio.to_thread(self.backend.tts, en)
            pcm = (np.clip(x, -1, 1) * 32767).astype("<i2").tobytes()
            ev.update(en=en, out_start=self.sent_bytes, out_end=self.sent_bytes + len(pcm),
                      t_send=round(self.now(), 3))
            for i in range(0, len(pcm), MAX_OUT):
                await self.ws.send(pcm[i:i + MAX_OUT])
            self.sent_bytes += len(pcm)
        await self.ws.send(json.dumps({"type": "session_complete", "session_id": self.sid}))
        if self.log_dir:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            (self.log_dir / f"{self.sid}.json").write_text(
                json.dumps({"session_id": self.sid, "clauses": self.events}, ensure_ascii=False, indent=1),
                encoding="utf-8")

    async def run(self):
        reader = asyncio.create_task(self.reader())
        try:
            await asyncio.gather(self.listener(), self.speaker())
        finally:
            await asyncio.sleep(0.2)
            reader.cancel()


def make_handler(backend_factory, log_dir):
    async def handler(ws):
        await Session(ws, backend_factory(), log_dir).run()
    return handler


def health(connection, request):
    if request.path == "/health":
        return connection.respond(HTTPStatus.OK, "ok\n")
    if request.path != "/ws":
        return connection.respond(HTTPStatus.NOT_FOUND, "use /ws\n")
    return None


async def serve_forever(backend_factory, host="0.0.0.0", port=8000, log_dir=None, ready=None):
    async with serve(make_handler(backend_factory, log_dir), host, port,
                     process_request=health, max_size=2**20, compression=None) as server:
        if ready:
            ready.set()
        await server.serve_forever()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--backend", choices=["sarvam", "mock"], default="sarvam")
    ap.add_argument("--log-dir", default="logs")
    ap.add_argument("--step", type=float, default=2.0, help="seconds between ASR passes")
    ap.add_argument("--max-credits", type=float, default=8.0,
                    help="hard cap on Sarvam spend in ₹ across runs (ledger: stream_spend.json)")
    a = ap.parse_args()
    global STEP
    STEP = a.step
    if a.backend == "sarvam":
        from .backend import SarvamBackend
        factory = lambda: SarvamBackend(max_credits=a.max_credits)
    else:
        from .backend import MockBackend
        factory = lambda: MockBackend("मैंने कल अपना पुराना बैंक खाता बंद करवा दिया।".split())
    print(f"listening on :{a.port} (/ws, /health), backend={a.backend}, ASR every {STEP}s"
          + (f", credit cap ₹{a.max_credits}" if a.backend == "sarvam" else ""))
    asyncio.run(serve_forever(factory, port=a.port, log_dir=Path(a.log_dir)))


if __name__ == "__main__":
    main()
