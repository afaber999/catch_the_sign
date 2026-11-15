"""Generate spoken NATO alphabet and number WAVs for each supported accent."""

import argparse
import string
import wave
from pathlib import Path

import numpy as np
from piper import PiperVoice

from callsign_trainer.app import ACCENT_VOICES, phonetic_call_sign, synthesize


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models-dir", type=Path, default=Path("models"))
    parser.add_argument("--output-dir", type=Path, default=Path("alphabet_wavs"))
    parser.add_argument(
        "--overwrite", action="store_true", help="Replace existing output files"
    )
    args = parser.parse_args(argv)

    for accent, name in ACCENT_VOICES.items():
        model = args.models_dir / f"{name}.onnx"
        config = Path(f"{model}.json")
        for path in (model, config):
            if not path.is_file():
                parser.error(f"missing {accent} voice file: {path}")
        output = args.output_dir / f"{accent}.wav"
        if output.exists() and not args.overwrite:
            parser.error(f"output already exists: {output}; use --overwrite to replace it")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for accent, name in ACCENT_VOICES.items():
        model = args.models_dir / f"{name}.onnx"
        voice = PiperVoice.load(model, config_path=Path(f"{model}.json"))
        text = ", ".join(
            phonetic_call_sign(character, voice.config.espeak_voice)
            for character in string.ascii_uppercase + string.digits
        )
        samples, sample_rate = synthesize(voice, text, 0.8)
        pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
        output = args.output_dir / f"{accent}.wav"
        with wave.open(str(output), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(pcm.tobytes())
        print(f"Saved {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
