"""Terminal-based call sign listening practice."""

import argparse
import io
import random
import string
import sys
import wave
from importlib.resources import files
from pathlib import Path

import numpy as np
import sounddevice as sd
from piper import PiperVoice, SynthesisConfig

PHONETIC_WORDS = dict(
    zip(
        string.ascii_uppercase + string.digits,
        (
            "Alpha Bravo Charlie Delta Echo Foxtrot Golf Hotel India Juliett "
            "Kilo Lima Mike November Oscar Papa Quebec Romeo Sierra Tango "
            "Uniform Victor Whiskey X-ray Yankee Zulu "
            "Zero One Two Three Four Five Six Seven Eight Nine"
        ).split(),
    )
)
PREFIXES = files("callsign_trainer").joinpath("prefixes.txt").read_text(
    encoding="utf-8"
).splitlines()
ROUNDS = 20
MODEL_DIR = Path("models")
ACCENT_VOICES = {
    "german": "de_DE-thorsten-medium",
    "french": "fr_FR-siwis-medium",
    "dutch": "nl_NL-pim-medium",
    "italian": "it_IT-paola-medium",
    "russian": "ru_RU-irina-medium",
}


def random_call_sign():
    length = random.randint(1, 3)
    return random.choice(PREFIXES) + "".join(
        random.choice(string.ascii_uppercase) for _ in range(length)
    )


def phonetic_call_sign(call_sign):
    return " ".join(PHONETIC_WORDS[character] for character in call_sign)


def synthesize(voice, text, speed):
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(voice.config.sample_rate)
        voice.synthesize_wav(
            text,
            wav,
            syn_config=SynthesisConfig(length_scale=voice.config.length_scale / speed),
        )
    output.seek(0)
    with wave.open(output, "rb") as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            raise ValueError("Piper produced an unsupported audio format")
        sample_rate = wav.getframerate()
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
    if samples.size == 0:
        raise ValueError("Piper produced no speech")
    return samples.astype(np.float32) / 32768, sample_rate


def play_call_sign(voice, call_sign, speed):
    speech, sample_rate = synthesize(voice, phonetic_call_sign(call_sign), speed)
    lead_in = np.zeros(int(sample_rate * 0.1), dtype=np.float32)
    speech = np.concatenate((lead_in, speech))
    noise = np.random.normal(0, random.uniform(0.01, 0.05), speech.size)
    audio = np.clip(speech + noise, -1.0, 1.0).astype(np.float32)
    sd.play(audio, sample_rate)
    sd.wait()


def play_success():
    sample_rate = 22050
    time = np.arange(int(sample_rate * 0.15)) / sample_rate
    envelope = np.minimum(1, np.minimum(time * 100, (0.15 - time) * 100))
    sd.play((0.2 * envelope * np.sin(2 * np.pi * 880 * time)).astype(np.float32), sample_rate)
    sd.wait()


def practice_round(voice):
    call_sign = random_call_sign()
    speed = random.uniform(0.8, 1.2)
    while True:
        play_call_sign(voice, call_sign, speed)
        answer = input("Call sign: ")
        if answer.upper() == call_sign:
            play_success()
            return
        if "?" in answer:
            print(f"Call sign: {call_sign}")
        speed = 0.8


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    voice = parser.add_mutually_exclusive_group()
    voice.add_argument(
        "--model", type=Path, help="Path to a local Piper .onnx voice"
    )
    voice.add_argument(
        "--accent",
        choices=ACCENT_VOICES,
        help="Use a local voice for the selected accent",
    )
    parser.add_argument(
        "--config", type=Path, help="Voice config (default: MODEL.onnx.json)"
    )
    args = parser.parse_args(argv)
    voice_name = ACCENT_VOICES.get(args.accent, "en_US-lessac-medium")
    model = args.model or MODEL_DIR / f"{voice_name}.onnx"
    config = args.config or Path(f"{model}.json")
    for path in (model, config):
        if not path.is_file():
            if args.model is None and path == model:
                parser.error(
                    f"file not found: {path}; download it with "
                    f'"{sys.executable}" -m piper.download_voices '
                    f"{voice_name} --download-dir {MODEL_DIR}"
                )
            parser.error(f"file not found: {path}")
    try:
        voice = PiperVoice.load(model, config_path=config)
        for index in range(ROUNDS):
            print(f"Round {index + 1} of {ROUNDS}")
            practice_round(voice)
    except KeyboardInterrupt:
        print("\nPractice stopped.")
        return 0
    except (OSError, ValueError, RuntimeError, wave.Error, sd.PortAudioError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
