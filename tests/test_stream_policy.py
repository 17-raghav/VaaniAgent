import numpy as np

from vaani.stream.policy import ClauseGate, LocalAgreement, PauseDetector
from vaani.stream.metrics import playback, compute_metrics


def test_local_agreement_commits_only_stable_prefix():
    la = LocalAgreement()
    assert la.update("मैंने कल".split()) == []                     # nothing to agree with yet
    assert la.update("मैंने कल अपना".split()) == ["मैंने", "कल"]
    assert la.update("मैंने कल अपना पुराना".split()) == ["अपना"]
    assert la.update("मैंने कल अपनी पुराना बैंक".split()) == []      # disagreement: wait
    assert la.finalize("मैंने कल अपना पुराना बैंक खाता".split()) == ["पुराना", "बैंक", "खाता"]


def test_clause_gate_waits_for_verb_and_never_splits_numbers():
    g = ClauseGate(min_words=3, max_words=18)
    assert g.push("मैंने कल अपना पुराना बैंक".split()) == []         # verb not heard yet
    assert g.push("खाता बंद करवा दिया".split()) == ["मैंने कल अपना पुराना बैंक खाता बंद करवा दिया"]
    # a tight cap forces a cut, but never in the middle of an amount
    g = ClauseGate(min_words=3, max_words=6)
    out = g.push("मुझे दो लाख पचास हज़ार".split())                   # 5 words, ends on a number
    assert out == []
    out = g.push(["रुपये"])                                          # max_words reached, not in number
    assert out == ["मुझे दो लाख पचास हज़ार रुपये"]


def test_pause_detector_finds_gap():
    sr = 24000
    rng = np.random.default_rng(0)
    x = np.concatenate([0.3 * rng.standard_normal(sr), np.zeros(int(0.6 * sr)), 0.3 * rng.standard_normal(sr)])
    cut = PauseDetector(sr).last_pause(x.astype(np.float32))
    assert sr < cut < 1.6 * sr
    assert PauseDetector(sr).last_pause(np.zeros(sr, dtype=np.float32)) is None


def test_playback_timeline_queues_frames():
    a = [(1.0, bytes(48000)), (1.2, bytes(48000)), (5.0, bytes(24000))]   # 1 s, 1 s, 0.5 s
    tl = playback(a)
    assert [round(s, 2) for s, *_ in tl] == [1.0, 2.0, 5.0]
    pcm = np.full(24000 * 3, 3000, dtype=np.int16)                         # 3 s of "speech"
    m = compute_metrics(a, pcm, {}, None)
    assert m["start_lag_s"] == 1.0 and m["end_offset_s"] == 2.5
