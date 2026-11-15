import io
import string
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from callsign_trainer.app import ACCENT_VOICES, phonetic_call_sign
from scripts import generate_alphabets


class GenerateAlphabetsTests(unittest.TestCase):
    def create_models(self, directory):
        for name in ACCENT_VOICES.values():
            model = directory / f"{name}.onnx"
            model.touch()
            Path(f"{model}.json").touch()

    def test_generates_alphabet_then_digits_for_all_accents(self):
        with tempfile.TemporaryDirectory() as directory:
            models = Path(directory) / "models"
            output = Path(directory) / "recordings"
            models.mkdir()
            self.create_models(models)
            spoken = []

            def load_voice(model, config_path):
                language = "nl" if model.name.startswith("nl_") else "en-us"
                return SimpleNamespace(config=SimpleNamespace(espeak_voice=language))

            def synthesize(voice, text, speed):
                spoken.append((voice.config.espeak_voice, text, speed))
                return np.array([0.0, 0.5, -0.5], dtype=np.float32), 22050

            with (
                patch.object(generate_alphabets.PiperVoice, "load", side_effect=load_voice),
                patch.object(generate_alphabets, "synthesize", side_effect=synthesize),
                patch("builtins.print"),
            ):
                self.assertEqual(
                    generate_alphabets.main(
                        ["--models-dir", str(models), "--output-dir", str(output)]
                    ),
                    0,
                )

            self.assertEqual(
                {path.name for path in output.iterdir()},
                {f"{accent}.wav" for accent in ACCENT_VOICES},
            )
            for language, text, speed in spoken:
                self.assertEqual(
                    text,
                    ", ".join(
                        phonetic_call_sign(character, language)
                        for character in string.ascii_uppercase + string.digits
                    ),
                )
                expected_digits = (
                    "Zero, wan, toe, trie, for, faiv, sikss, sevven, eit, nain"
                    if language == "nl"
                    else "Zero, One, Two, Three, Four, Five, Six, Seven, Eight, Nine"
                )
                self.assertTrue(text.endswith(expected_digits))
                self.assertEqual(speed, 0.8)
            self.assertEqual(len(spoken), len(ACCENT_VOICES))
            with wave.open(str(output / "dutch.wav"), "rb") as wav:
                self.assertEqual((wav.getnchannels(), wav.getsampwidth(), wav.getframerate()), (1, 2, 22050))
                self.assertEqual(wav.getnframes(), 3)

    def test_missing_voice_does_not_create_partial_output(self):
        with tempfile.TemporaryDirectory() as directory:
            models = Path(directory) / "models"
            output = Path(directory) / "recordings"
            models.mkdir()
            with (
                patch("sys.stderr", new_callable=io.StringIO) as stderr,
                self.assertRaises(SystemExit) as result,
            ):
                generate_alphabets.main(
                    ["--models-dir", str(models), "--output-dir", str(output)]
                )
            self.assertEqual(result.exception.code, 2)
            self.assertIn("missing german voice file", stderr.getvalue())
            self.assertFalse(output.exists())

    def test_existing_recording_is_not_overwritten_without_permission(self):
        with tempfile.TemporaryDirectory() as directory:
            models = Path(directory) / "models"
            output = Path(directory) / "recordings"
            models.mkdir()
            output.mkdir()
            self.create_models(models)
            existing = output / "dutch.wav"
            existing.write_bytes(b"existing")
            with (
                patch("sys.stderr", new_callable=io.StringIO) as stderr,
                patch.object(generate_alphabets.PiperVoice, "load") as load,
                self.assertRaises(SystemExit),
            ):
                generate_alphabets.main(
                    ["--models-dir", str(models), "--output-dir", str(output)]
                )
            self.assertIn("--overwrite", stderr.getvalue())
            self.assertEqual(existing.read_bytes(), b"existing")
            load.assert_not_called()

    def test_overwrite_replaces_an_existing_recording(self):
        with tempfile.TemporaryDirectory() as directory:
            models = Path(directory) / "models"
            output = Path(directory) / "recordings"
            models.mkdir()
            output.mkdir()
            model = models / "test.onnx"
            model.touch()
            Path(f"{model}.json").touch()
            recording = output / "dutch.wav"
            recording.write_bytes(b"existing")
            voice = SimpleNamespace(config=SimpleNamespace(espeak_voice="nl"))
            with (
                patch.object(generate_alphabets, "ACCENT_VOICES", {"dutch": "test"}),
                patch.object(generate_alphabets.PiperVoice, "load", return_value=voice),
                patch.object(
                    generate_alphabets,
                    "synthesize",
                    return_value=(np.array([0.0], dtype=np.float32), 22050),
                ),
                patch("builtins.print"),
            ):
                self.assertEqual(
                    generate_alphabets.main(
                        ["--models-dir", str(models), "--output-dir", str(output), "--overwrite"]
                    ),
                    0,
                )
            with wave.open(str(recording), "rb") as wav:
                self.assertEqual(wav.getnframes(), 1)


if __name__ == "__main__":
    unittest.main()
