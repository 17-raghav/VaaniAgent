"""Mic recording (push-to-talk) and WAV playback."""
import winsound

SAMPLE_RATE = 16000
MAX_SECONDS = 30   # Saaras accepts up to ~30 s per request
MIN_SECONDS = 0.5  # shorter than this is treated as an accidental Enter


def record(path="input.wav"):
    """Record from the mic until the user presses Enter.
    Returns the WAV path, or None if the recording was too short."""
    import numpy as np  # imported here so --mock/--text never touch the mic
    import sounddevice as sd
    import soundfile as sf

    chunks = []

    def on_audio(data, frames, time, status):
        chunks.append(data.copy())

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", callback=on_audio):
        input("  Recording... speak now, press Enter when you finish.")

    data = np.concatenate(chunks) if chunks else np.zeros((0, 1), dtype="int16")
    seconds = len(data) / SAMPLE_RATE
    if seconds < MIN_SECONDS:
        return None
    if seconds > MAX_SECONDS:
        print(f"  Note: only the first {MAX_SECONDS} s are used.")
        data = data[:MAX_SECONDS * SAMPLE_RATE]
    print(f"  Recorded {min(seconds, MAX_SECONDS):.1f} s")
    sf.write(path, data, SAMPLE_RATE, subtype="PCM_16")
    return path


def play(path):
    winsound.PlaySound(path, winsound.SND_FILENAME)
