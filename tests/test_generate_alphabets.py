import io
import json
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from callsign_trainer.recordings import CHARACTERS, load_recording, sha256_file
from scripts import generate_alphabets as generator


class GenerateAlphabetsTests(unittest.TestCase):
    def create_model(self, directory, name="nl_NL-test"):
        model = Path(directory) / f"{name}.onnx"
        model.write_bytes(b"model")
        Path(f"{model}.json").write_bytes(b"config")
        return model

    def make_voice(self, language="nl"):
        return SimpleNamespace(config=SimpleNamespace(
            espeak_voice=language, sample_rate=1000, num_speakers=2
        ))

    def test_synthesizes_each_character_and_creates_valid_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            model = self.create_model(directory)
            output = Path(directory) / "output"
            spoken = []

            def synthesize(voice, text, speaker_id):
                spoken.append((text, speaker_id))
                return np.array([1000, -1000], dtype="<i2"), 1000

            with (
                patch("piper.PiperVoice.load", return_value=self.make_voice()),
                patch.object(generator, "synthesize", side_effect=synthesize),
            ):
                name = generator.generate_recording(model, output)
            voice = load_recording(output, name)
            self.assertEqual(len(spoken), 36)
            self.assertEqual(spoken[0], ("alfa", None))
            self.assertEqual(spoken[23], ("eks reej", None))
            self.assertEqual(spoken[26], ("Zero", None))
            self.assertEqual(voice.segments["9"], (70, 72))
            self.assertEqual(voice.metadata["spoken_language"], "English")
            self.assertEqual(voice.metadata["accent"], "nl_NL")
            self.assertEqual(voice.metadata["source_model_sha256"], sha256_file(model))
            self.assertEqual(voice.metadata["wav_sha256"], sha256_file(output / f"{name}.wav"))
            self.assertIsNone(voice.metadata["license"])

    def test_italian_synthesis_is_slower(self):
        class FakeVoice:
            def __init__(self, language):
                self.config = SimpleNamespace(
                    sample_rate=22050, length_scale=1.0, espeak_voice=language
                )

            def synthesize_wav(self, text, wav, syn_config):
                self.length_scale = syn_config.length_scale
                wav.writeframes(np.array([1], dtype="<i2").tobytes())

        italian = FakeVoice("it")
        french = FakeVoice("fr")
        generator.synthesize(italian, "Alpha")
        generator.synthesize(french, "Alpha")
        self.assertAlmostEqual(french.length_scale, 1.0 / 0.8)
        self.assertAlmostEqual(italian.length_scale, 1.0 / (0.8 * 0.65))

    def test_empty_synthesis_is_an_error(self):
        class EmptyVoice:
            config = SimpleNamespace(sample_rate=22050, length_scale=1.0, espeak_voice="en")

            def synthesize_wav(self, text, wav, syn_config):
                pass

        with self.assertRaisesRegex(ValueError, "no speech"):
            generator.synthesize(EmptyVoice(), "Alpha")

    def test_overwrite_preserves_metadata_but_clears_rights_when_model_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            model = self.create_model(directory)
            output = Path(directory) / "output"
            with (
                patch("piper.PiperVoice.load", return_value=self.make_voice()),
                patch.object(generator, "synthesize", return_value=(np.array([1], dtype="<i2"), 1000)),
            ):
                name = generator.generate_recording(model, output)
                index_path = output / f"{name}.json"
                index = json.loads(index_path.read_text(encoding="utf-8"))
                index.update(display_name="My voice", license="Known", provenance="My source", custom="kept")
                index_path.write_text(json.dumps(index), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "--overwrite"):
                    generator.generate_recording(model, output)
                generator.generate_recording(model, output, overwrite=True)
                index = json.loads(index_path.read_text(encoding="utf-8"))
                self.assertEqual((index["display_name"], index["license"], index["custom"]), ("My voice", "Known", "kept"))
                model.write_bytes(b"changed")
                generator.generate_recording(model, output, overwrite=True)
                index = json.loads(index_path.read_text(encoding="utf-8"))
                self.assertEqual(index["display_name"], "My voice")
                self.assertIsNone(index["license"])
                self.assertIsNone(index["provenance"])

    def test_never_overwrites_human_or_incomplete_pairs(self):
        with tempfile.TemporaryDirectory() as directory:
            model = self.create_model(directory)
            output = Path(directory) / "output"
            with (
                patch("piper.PiperVoice.load", return_value=self.make_voice()),
                patch.object(generator, "synthesize", return_value=(np.array([1], dtype="<i2"), 1000)),
            ):
                name = generator.generate_recording(model, output)
                index_path = output / f"{name}.json"
                index = json.loads(index_path.read_text(encoding="utf-8"))
                index["origin"] = "human"
                index_path.write_text(json.dumps(index), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "human"):
                    generator.generate_recording(model, output, overwrite=True)
                index_path.unlink()
                with self.assertRaisesRegex(ValueError, "incomplete"):
                    generator.generate_recording(model, output, overwrite=True)

    def test_failure_does_not_publish_partial_pair_and_other_models_continue(self):
        with tempfile.TemporaryDirectory() as directory:
            models = Path(directory) / "models"
            models.mkdir()
            bad = self.create_model(models, "a_bad")
            self.create_model(models, "b_good")
            output = Path(directory) / "output"

            def load(model, config_path):
                return self.make_voice("bad" if model == bad else "nl")

            def synthesize(voice, text, speaker_id):
                if voice.config.espeak_voice == "bad":
                    raise ValueError("synthesis failed")
                return np.array([1], dtype="<i2"), 1000

            with (
                patch("piper.PiperVoice.load", side_effect=load),
                patch.object(generator, "synthesize", side_effect=synthesize),
                patch("sys.stderr", new_callable=io.StringIO) as stderr,
                patch("sys.stdout", new_callable=io.StringIO),
            ):
                self.assertEqual(generator.main(["--models-dir", str(models), "--output-dir", str(output)]), 1)
            self.assertIn("synthesis failed", stderr.getvalue())
            self.assertFalse((output / "a_bad.wav").exists())
            self.assertFalse((output / "a_bad.json").exists())
            self.assertEqual(set(load_recording(output, "b_good").segments), set(CHARACTERS))

    def test_explicit_speaker_has_distinct_name_and_rejects_bad_id(self):
        with tempfile.TemporaryDirectory() as directory:
            model = self.create_model(directory)
            output = Path(directory) / "output"
            with (
                patch("piper.PiperVoice.load", return_value=self.make_voice()),
                patch.object(generator, "synthesize", return_value=(np.array([1], dtype="<i2"), 1000)) as synthesize,
            ):
                name = generator.generate_recording(model, output, speaker_id=1)
                self.assertEqual(name, "nl_NL-test-speaker-1")
                self.assertTrue(all(call.args[2] == 1 for call in synthesize.call_args_list))
                with self.assertRaisesRegex(ValueError, "outside"):
                    generator.generate_recording(model, output, speaker_id=2)
            self.assertFalse((output / "nl_NL-test-speaker-2.wav").exists())

    def test_failed_publication_restores_previous_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            model = self.create_model(directory)
            output = Path(directory) / "output"
            with (
                patch("piper.PiperVoice.load", return_value=self.make_voice()),
                patch.object(generator, "synthesize", return_value=(np.array([1], dtype="<i2"), 1000)),
            ):
                name = generator.generate_recording(model, output)
                old_wav = (output / f"{name}.wav").read_bytes()
                old_index = (output / f"{name}.json").read_bytes()
                original_replace = generator.os.replace
                calls = 0

                def replace(source, target):
                    nonlocal calls
                    calls += 1
                    if calls == 2:
                        raise OSError("publication failed")
                    return original_replace(source, target)

                with patch.object(generator.os, "replace", side_effect=replace):
                    with self.assertRaisesRegex(OSError, "publication failed"):
                        generator.generate_recording(model, output, overwrite=True)
                self.assertEqual((output / f"{name}.wav").read_bytes(), old_wav)
                self.assertEqual((output / f"{name}.json").read_bytes(), old_index)


if __name__ == "__main__":
    unittest.main()
