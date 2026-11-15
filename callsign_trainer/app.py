"""Terminal-based call sign listening practice."""

import argparse
import random
import string
import sys
from importlib.resources import files
from pathlib import Path

import numpy as np
import sounddevice as sd

from callsign_trainer.recordings import load_recording

PREFIXES = files("callsign_trainer").joinpath("prefixes.txt").read_text(
    encoding="utf-8"
).splitlines()
ROUNDS = 20
ACCENT_VOICES = {
    "german": "de_DE-thorsten-medium",
    "french": "fr_FR-siwis-medium",
    "dutch": "nl_NL-pim-medium",
    "italian": "it_IT-paola-medium",
    "russian": "ru_RU-irina-medium",
}
DEFAULT_VOICE = "en_US-lessac-medium"


def random_call_sign(max_prefix_length=None, suffix_lengths=(1, 3)):
    prefixes = PREFIXES
    if max_prefix_length is not None:
        prefixes = [prefix for prefix in PREFIXES if len(prefix) <= max_prefix_length]
    length = random.randint(*suffix_lengths)
    return random.choice(prefixes) + "".join(
        random.choice(string.ascii_uppercase) for _ in range(length)
    )


def render_call_sign(voice, call_sign, speed):
    rate = speed / 0.8
    pause = np.zeros(round(voice.sample_rate * 0.1), dtype=np.float32)
    parts = []
    for character in call_sign:
        start, end = voice.segments[character]
        clip = voice.samples[start:end]
        if rate != 1.0:
            import librosa

            expected = max(1, round(len(clip) / rate))
            if len(clip) < 512:
                clip = np.pad(clip, (0, 512 - len(clip)))
            clip = librosa.effects.time_stretch(
                clip, rate=rate, n_fft=512, hop_length=128
            )[:expected]
        if parts:
            parts.append(pause)
        parts.append(clip)
    return np.concatenate(parts)


def noisy_call_sign(voice, call_sign, speed, noise_level=None):
    speech = render_call_sign(voice, call_sign, speed)
    lead_in = np.zeros(int(voice.sample_rate * 0.1), dtype=np.float32)
    speech = np.concatenate((lead_in, speech))
    if noise_level is None:
        noise_level = random.uniform(0.01, 0.05)
    if noise_level:
        speech = speech + np.random.normal(0, noise_level, speech.size)
    return np.clip(speech, -1.0, 1.0).astype(np.float32)


def play_call_sign(voice, call_sign, speed):
    sd.play(noisy_call_sign(voice, call_sign, speed), voice.sample_rate)
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


def discover_recordings(directory):
    recordings = []
    names = {path.stem for pattern in ("*.wav", "*.json") for path in directory.glob(pattern)}
    for name in sorted(names):
        try:
            recordings.append(load_recording(directory, name))
        except ValueError as error:
            print(f"warning: skipping {name}: {error}", file=sys.stderr)
    return recordings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--voice", action="append", help="Recording name; repeat to select a random pool"
    )
    selection.add_argument("--accent", choices=ACCENT_VOICES, help="Built-in voice alias")
    selection.add_argument("--model", type=Path, help="Deprecated recording-name alias")
    parser.add_argument("--config", type=Path, help="Deprecated; ignored")
    parser.add_argument(
        "--recordings-dir", type=Path, default=Path("alphabet_wavs"),
        help="Directory containing indexed WAV files",
    )
    parser.add_argument("--random", action="store_true", help="Choose a voice each round")
    parser.add_argument("--list-voices", action="store_true", help="List valid recordings")
    args = parser.parse_args(argv)
    if args.config is not None:
        print("warning: --config is ignored; playback does not use Piper", file=sys.stderr)
    if args.list_voices:
        for voice in discover_recordings(args.recordings_dir):
            print(f"{voice.name}: {voice.metadata['display_name']}")
        return 0
    if args.model is not None:
        if args.model.suffix.lower() != ".onnx":
            parser.error("--model must name an .onnx model")
        print("warning: --model is deprecated; use --voice", file=sys.stderr)
        names = [args.model.stem]
    elif args.accent:
        names = [ACCENT_VOICES[args.accent]]
    else:
        names = args.voice
    if names and len(names) > 1 and not args.random:
        parser.error("multiple --voice options require --random")
    try:
        if names:
            voices = [load_recording(args.recordings_dir, name) for name in dict.fromkeys(names)]
        elif args.random:
            voices = discover_recordings(args.recordings_dir)
        else:
            voices = [load_recording(args.recordings_dir, DEFAULT_VOICE)]
        if not voices:
            raise ValueError(f"no valid indexed voices in {args.recordings_dir}")
        for index in range(ROUNDS):
            print(f"Round {index + 1} of {ROUNDS}")
            voice = random.choice(voices) if args.random else voices[0]
            practice_round(voice)
    except KeyboardInterrupt:
        print("\nPractice stopped.")
        return 0
    except (OSError, ValueError, RuntimeError, sd.PortAudioError) as error:
        print(f"error: {error}\nUse --list-voices to see valid recordings.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
