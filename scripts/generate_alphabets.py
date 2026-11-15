"""Generate indexed alphabet recordings from local Piper models."""

import argparse
import io
import json
import os
import shutil
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

from callsign_trainer.phonetics import phonetic_call_sign
from callsign_trainer.recordings import CHARACTERS, load_recording, sha256_file


def synthesize(voice, text, speaker_id=None):
    from piper import SynthesisConfig

    speed = 0.8 * (0.65 if voice.config.espeak_voice == "it" else 1.0)
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(voice.config.sample_rate)
        voice.synthesize_wav(
            text,
            wav,
            syn_config=SynthesisConfig(
                length_scale=voice.config.length_scale / speed, speaker_id=speaker_id
            ),
        )
    output.seek(0)
    with wave.open(output, "rb") as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            raise ValueError("Piper produced an unsupported audio format")
        sample_rate = wav.getframerate()
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
    if samples.size == 0:
        raise ValueError("Piper produced no speech")
    return samples, sample_rate


def _existing_metadata(output_dir, name, model, config, speaker_id, overwrite):
    wav_path = output_dir / f"{name}.wav"
    index_path = output_dir / f"{name}.json"
    if not wav_path.exists() and not index_path.exists():
        return {}
    if not overwrite:
        raise ValueError(f"{name} already exists; use --overwrite")
    if not wav_path.is_file() or not index_path.is_file():
        raise ValueError(f"{name}: refusing to overwrite an incomplete recording pair")
    metadata = dict(load_recording(output_dir, name).metadata)
    if (
        metadata["origin"] != "synthetic"
        or metadata.get("source_model") != model.name
        or metadata.get("speaker_id") != speaker_id
    ):
        raise ValueError(f"{name}: refusing to overwrite a human or different-model recording")
    if (
        metadata.get("source_model_sha256") != sha256_file(model)
        or metadata.get("source_config_sha256") != sha256_file(config)
    ):
        metadata["license"] = None
        metadata["provenance"] = None
    return metadata


def _publish_pair(staging, output, name):
    targets = [output / f"{name}.wav", output / f"{name}.json"]
    sources = [staging / path.name for path in targets]
    backups = []
    for target in targets:
        backup = staging / f"backup-{target.name}"
        if target.exists():
            shutil.copy2(target, backup)
            backups.append(backup)
        else:
            backups.append(None)
    published = 0
    try:
        for source, target in zip(sources, targets):
            os.replace(source, target)
            published += 1
    except OSError:
        for target, backup in zip(targets[:published], backups[:published]):
            if backup is None:
                target.unlink(missing_ok=True)
            else:
                os.replace(backup, target)
        raise


def generate_recording(model, output_dir, overwrite=False, speaker_id=None):
    from piper import PiperVoice

    model = Path(model)
    config = Path(f"{model}.json")
    if not model.is_file() or not config.is_file():
        raise ValueError(f"missing model or companion config: {model}, {config}")
    name = model.stem + (f"-speaker-{speaker_id}" if speaker_id is not None else "")
    metadata = _existing_metadata(output_dir, name, model, config, speaker_id, overwrite)
    voice = PiperVoice.load(model, config_path=config)
    if speaker_id is not None and not 0 <= speaker_id < voice.config.num_speakers:
        raise ValueError(f"speaker {speaker_id} is outside 0..{voice.config.num_speakers - 1}")
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".recording-", dir=output_dir) as temp:
        staging = Path(temp)
        wav_path = staging / f"{name}.wav"
        segments = {}
        position = 0
        sample_rate = voice.config.sample_rate
        with wave.open(str(wav_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            for character in CHARACTERS:
                text = phonetic_call_sign(character, voice.config.espeak_voice)
                samples, rate = synthesize(voice, text, speaker_id)
                if rate != sample_rate or samples.size == 0:
                    raise ValueError(f"inconsistent or empty audio for {character}")
                start = position
                position += len(samples)
                segments[character] = {"start": start / rate, "end": position / rate}
                wav.writeframes(samples.astype("<i2", copy=False).tobytes())
        metadata.update(
            format_version=1,
            display_name=metadata.get("display_name", model.stem),
            spoken_language=metadata.get("spoken_language", "English"),
            accent=metadata.get("accent", model.stem.split("-", 1)[0]),
            origin="synthetic",
            license=metadata.get("license"),
            provenance=metadata.get("provenance"),
            source_model=model.name,
            source_model_sha256=sha256_file(model),
            source_config_sha256=sha256_file(config),
            speaker_id=speaker_id,
            wav_sha256=sha256_file(wav_path),
            segments=segments,
        )
        (staging / f"{name}.json").write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        load_recording(staging, name)
        _publish_pair(staging, output_dir, name)
    return name


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models-dir", type=Path, default=Path("models"))
    parser.add_argument("--model", type=Path, help="Generate one model instead of all models")
    parser.add_argument("--speaker", type=int, help="Speaker ID (requires --model)")
    parser.add_argument("--output-dir", type=Path, default=Path("alphabet_wavs"))
    parser.add_argument("--overwrite", action="store_true", help="Replace matching generated pairs")
    args = parser.parse_args(argv)
    if args.speaker is not None and args.model is None:
        parser.error("--speaker requires --model")
    try:
        import piper  # noqa: F401
    except ImportError:
        print("error: install generation dependencies with pip install -e \".[generation]\"", file=sys.stderr)
        return 1
    models = [args.model] if args.model else sorted(args.models_dir.glob("*.onnx"))
    if not models:
        print(f"error: no models found in {args.models_dir}", file=sys.stderr)
        return 1
    failures = 0
    for model in models:
        try:
            name = generate_recording(model, args.output_dir, args.overwrite, args.speaker)
            print(f"Saved {name}.wav and {name}.json in {args.output_dir}")
        except Exception as error:
            print(f"error: {model}: {error}", file=sys.stderr)
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
