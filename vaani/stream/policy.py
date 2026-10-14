"""When to speak: the read/write policy of a simultaneous interpreter.

Three layers, each answering one question:

1. PauseDetector  - where can we safely cut the audio?  (energy-based, 20 ms frames)
2. LocalAgreement - which recognised words are stable? A word is committed only
                    when two consecutive ASR passes over the growing buffer agree on
                    it (LocalAgreement-2, Machacek et al. 2023). Never un-commit.
3. ClauseGate     - which committed Hindi words are ready to translate? Hindi is
                    verb-final: "मैंने कल अपना पुराना बैंक खाता ... बंद करवा दिया" only
                    becomes translatable at the verb. So we hold words until a clause
                    closes (clause-final verb/auxiliary, a pause, or punctuation) and
                    never cut inside a number ("दो लाख | पचास हज़ार" would be spoken
                    as two amounts).

A fixed wait-k policy (start after k source words) fails for SOV -> SVO because the
English verb depends on the *last* Hindi word, not the k-th.
"""
import re

import numpy as np

# Clause-final verbs/auxiliaries: when one of these is the last word, the clause's
# meaning (opened/closed, did/didn't, asked/told) is usually settled.
CLAUSE_END = {
    "है", "हैं", "था", "थी", "थे", "हूँ", "हूं", "हो", "थीं",
    "दिया", "दी", "दिए", "दिये", "गया", "गई", "गए", "गये", "लिया", "ली", "लिए",
    "करो", "करें", "करिए", "कीजिए", "कीजिये", "दीजिए", "बताइए", "चाहिए", "सकता", "सकती",
    "सकते", "रहा", "रही", "रहे", "जाएगा", "जाएगी", "जाएँगे", "होगा", "होगी", "करूँगा", "करूँगी",
    "please", "प्लीज़", "ना",
}
CONNECTIVES = {"और", "लेकिन", "पर", "तो", "क्योंकि", "कि", "अगर", "जब", "फिर"}
NUMBER_WORDS = set("""शून्य एक दो तीन चार पाँच पांच छह सात आठ नौ दस ग्यारह बारह तेरह चौदह पंद्रह
सोलह सत्रह अठारह उन्नीस बीस पच्चीस तीस चालीस पचास साठ सत्तर अस्सी नब्बे सौ हज़ार हजार लाख करोड़
डेढ़ ढाई साढ़े सवा पौने दशमलव""".split())


def _strip(w: str) -> str:
    return re.sub(r"[।?!,.\"']", "", w)


class PauseDetector:
    """Finds the latest pause (>= min_pause s of low energy) in a buffer."""

    def __init__(self, sr: int, min_pause=0.35, thresh_db=-38.0):
        self.sr, self.min_pause, self.thresh_db = sr, min_pause, thresh_db

    def last_pause(self, x: np.ndarray):
        """Returns the sample index in the middle of the last pause, or None."""
        win = int(0.02 * self.sr)
        n = len(x) // win
        if n == 0:
            return None
        rms = np.sqrt((x[: n * win].reshape(n, win).astype(np.float64) ** 2).mean(1) + 1e-12)
        quiet = 20 * np.log10(rms) < self.thresh_db
        need = int(self.min_pause / 0.02)
        run, best = 0, None
        for i, q in enumerate(quiet):
            run = run + 1 if q else 0
            if run >= need:
                best = (i - run // 2) * win
        # a pause that is still running at the very end is fine to cut at, but only
        # if there was speech before it
        if best is not None and not quiet[: max(1, best // win)].all():
            return best
        return None


class LocalAgreement:
    """Commits the longest common prefix of the last two hypotheses."""

    def __init__(self):
        self.prev: list[str] = []
        self.committed = 0          # words of the current segment already committed

    def update(self, hyp: list[str]) -> list[str]:
        n = 0
        for a, b in zip(self.prev, hyp):
            if _strip(a) != _strip(b):
                break
            n += 1
        self.prev = hyp
        new = hyp[self.committed:n] if n > self.committed else []
        self.committed = max(self.committed, n)
        return new

    def finalize(self, hyp: list[str]) -> list[str]:
        """Segment closed at a pause: everything left is committed."""
        new = hyp[self.committed:]
        self.prev, self.committed = [], 0
        return new


class ClauseGate:
    """Holds committed Hindi words until a translatable clause is complete."""

    def __init__(self, min_words=3, max_words=18):
        self.pending: list[str] = []
        self.min_words, self.max_words = min_words, max_words

    def push(self, words: list[str]) -> list[str]:
        """Add committed words; return zero or more clauses ready to translate."""
        out = []
        for w in words:
            self.pending.append(w)
            if self._closes(w) or len(self.pending) >= self.max_words and not self._in_number():
                out.append(" ".join(self.pending))
                self.pending = []
        return out

    def _in_number(self) -> bool:
        return bool(self.pending) and _strip(self.pending[-1]) in NUMBER_WORDS

    def _closes(self, w: str) -> bool:
        if len(self.pending) < self.min_words:
            return False
        if w[-1:] in "।?!":
            return True
        return _strip(w) in CLAUSE_END

    def flush(self) -> list[str]:
        """Pause or end of input: whatever is pending must be said now."""
        if not self.pending:
            return []
        out, self.pending = [" ".join(self.pending)], []
        return out
