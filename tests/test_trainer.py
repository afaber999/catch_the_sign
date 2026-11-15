import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import call, patch

import numpy as np

from callsign_trainer import app
from callsign_trainer.phonetics import phonetic_call_sign


class TrainerTests(unittest.TestCase):
    def test_phonetics_and_listening_tested_pronunciations(self):
        self.assertEqual(phonetic_call_sign("3B6XYZ"), "Three Bravo Six X-ray Yankee Zulu")
        self.assertEqual(
            phonetic_call_sign("AJMQRT0123456789X", "nl"),
            "alfa djoelie-et maik kwiebek roomie-o tenggo Zero wan toe trie for "
            "faiv sikss sevven eit nain eks reej",
        )
        self.assertEqual(phonetic_call_sign("HM", "fr"), "[[h]]o-tel [[maik]]")
        self.assertEqual(
            phonetic_call_sign("EMVXZ123456789", "de"),
            "ekko maik Victor ex rej sulu [[w]]an tu trie for [[faiv]] "
            "[[s]]iks Seven [[e\u026at]] nain",
        )

    def test_generator_uses_original_prefix_and_one_to_three_letters(self):
        with (
            patch.object(app.random, "randint", return_value=2),
            patch.object(app.random, "choice", side_effect=["3B6", "A", "Z"]),
        ):
            self.assertEqual(app.random_call_sign(), "3B6AZ")

    def test_short_level_filters_prefixes_and_suffix_length(self):
        with (
            patch.object(app.random, "randint", return_value=1) as length,
            patch.object(app.random, "choice", side_effect=lambda values: values[0]) as choice,
        ):
            result = app.random_call_sign(max_prefix_length=2, suffix_lengths=(1, 1))
        length.assert_called_once_with(1, 1)
        self.assertTrue(all(len(prefix) <= 2 for prefix in choice.call_args_list[0].args[0]))
        self.assertLessEqual(len(result), 3)

    def test_retries_reveal_and_correct_answer_keep_the_same_voice(self):
        with (
            patch.object(app, "random_call_sign", return_value="3B6AZ"),
            patch.object(app.random, "uniform", return_value=1.1),
            patch.object(app, "play_call_sign") as play,
            patch.object(app, "play_success") as success,
            patch("builtins.input", side_effect=["wrong", "?", "3b6az"]),
            patch("builtins.print") as output,
        ):
            app.practice_round("voice")
        self.assertEqual(play.call_args_list, [
            call("voice", "3B6AZ", 1.1),
            call("voice", "3B6AZ", 0.8),
            call("voice", "3B6AZ", 0.8),
        ])
        output.assert_called_once_with("Call sign: 3B6AZ")
        success.assert_called_once_with()

    def test_render_uses_index_and_fixed_pause(self):
        voice = SimpleNamespace(
            sample_rate=1000,
            samples=np.array([0.1] * 100 + [0.2] * 200, dtype=np.float32),
            segments={"A": (0, 100), "B": (100, 300)},
        )
        audio = app.render_call_sign(voice, "BA", 0.8)
        np.testing.assert_allclose(audio, [0.2] * 200 + [0.0] * 100 + [0.1] * 100)

    def test_time_stretch_preserves_pitch_and_fixed_pause(self):
        sample_rate = 8000
        samples = np.sin(2 * np.pi * 440 * np.arange(4000) / sample_rate).astype(np.float32)
        voice = SimpleNamespace(sample_rate=sample_rate, samples=samples, segments={"A": (0, 4000)})
        audio = app.render_call_sign(voice, "AA", 1.2)
        clip_length = round(4000 / 1.5)
        self.assertEqual(len(audio), 2 * clip_length + 800)
        np.testing.assert_array_equal(audio[clip_length:clip_length + 800], 0)
        frequency = np.fft.rfftfreq(clip_length, 1 / sample_rate)[
            np.argmax(abs(np.fft.rfft(audio[:clip_length])))
        ]
        self.assertAlmostEqual(frequency, 440, delta=10)

    def test_noise_covers_full_speech_with_lead_in(self):
        voice = SimpleNamespace(sample_rate=1000)
        with (
            patch.object(app, "render_call_sign", return_value=np.zeros(500, dtype=np.float32)),
            patch.object(app.random, "uniform", return_value=0.03),
            patch.object(app.np.random, "normal", side_effect=lambda mean, level, size: np.full(size, level)) as noise,
            patch.object(app.sd, "play") as play,
            patch.object(app.sd, "wait"),
        ):
            app.play_call_sign(voice, "1A", 1.0)
        noise.assert_called_once_with(0, 0.03, 600)
        np.testing.assert_allclose(play.call_args.args[0], 0.03)

    def test_zero_noise_adds_only_silent_lead_in(self):
        voice = SimpleNamespace(sample_rate=1000)
        with (
            patch.object(app, "render_call_sign", return_value=np.full(3, 0.5, dtype=np.float32)),
            patch.object(app.np.random, "normal") as noise,
        ):
            audio = app.noisy_call_sign(voice, "A", 0.65, 0)
        noise.assert_not_called()
        np.testing.assert_array_equal(audio[:100], 0)
        np.testing.assert_array_equal(audio[100:], [0.5, 0.5, 0.5])

    def test_default_and_accent_load_recordings(self):
        with (
            patch.object(app, "load_recording", return_value="voice") as load,
            patch.object(app, "ROUNDS", 1),
            patch.object(app, "practice_round") as practice,
            patch("builtins.print"),
        ):
            self.assertEqual(app.main([]), 0)
            load.assert_called_with(Path("alphabet_wavs"), "en_US-lessac-medium")
            self.assertEqual(app.main(["--accent", "french"]), 0)
            load.assert_called_with(Path("alphabet_wavs"), "fr_FR-siwis-medium")
            self.assertEqual(practice.call_count, 2)

    def test_random_selects_once_per_round_from_restricted_pool(self):
        with (
            patch.object(app, "load_recording", side_effect=lambda path, name: name),
            patch.object(app, "ROUNDS", 3),
            patch.object(app.random, "choice", side_effect=["a", "a", "b"]) as choice,
            patch.object(app, "practice_round") as practice,
            patch("builtins.print"),
        ):
            self.assertEqual(app.main(["--random", "--voice", "a", "--voice", "b"]), 0)
        self.assertEqual(choice.call_count, 3)
        self.assertEqual(practice.call_args_list, [call("a"), call("a"), call("b")])

    def test_model_alias_does_not_require_model_file(self):
        with (
            patch.object(app, "load_recording", return_value="voice") as load,
            patch.object(app, "ROUNDS", 0),
            patch("sys.stderr", new_callable=io.StringIO) as stderr,
        ):
            self.assertEqual(app.main(["--model", "not-present.onnx"]), 0)
        load.assert_called_once_with(Path("alphabet_wavs"), "not-present")
        self.assertIn("deprecated", stderr.getvalue())

    def test_explicit_missing_recording_reports_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("sys.stderr", new_callable=io.StringIO) as stderr:
                self.assertEqual(app.main(["--recordings-dir", directory, "--voice", "missing"]), 1)
            self.assertIn("--list-voices", stderr.getvalue())

    def test_ctrl_c_stops_session(self):
        with (
            patch.object(app, "load_recording", return_value="voice"),
            patch.object(app, "practice_round", side_effect=KeyboardInterrupt),
            patch("builtins.print") as output,
        ):
            self.assertEqual(app.main([]), 0)
        output.assert_any_call("\nPractice stopped.")

    def test_model_and_accent_are_mutually_exclusive(self):
        with patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit):
            app.main(["--model", "voice.onnx", "--accent", "german"])


if __name__ == "__main__":
    unittest.main()
