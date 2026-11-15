"""Catch the Sign: local web interface for call sign practice."""

import argparse
import io
import json
import math
import random
import re
import sys
import wave
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlsplit

import numpy as np

from callsign_trainer import app
from callsign_trainer.recordings import load_recording

ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}

LEVELS = {
    1: {
        "name": "First contact",
        "description": "Shortest calls · slow · native English · no added noise",
        "native_only": True, "prefix_length": 2, "suffix_lengths": (1, 1),
        "speed": (0.65, 0.65), "noise": (0.0, 0.0),
    },
    2: {
        "name": "Finding your rhythm",
        "description": "Short calls · relaxed pace · native English · no added noise",
        "native_only": True, "prefix_length": 2, "suffix_lengths": (1, 2),
        "speed": (0.72, 0.8), "noise": (0.0, 0.0),
    },
    3: {
        "name": "On the air",
        "description": "Longer calls · native English · light noise",
        "native_only": True, "prefix_length": 3, "suffix_lengths": (1, 3),
        "speed": (0.8, 0.95), "noise": (0.01, 0.02),
    },
    4: {
        "name": "Changing conditions",
        "description": "All call lengths · any accent · moderate noise",
        "native_only": False, "prefix_length": None, "suffix_lengths": (1, 3),
        "speed": (0.9, 1.05), "noise": (0.025, 0.04),
    },
    5: {
        "name": "Pile-up",
        "description": "Longer calls · faster voices · any accent · stronger noise",
        "native_only": False, "prefix_length": None, "suffix_lengths": (2, 3),
        "speed": (1.05, 1.2), "noise": (0.04, 0.07),
    },
}


def native_english(voice):
    language = voice.metadata["spoken_language"].strip().lower().replace("_", "-")
    accent = (voice.metadata["accent"] or "").strip().lower().replace("_", "-")
    english = language in ("english", "en") or language.startswith("en-")
    native_accents = {
        "english", "native english", "american", "american english",
        "british", "british english", "australian", "australian english",
        "canadian", "canadian english", "irish", "irish english",
        "new zealand", "new zealand english",
    }
    english_regions = {"us", "gb", "uk", "au", "ca", "ie", "nz", "za"}
    parts = accent.split("-")
    native_code = accent == "en" or (
        len(parts) >= 2 and parts[0] == "en" and parts[1] in english_regions
    )
    return english and (native_code or accent in native_accents)


def get_level(value):
    if type(value) is not int or value not in LEVELS:
        raise ValueError("Choose a difficulty level from 1 to 5")
    return LEVELS[value]


class Handler(BaseHTTPRequestHandler):
    def send_data(self, status, content_type, data):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, status, value):
        self.send_data(status, "application/json; charset=utf-8", json.dumps(value).encode("utf-8"))

    def valid_host(self):
        port = self.server.server_address[1]
        return self.headers.get("Host", "").lower() in (f"127.0.0.1:{port}", f"localhost:{port}")

    def do_GET(self):
        if not self.valid_host():
            self.send_json(400, {"error": "Invalid host"})
            return
        path = urlsplit(self.path).path
        if path in ASSETS:
            name, content_type = ASSETS[path]
            asset = files("callsign_trainer").joinpath("web", name).read_bytes()
            self.send_data(200, content_type, asset)
        elif path == "/api/voices":
            voices = app.discover_recordings(self.server.recordings_dir)
            self.send_json(200, {
                "voices": [
                    {
                        "name": voice.name,
                        "display_name": voice.metadata["display_name"],
                        "accent": voice.metadata["accent"],
                        "native_english": native_english(voice),
                    }
                    for voice in voices
                ],
                "default": app.DEFAULT_VOICE,
                "rounds": app.ROUNDS,
                "levels": [
                    {"level": number, "name": profile["name"],
                     "description": profile["description"], "native_only": profile["native_only"]}
                    for number, profile in LEVELS.items()
                ],
            })
        else:
            self.send_json(404, {"error": "Not found"})

    def do_POST(self):
        origin = self.headers.get("Origin")
        if not self.valid_host() or (origin and origin != f"http://{self.headers.get('Host')}"):
            self.send_json(403, {"error": "Only same-origin local requests are allowed"})
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            self.send_json(415, {"error": "Expected JSON"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 8192:
                raise ValueError("Invalid request size")
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Expected a JSON object")
            path = urlsplit(self.path).path
            if path == "/api/round":
                names = data.get("voices")
                if not isinstance(names, list) or not names or len(names) > 256 or any(
                    not isinstance(name, str) or not name for name in names
                ):
                    raise ValueError("Choose at least one valid voice")
                level_number = data.get("level")
                if level_number is None:
                    voice = load_recording(self.server.recordings_dir, random.choice(names))
                    result = {"call_sign": app.random_call_sign(), "voice": voice.name,
                              "speed": random.uniform(0.8, 1.2)}
                else:
                    profile = get_level(level_number)
                    voices = [load_recording(self.server.recordings_dir, name) for name in dict.fromkeys(names)]
                    if profile["native_only"]:
                        voices = [voice for voice in voices if native_english(voice)]
                    if not voices:
                        raise ValueError("This level requires a native English voice")
                    voice = random.choice(voices)
                    speed = random.uniform(*profile["speed"])
                    result = {
                        "call_sign": app.random_call_sign(profile["prefix_length"], profile["suffix_lengths"]),
                        "voice": voice.name, "speed": speed,
                        "retry_speed": min(0.8, speed * 0.85),
                        "noise": random.uniform(*profile["noise"]), "level": level_number,
                    }
                self.send_json(200, result)
            elif path == "/api/audio":
                name = data.get("voice")
                call_sign = data.get("call_sign")
                speed = data.get("speed")
                if not isinstance(name, str):
                    raise ValueError("Invalid voice")
                if not isinstance(call_sign, str) or not re.fullmatch(r"[A-Z0-9]{1,16}", call_sign):
                    raise ValueError("Invalid call sign")
                if (
                    isinstance(speed, bool)
                    or not isinstance(speed, (int, float))
                    or (isinstance(speed, float) and not math.isfinite(speed))
                    or not 0.5 <= speed <= 1.2
                ):
                    raise ValueError("Invalid playback speed")
                voice = load_recording(self.server.recordings_dir, name)
                level_number = data.get("level")
                if level_number is None:
                    audio = app.noisy_call_sign(voice, call_sign, speed)
                else:
                    profile = get_level(level_number)
                    noise = data.get("noise")
                    if (
                        isinstance(noise, bool)
                        or not isinstance(noise, (int, float))
                        or (isinstance(noise, float) and not math.isfinite(noise))
                        or not profile["noise"][0] <= noise <= profile["noise"][1]
                    ):
                        raise ValueError("Invalid noise for difficulty level")
                    if not min(0.8, profile["speed"][0] * 0.85) <= speed <= profile["speed"][1]:
                        raise ValueError("Invalid speed for difficulty level")
                    if profile["native_only"] and not native_english(voice):
                        raise ValueError("This level requires a native English voice")
                    audio = app.noisy_call_sign(voice, call_sign, speed, noise)
                pcm = (audio * 32767).astype("<i2")
                buffer = io.BytesIO()
                with wave.open(buffer, "wb") as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(voice.sample_rate)
                    wav.writeframes(pcm.tobytes())
                self.send_data(200, "audio/wav", buffer.getvalue())
            else:
                self.send_json(404, {"error": "Not found"})
        except (BrokenPipeError, ConnectionResetError):
            return
        except (ValueError, UnicodeError, json.JSONDecodeError, OSError) as error:
            self.send_json(400, {"error": str(error)})


def create_server(recordings_dir, port):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.recordings_dir = Path(recordings_dir)
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recordings-dir", type=Path, default=Path("alphabet_wavs"))
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    try:
        server = create_server(args.recordings_dir, args.port)
    except OSError as error:
        print(f"error: cannot start web server: {error}", file=sys.stderr)
        return 1
    address = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Open {address}  (Ctrl+C to stop)", flush=True)
    if not args.no_browser:
        webbrowser.open(address)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nWeb trainer stopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
