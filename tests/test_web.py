import http.client
import io
import json
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from callsign_trainer import app, web
from test_recordings import create_recording


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        create_recording(cls.temp.name, "human")
        index = create_recording(cls.temp.name, "native")
        index["accent"] = "en_GB"
        (Path(cls.temp.name) / "native.json").write_text(json.dumps(index), encoding="utf-8")
        cls.server = web.create_server(Path(cls.temp.name), 0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.temp.cleanup()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        if body is not None and not isinstance(body, bytes):
            body = json.dumps(body).encode()
            headers = {"Content-Type": "application/json", **(headers or {})}
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        data = response.read()
        result = response.status, dict(response.getheaders()), data
        connection.close()
        return result

    def test_serves_interface_and_valid_voice_list(self):
        status, headers, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"<title>Catch the Sign</title>", body)
        self.assertIn(b'aria-label="Catch the Sign home"', body)
        self.assertIn(b"Listening desk", body)
        self.assertIn(b'id="letter-hints-enabled"', body)
        self.assertIn(b'id="guess-hints"', body)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        status, _, body = self.request("GET", "/api/voices")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload["voices"][0]["name"], "human")
        self.assertEqual(payload["rounds"], 20)
        self.assertEqual([level["level"] for level in payload["levels"]], [1, 2, 3, 4, 5])
        self.assertEqual([voice["native_english"] for voice in payload["voices"]], [False, True])
        self.assertEqual(self.request("GET", "/not-a-file")[0], 404)

    def test_round_and_audio_use_indexed_recording(self):
        with patch.object(app, "random_call_sign", return_value="A1"):
            status, _, body = self.request("POST", "/api/round", {"voices": ["human"]})
        self.assertEqual(status, 200)
        round_data = json.loads(body)
        self.assertEqual((round_data["call_sign"], round_data["voice"]), ("A1", "human"))
        self.assertTrue(0.8 <= round_data["speed"] <= 1.2)
        round_data["speed"] = 0.8
        status, headers, audio = self.request("POST", "/api/audio", round_data)
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "audio/wav")
        with wave.open(io.BytesIO(audio), "rb") as wav:
            self.assertEqual((wav.getnchannels(), wav.getsampwidth(), wav.getframerate()), (1, 2, 1000))
            self.assertEqual(wav.getnframes(), 400)

    def test_invalid_requests_and_foreign_origins_are_rejected(self):
        self.assertEqual(self.request("POST", "/api/round", {"voices": []})[0], 400)
        self.assertEqual(self.request("POST", "/api/round", {"voices": ["..\\human"]})[0], 400)
        self.assertEqual(self.request("POST", "/api/audio", {"voice": "human", "call_sign": "A!", "speed": 0.8})[0], 400)
        self.assertEqual(self.request("POST", "/api/audio", {"voice": "human", "call_sign": "A", "speed": 10 ** 400})[0], 400)
        self.assertEqual(self.request("POST", "/api/round", {"voices": ["human"]}, {"Origin": "https://example.com"})[0], 403)
        self.assertEqual(self.request("GET", "/", headers={"Host": "example.com"})[0], 400)
        self.assertEqual(self.request("POST", "/api/round", b"x", {"Content-Type": "text/plain"})[0], 415)

    def test_level_one_uses_native_short_slow_calls_without_noise(self):
        status, _, body = self.request("POST", "/api/round", {"voices": ["human", "native"], "level": 1})
        self.assertEqual(status, 200)
        round_data = json.loads(body)
        self.assertEqual(round_data["voice"], "native")
        self.assertLessEqual(len(round_data["call_sign"]), 3)
        self.assertEqual(round_data["speed"], 0.65)
        self.assertEqual(round_data["noise"], 0)
        self.assertLess(round_data["retry_speed"], round_data["speed"])
        with (
            patch.object(app, "render_call_sign", return_value=np.ones(10, dtype=np.float32)),
            patch.object(app.np.random, "normal") as noise,
        ):
            status, _, audio = self.request("POST", "/api/audio", round_data)
        self.assertEqual(status, 200)
        noise.assert_not_called()
        with wave.open(io.BytesIO(audio), "rb") as wav:
            samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
        np.testing.assert_array_equal(samples[:100], 0)
        self.assertTrue(np.all(samples[100:] > 0))
        round_data["speed"] = round_data["retry_speed"]
        with patch.object(app, "render_call_sign", return_value=np.ones(10, dtype=np.float32)):
            self.assertEqual(self.request("POST", "/api/audio", round_data)[0], 200)

    def test_profiles_enforce_voice_speed_and_noise(self):
        for level, profile in web.LEVELS.items():
            with self.subTest(level=level):
                voices = ["native"] if profile["native_only"] else ["human"]
                status, _, body = self.request("POST", "/api/round", {"voices": voices, "level": level})
                self.assertEqual(status, 200)
                round_data = json.loads(body)
                self.assertTrue(profile["speed"][0] <= round_data["speed"] <= profile["speed"][1])
                self.assertTrue(profile["noise"][0] <= round_data["noise"] <= profile["noise"][1])
                self.assertLess(round_data["retry_speed"], round_data["speed"])
        self.assertEqual(self.request("POST", "/api/round", {"voices": ["human"], "level": 1})[0], 400)
        self.assertEqual(self.request("POST", "/api/round", {"voices": ["native"], "level": True})[0], 400)
        for data in (
            {"voice": "human", "call_sign": "A1", "level": 1, "speed": 0.65, "noise": 0},
            {"voice": "native", "call_sign": "A1", "level": 1, "speed": 1.2, "noise": 0},
            {"voice": "native", "call_sign": "A1", "level": 1, "speed": 0.65, "noise": 0.01},
        ):
            self.assertEqual(self.request("POST", "/api/audio", data)[0], 400)

    def test_native_voice_classification_uses_accent_not_filename(self):
        def voice(language, accent):
            return SimpleNamespace(metadata={"spoken_language": language, "accent": accent})

        self.assertTrue(web.native_english(voice("English", "en_US")))
        self.assertTrue(web.native_english(voice("en-GB", "British English")))
        self.assertFalse(web.native_english(voice("English", "Dutch")))
        self.assertFalse(web.native_english(voice("English", "en_NL")))
        self.assertFalse(web.native_english(voice("English", "en-DE")))
        self.assertFalse(web.native_english(voice("English", None)))
        self.assertFalse(web.native_english(voice("German", "en_US")))


if __name__ == "__main__":
    unittest.main()
