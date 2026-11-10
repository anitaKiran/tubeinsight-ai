"""Regenerate deterministic noise/validation files using only the standard library."""
import array
from pathlib import Path
import random
import wave

root = Path(__file__).resolve().parent / "fixtures"
root.mkdir(exist_ok=True)
clear = root / "clear-question.wav"
if clear.exists():
    with wave.open(str(clear), "rb") as handle:
        params = handle.getparams()
        samples = array.array("h", handle.readframes(handle.getnframes()))
    if params.sampwidth != 2:
        raise ValueError("Use 16-bit PCM speech for this fixture generator.")
    rng = random.Random(42)
    for index, sample in enumerate(samples):
        samples[index] = max(-32768, min(32767, sample + rng.randint(-100, 100)))
    with wave.open(str(root / "noisy-question.wav"), "wb") as handle:
        handle.setparams(params)
        handle.writeframes(samples.tobytes())
with wave.open(str(root / "silent.wav"), "wb") as handle:
    handle.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
    handle.writeframes(bytes(3200))
(root / "empty.wav").write_bytes(b"")
(root / "unsupported.txt").write_text("This is not audio.")
(root / "invalid.webm").write_bytes(b"not a valid WebM recording")
