import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import call, patch

import numpy as np

from callsign_trainer import app


class TrainerTests(unittest.TestCase):
    def test_phonetics_include_letters_and_digits(self):
        self.assertEqual(
            app.phonetic_call_sign("3B6XYZ"), "Three Bravo Six X-ray Yankee Zulu"
        )

    def test_generator_uses_original_prefix_and_one_to_three_letters(self):
        with (
            patch.object(app.random, "randint", return_value=2),
            patch.object(app.random, "choice", side_effect=["3B6", "A", "Z"]),
        ):
            self.assertEqual(app.random_call_sign(), "3B6AZ")

    def test_retries_reveal_and_correct_answer(self):
        with (
            patch.object(app, "random_call_sign", return_value="3B6AZ"),
            patch.object(app.random, "uniform", return_value=1.1) as speed,
            patch.object(app, "play_call_sign") as play,
            patch.object(app, "play_success") as success,
            patch("builtins.input", side_effect=["wrong", "?", "3b6az"]),
            patch("builtins.print") as output,
        ):
            app.practice_round("voice")
        self.assertEqual(
            play.call_args_list,
            [
                call("voice", "3B6AZ", 1.1),
                call("voice", "3B6AZ", 0.8),
                call("voice", "3B6AZ", 0.8),
            ],
        )
        speed.assert_called_once_with(0.8, 1.2)
        output.assert_called_once_with("Call sign: 3B6AZ")
        success.assert_called_once_with()

    def test_noise_covers_full_speech_with_lead_in(self):
        speech = np.zeros(500, dtype=np.float32)
        voice = SimpleNamespace(config=SimpleNamespace(espeak_voice="en-us"))
        with (
            patch.object(app, "synthesize", return_value=(speech, 1000)),
            patch.object(app.random, "uniform", return_value=0.03),
            patch.object(
                app.np.random,
                "normal",
                side_effect=lambda mean, level, size: np.full(size, level),
            ) as noise,
            patch.object(app.sd, "play") as play,
            patch.object(app.sd, "wait"),
        ):
            app.play_call_sign(voice, "1A", 1.0)
        noise.assert_called_once_with(0, 0.03, 600)
        self.assertEqual(len(play.call_args.args[0]), 600)
        np.testing.assert_allclose(play.call_args.args[0], 0.03)

    def test_dutch_xray_uses_listening_tested_pronunciation(self):
        for language, expected in [("nl", "eks reej"), ("en-us", "X-ray")]:
            with self.subTest(language=language):
                voice = SimpleNamespace(config=SimpleNamespace(espeak_voice=language))
                with (
                    patch.object(
                        app, "synthesize", return_value=(np.zeros(1), 1000)
                    ) as synthesize,
                    patch.object(app.sd, "play"),
                    patch.object(app.sd, "wait"),
                ):
                    app.play_call_sign(voice, "X", 1.0)
                synthesize.assert_called_once_with(voice, expected, 1.0)

    def test_dutch_uses_listening_tested_words_and_numbers(self):
        voice = SimpleNamespace(config=SimpleNamespace(espeak_voice="nl"))
        with (
            patch.object(
                app, "synthesize", return_value=(np.zeros(1), 1000)
            ) as synthesize,
            patch.object(app.sd, "play"),
            patch.object(app.sd, "wait"),
        ):
            app.play_call_sign(voice, "AJMQRT123456789X", 1.0)
        synthesize.assert_called_once_with(
            voice,
            "alfa djoelie-et maik kwiebek roomie-o tenggo "
            "wan toe trie for faiv sikss sevven eit nain eks reej",
            1.0,
        )
        self.assertEqual(
            app.phonetic_call_sign("AJMQRT0123456789X", "en-us"),
            "Alpha Juliett Mike Quebec Romeo Tango Zero One Two Three Four "
            "Five Six Seven Eight Nine X-ray",
        )
        self.assertEqual(app.phonetic_call_sign("0", "nl"), "Zero")

    def test_synthesis_uses_model_rate_and_speed(self):
        class FakeVoice:
            config = SimpleNamespace(sample_rate=22050, length_scale=1.2)

            def synthesize_wav(self, text, wav, syn_config):
                self.text = text
                self.length_scale = syn_config.length_scale
                wav.writeframes(np.array([0, 16384, -16384], dtype="<i2").tobytes())

        voice = FakeVoice()
        samples, rate = app.synthesize(voice, "Alpha", 1.5)
        self.assertEqual((voice.text, rate), ("Alpha", 22050))
        self.assertAlmostEqual(voice.length_scale, 0.8)
        np.testing.assert_allclose(samples, [0, 0.5, -0.5])

    def test_empty_synthesis_is_an_error(self):
        class EmptyVoice:
            config = SimpleNamespace(sample_rate=22050, length_scale=1.0)

            def synthesize_wav(self, text, wav, syn_config):
                pass

        with self.assertRaisesRegex(ValueError, "no speech"):
            app.synthesize(EmptyVoice(), "Alpha", 1.0)

    def test_session_runs_twenty_rounds(self):
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / "voice.onnx"
            model.touch()
            config = Path(f"{model}.json")
            config.touch()
            with (
                patch.object(app.PiperVoice, "load", return_value="voice") as load,
                patch.object(app, "practice_round") as practice,
                patch("builtins.print"),
            ):
                self.assertEqual(app.main(["--model", str(model)]), 0)
            load.assert_called_once_with(model, config_path=config)
            self.assertEqual(practice.call_count, 20)

    def test_ctrl_c_stops_session(self):
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / "voice.onnx"
            model.touch()
            Path(f"{model}.json").touch()
            with (
                patch.object(app.PiperVoice, "load", return_value="voice"),
                patch.object(app, "practice_round", side_effect=KeyboardInterrupt),
                patch("builtins.print") as output,
            ):
                self.assertEqual(app.main(["--model", str(model)]), 0)
            output.assert_any_call("\nPractice stopped.")

    def test_missing_model_reports_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("sys.stderr", new_callable=io.StringIO) as stderr:
                with self.assertRaises(SystemExit) as result:
                    app.main(["--model", str(Path(directory) / "missing.onnx")])
        self.assertEqual(result.exception.code, 2)
        self.assertIn("file not found", stderr.getvalue())

    def test_accent_loads_the_matching_local_voice(self):
        with tempfile.TemporaryDirectory() as directory:
            model_dir = Path(directory)
            for accent, name in app.ACCENT_VOICES.items():
                with self.subTest(accent=accent):
                    model = model_dir / f"{name}.onnx"
                    model.touch()
                    Path(f"{model}.json").touch()
                    with (
                        patch.object(app, "MODEL_DIR", model_dir),
                        patch.object(app, "ROUNDS", 1),
                        patch.object(app.PiperVoice, "load", return_value="voice") as load,
                        patch.object(app, "practice_round") as practice,
                        patch("builtins.print"),
                    ):
                        self.assertEqual(app.main(["--accent", accent]), 0)
                    load.assert_called_once_with(model, config_path=Path(f"{model}.json"))
                    practice.assert_called_once_with("voice")

    def test_missing_accent_voice_explains_how_to_download_it(self):
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(app, "MODEL_DIR", Path(directory)),
                patch("sys.stderr", new_callable=io.StringIO) as stderr,
                self.assertRaises(SystemExit) as result,
            ):
                app.main(["--accent", "french"])
        self.assertEqual(result.exception.code, 2)
        self.assertIn("piper.download_voices fr_FR-siwis-medium", stderr.getvalue())

    def test_default_voice_is_english(self):
        with tempfile.TemporaryDirectory() as directory:
            model_dir = Path(directory)
            model = model_dir / "en_US-lessac-medium.onnx"
            model.touch()
            Path(f"{model}.json").touch()
            with (
                patch.object(app, "MODEL_DIR", model_dir),
                patch.object(app, "ROUNDS", 0),
                patch.object(app.PiperVoice, "load") as load,
            ):
                self.assertEqual(app.main([]), 0)
            load.assert_called_once_with(model, config_path=Path(f"{model}.json"))

    def test_model_and_accent_are_mutually_exclusive(self):
        with (
            patch("sys.stderr", new_callable=io.StringIO),
            self.assertRaises(SystemExit) as result,
        ):
            app.main(["--model", "voice.onnx", "--accent", "german"])
        self.assertEqual(result.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
