import io
import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np

from callsign_trainer import app
from callsign_trainer.recordings import CHARACTERS, load_recording, sha256_file


def create_recording(directory, name="voice", checksum=False):
    directory = Path(directory)
    wav_path = directory / f"{name}.wav"
    with wave.open(str(wav_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(1000)
        wav.writeframes(np.arange(3600, dtype="<i2").tobytes())
    index = {
        "format_version": 1,
        "display_name": "A human voice",
        "spoken_language": "English",
        "accent": "Dutch",
        "origin": "human",
        "license": None,
        "provenance": None,
        "segments": {
            character: {"start": position / 10, "end": (position + 1) / 10}
            for position, character in enumerate(CHARACTERS)
        },
    }
    if checksum:
        index["wav_sha256"] = sha256_file(wav_path)
    (directory / f"{name}.json").write_text(json.dumps(index), encoding="utf-8")
    return index


class RecordingTests(unittest.TestCase):
    def test_human_recording_without_checksum_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            create_recording(directory)
            voice = load_recording(directory, "voice")
            self.assertEqual(voice.sample_rate, 1000)
            self.assertEqual(voice.segments["A"], (0, 100))
            self.assertEqual(voice.segments["9"], (3500, 3600))
            self.assertEqual(voice.metadata["accent"], "Dutch")

    def test_generated_checksum_detects_changed_wav(self):
        with tempfile.TemporaryDirectory() as directory:
            create_recording(directory, checksum=True)
            load_recording(directory, "voice")
            with (Path(directory) / "voice.wav").open("ab") as stream:
                stream.write(b"changed")
            with self.assertRaisesRegex(ValueError, "checksum"):
                load_recording(directory, "voice")

    def test_invalid_segments_are_rejected(self):
        cases = {
            "missing": lambda index: index["segments"].pop("A"),
            "extra": lambda index: index["segments"].update({"!": {"start": 0, "end": 0.1}}),
            "overlap": lambda index: index["segments"]["B"].update(start=0.09),
            "subsample overlap": lambda index: index["segments"]["B"].update(start=0.0999),
            "empty": lambda index: index["segments"]["A"].update(end=0),
            "out of range": lambda index: index["segments"]["9"].update(end=3.7),
            "negative": lambda index: index["segments"]["A"].update(start=-0.1),
            "nonfinite": lambda index: index["segments"]["A"].update(start=float("nan")),
            "boolean": lambda index: index["segments"]["A"].update(start=False),
            "huge": lambda index: index["segments"]["A"].update(end=10 ** 400),
        }
        for label, change in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                index = create_recording(directory)
                change(index)
                (Path(directory) / "voice.json").write_text(json.dumps(index), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_recording(directory, "voice")

    def test_invalid_and_unpaired_voices_are_skipped_with_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            create_recording(directory, "good")
            (Path(directory) / "broken.wav").write_bytes(b"not audio")
            (Path(directory) / "unpaired.json").write_text(
                (Path(directory) / "good.json").read_text(encoding="utf-8"), encoding="utf-8"
            )
            with patch("sys.stderr", new_callable=io.StringIO) as stderr:
                voices = app.discover_recordings(Path(directory))
            self.assertEqual([voice.name for voice in voices], ["good"])
            self.assertIn("skipping broken", stderr.getvalue())
            self.assertIn("skipping unpaired", stderr.getvalue())

    def test_wav_format_and_truncation_are_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            create_recording(directory)
            path = Path(directory) / "voice.wav"
            with wave.open(str(path), "wb") as wav:
                wav.setnchannels(2)
                wav.setsampwidth(2)
                wav.setframerate(1000)
                wav.writeframes(b"\0" * 1000)
            with self.assertRaisesRegex(ValueError, "mono 16-bit"):
                load_recording(directory, "voice")
            create_recording(directory)
            data = path.read_bytes()
            path.write_bytes(data[:-2])
            with self.assertRaisesRegex(ValueError, "truncated"):
                load_recording(directory, "voice")

    def test_voice_names_cannot_escape_directory(self):
        with self.assertRaises(ValueError):
            load_recording(".", "..\\voice")


if __name__ == "__main__":
    unittest.main()
