"""Latency on the listener's playback timeline.

start_lag_s   first English sound minus first Hindi speech
end_offset_s  last English sound minus last Hindi speech (PS: "how soon it finishes
              after the speaker stops"; Hibiki reports this as End Offset)
laal_s        Length-Adaptive Average Lagging (Papi et al. 2022), approximated:
              English word i is "emitted" when its share of its clause's audio plays
              (uniform spread inside the clause), d_i is that time, and
              LAAL = (1/tau) * sum_{i<=tau} [ d_i - (i-1) * |X| / max(|Y|, |Y*|) ]
              with |X| the source duration and tau the first word emitted after the
              source ended. Without a reference we use |Y*| = |Y|, which makes it
              plain Average Lagging on time.
"""
import numpy as np

SR = 24000


def playback(arrivals):
    """[(arrival_s, bytes)] -> list of (start_s, end_s, byte_offset_start, byte_offset_end)."""
    t, off, out = 0.0, 0, []
    for arr, b in arrivals:
        start = max(arr, t)
        end = start + len(b) / 2 / SR
        out.append((start, end, off, off + len(b)))
        t, off = end, off + len(b)
    return out


def byte_time(timeline, byte_pos):
    for start, end, a, b in timeline:
        if a <= byte_pos <= b:
            return start + (byte_pos - a) / 2 / SR
    return timeline[-1][1] if timeline else None


def voiced_bounds(pcm, thresh_db=-38.0):
    x = pcm.astype(np.float32) / 32768
    win = int(0.02 * SR)
    n = len(x) // win
    if n == 0:
        return 0.0, len(x) / SR
    rms = np.sqrt((x[: n * win].reshape(n, win) ** 2).mean(1) + 1e-12)
    loud = np.where(20 * np.log10(rms) > thresh_db)[0]
    if not len(loud):
        return 0.0, len(x) / SR
    return loud[0] * 0.02, (loud[-1] + 1) * 0.02


def compute_metrics(arrivals, pcm, timing, clauses=None):
    tl = playback(arrivals)
    speech_start, speech_end = voiced_bounds(pcm)
    m = {"source_s": round(len(pcm) / SR, 2), "output_s": round(sum(e - s for s, e, *_ in tl), 2),
         "start_lag_s": None, "end_offset_s": None, "laal_s": None}
    if not tl:
        return m
    m["start_lag_s"] = round(tl[0][0] - speech_start, 3)
    m["end_offset_s"] = round(tl[-1][1] - speech_end, 3)
    if clauses:
        times = []
        for c in clauses:
            if "out_start" not in c:
                continue
            words = c["en"].split()
            for j in range(len(words)):
                pos = c["out_start"] + (c["out_end"] - c["out_start"]) * (j + 0.5) / len(words)
                times.append(byte_time(tl, int(pos)))
        if times:
            X, Y = speech_end, len(times)
            tau = next((i + 1 for i, d in enumerate(times) if d >= X), Y)
            lag = [times[i] - i * X / Y for i in range(tau)]
            m["laal_s"] = round(float(np.mean(lag)), 3)
            m["english_words"] = Y
    return m


def render_playback(arrivals):
    """The audio exactly as the listener hears it, gaps as silence."""
    tl = playback(arrivals)
    if not tl:
        return np.zeros(1, dtype=np.int16)
    out = np.zeros(int(tl[-1][1] * SR) + 1, dtype=np.int16)
    for (start, _, _, _), (_, b) in zip(tl, arrivals):
        x = np.frombuffer(b, dtype="<i2")
        i = int(start * SR)
        out[i:i + len(x)] = x[: len(out) - i]
    return out
