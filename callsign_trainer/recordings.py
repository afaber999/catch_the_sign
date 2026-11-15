"""Load and validate indexed recordings for practice."""

import hashlib
import json
import math
import string
import struct
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

CHARACTERS = string.ascii_uppercase + string.digits


def sha256_file(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_index(path):
    try:
        with path.open(encoding="utf-8") as stream:
            index = json.load(stream, object_pairs_hook=_unique_pairs)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read index {path}: {error}") from error
    if not isinstance(index, dict) or type(index.get("format_version")) is not int or index["format_version"] != 1:
        raise ValueError(f"{path}: unsupported or missing format_version")
    for key in ("display_name", "spoken_language", "origin"):
        if not isinstance(index.get(key), str) or not index[key].strip():
            raise ValueError(f"{path}: {key} must be a non-empty string")
    if index["origin"] not in ("human", "synthetic"):
        raise ValueError(f"{path}: origin must be human or synthetic")
    for key in ("accent", "license", "provenance"):
        if key not in index or (index[key] is not None and not isinstance(index[key], str)):
            raise ValueError(f"{path}: {key} must be a string or null")
    return index


@dataclass(frozen=True)
class Recording:
    name: str
    sample_rate: int
    samples: np.ndarray
    segments: dict
    metadata: dict


def load_recording(directory, name):
    if not name or name in (".", "..") or "/" in name or "\\" in name:
        raise ValueError(f"invalid voice name: {name!r}")
    directory = Path(directory)
    wav_path = directory / f"{name}.wav"
    index_path = directory / f"{name}.json"
    index = read_index(index_path)
    try:
        with wave.open(str(wav_path), "rb") as wav:
            if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getcomptype() != "NONE":
                raise ValueError(f"{wav_path}: expected mono 16-bit PCM WAV")
            sample_rate = wav.getframerate()
            frames = wav.getnframes()
            data = wav.readframes(frames)
    except (OSError, EOFError, struct.error, wave.Error) as error:
        raise ValueError(f"cannot read WAV {wav_path}: {error}") from error
    if sample_rate <= 0 or frames <= 0 or len(data) != frames * 2:
        raise ValueError(f"{wav_path}: invalid or truncated audio")
    checksum = index.get("wav_sha256")
    if checksum is not None:
        if not isinstance(checksum, str) or len(checksum) != 64 or sha256_file(wav_path) != checksum.lower():
            raise ValueError(f"{wav_path}: WAV checksum does not match the index")

    raw_segments = index.get("segments")
    if not isinstance(raw_segments, dict) or set(raw_segments) != set(CHARACTERS):
        raise ValueError(f"{index_path}: segments must contain exactly A-Z and 0-9")
    segments = {}
    intervals = []
    for character, bounds in raw_segments.items():
        if not isinstance(bounds, dict):
            raise ValueError(f"{index_path}: invalid segment for {character}")
        start, end = bounds.get("start"), bounds.get("end")
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or (isinstance(value, float) and not math.isfinite(value))
            for value in (start, end)
        ):
            raise ValueError(f"{index_path}: invalid timestamps for {character}")
        if start < 0 or end <= start or end > frames / sample_rate:
            raise ValueError(f"{index_path}: segment out of bounds for {character}")
        intervals.append((start, end, character))
        first, last = round(start * sample_rate), round(end * sample_rate)
        if first >= last or last > frames:
            raise ValueError(f"{index_path}: segment too short for {character}")
        segments[character] = (first, last)
    intervals.sort()
    for (_, end, previous), (start, _, current) in zip(intervals, intervals[1:]):
        if start < end:
            raise ValueError(f"{index_path}: overlapping segments {previous} and {current}")
    ordered = sorted(segments.items(), key=lambda item: item[1])
    for (previous, (_, last)), (current, (first, _)) in zip(ordered, ordered[1:]):
        if first < last:
            raise ValueError(f"{index_path}: overlapping segments {previous} and {current}")
    samples = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768
    return Recording(name, sample_rate, samples, segments, index)
