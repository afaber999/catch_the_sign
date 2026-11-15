# SSB call sign trainer

Practice recognizing amateur radio call signs spoken in English spelling words
over randomized background noise. Practice plays indexed recordings offline;
it does not require Piper or voice models.

## Setup (Windows)

Install Python 3.12 and create a local virtual environment:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

Place an indexed voice recording in `alphabet_wavs\`, or generate recordings
locally as described below. Recordings and models are not included in Git.

## Practice in your browser

```powershell
.\.venv\Scripts\ssb-callsign-trainer-web.exe
```

The trainer opens `http://127.0.0.1:8765/` in your browser. Choose a difficulty
level and select a voice, or turn on **Mix voices** and choose a pool, then
start a session. Listen, enter
the call sign, and select **Check**. A wrong answer plays it more slowly;
**Reveal answer** (or entering `?`) shows the answer. The progress panel tracks
completed rounds and first-try copies. Level and voice changes apply to the next round.
Audio plays through the browser's output device.

| Level | Calls | Voice and conditions |
| --- | --- | --- |
| 1 — First contact | Shortest: prefixes of up to 2 characters, plus 1 letter | Native English, slow, no added noise |
| 2 — Finding your rhythm | Short prefixes, plus 1–2 letters | Native English, relaxed pace, no added noise |
| 3 — On the air | Prefixes of up to 3 characters, plus 1–3 letters | Native English, light noise |
| 4 — Changing conditions | Any prefix, plus 1–3 letters | Any selected accent, faster, moderate noise |
| 5 — Pile-up | Any prefix, plus 2–3 letters | Any selected accent, fastest, stronger noise |

Level 1 is selected initially. Levels 4–5 make accented voices available; select
them or include them in your mix to hear them. Retries keep the same voice and
noise level and play more slowly. Levels 1–3 require a voice whose metadata
identifies an English native accent (for example `en`, `en_US`, `British English`,
or `American English`). Unknown or non-English accents are excluded from those
levels rather than assumed to be native. Classification relies on the recording's
metadata; it cannot verify a speaker's background.

The server is available only on your computer and works offline. Keep its
console open while practicing; press Ctrl+C there to stop it. Use `--port 8766`
to change the port, `--recordings-dir PATH` to select another recording
directory, or `--no-browser` to open the displayed address yourself. Preparing
the first audio may take longer while the time-stretch library initializes.

## Practice in the terminal

```powershell
.\.venv\Scripts\ssb-callsign-trainer.exe --list-voices
.\.venv\Scripts\ssb-callsign-trainer.exe
.\.venv\Scripts\ssb-callsign-trainer.exe --voice en_GB-alan-medium
.\.venv\Scripts\ssb-callsign-trainer.exe --accent dutch
.\.venv\Scripts\ssb-callsign-trainer.exe --random
.\.venv\Scripts\ssb-callsign-trainer.exe --random --voice nl_NL-pim-medium --voice fr_FR-siwis-medium
```

The default is `en_US-lessac-medium`, if its recording is available. `--voice`
selects a recording by basename; repeat it with `--random` to restrict the
random pool. Otherwise, `--random` chooses among all valid recordings once per
round, and the same voice is used for retries. Consecutive rounds can use the
same voice. Invalid or unpaired recordings are warned about and skipped during
discovery; explicitly selected invalid recordings fail. Use `--recordings-dir
PATH` for a different directory.

The accent aliases `german`, `french`, `dutch`, `italian`, and `russian` select
`de_DE-thorsten-medium`, `fr_FR-siwis-medium`, `nl_NL-pim-medium`,
`it_IT-paola-medium`, and `ru_RU-irina-medium`, respectively. Voices trained in
other languages approximate English and may mispronounce words.

Each session has 20 rounds. Enter the call sign after listening; a wrong answer
replays it more slowly. Enter `?` to reveal the answer, then enter it to continue.
Press Ctrl+C to stop early. Generated call signs are practice examples and are
not guaranteed to be assigned or valid. Playback joins the indexed words with
100 ms pauses and uses pitch-preserving speed changes, which may introduce
artifacts. Background noise continues throughout each playback.

For compatibility, `--model PATH` selects the recording named after the `.onnx`
model, without opening it; this option is deprecated. `--config` is ignored.

## Generate recordings with Piper

Generation is separate from practice. Install the optional dependencies and
download the voices you want:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[generation]"
.\.venv\Scripts\python.exe -m piper.download_voices en_US-lessac-medium --download-dir models
.\.venv\Scripts\python.exe -m piper.download_voices nl_NL-pim-medium --download-dir models
.\.venv\Scripts\python.exe .\scripts\generate_alphabets.py
```

The generator processes all `.onnx` models in `models\` with their
`MODEL.onnx.json` companions, producing `NAME.wav` and `NAME.json` in
`alphabet_wavs\`. Each A–Z spelling word and each digit 0–9 is synthesized
separately. Existing Dutch, French, and German pronunciation tuning and slower
Italian generation are retained. The default speaker is used for multi-speaker
models; to choose one explicitly:

```powershell
.\.venv\Scripts\python.exe .\scripts\generate_alphabets.py --model .\models\my-voice.onnx --speaker 1
```

Explicit speakers get a `-speaker-N` suffix. `--models-dir PATH` and
`--output-dir PATH` change the input and output directories. Failures are
reported individually; other models still run, and the command returns a
nonzero status if any failed. Existing pairs are never replaced unless
`--overwrite` is given. Even then, incomplete, invalid, human, and
different-model pairs are protected. Valid edited metadata is retained; if the
model or configuration has changed, license and provenance revert to unknown.

For more voices, choose a model name from the
[Piper voice samples](https://rhasspy.github.io/piper-samples/) and download it,
for example:

```powershell
.\.venv\Scripts\python.exe -m piper.download_voices en_GB-alan-medium --download-dir models
```

Downloads require internet access; generation and practice work offline once
the models are local. Piper is GPL-3.0-or-later; models and their generated audio
may have separate restrictions. License and provenance default to unknown.
Verify all relevant rights and license compatibility before redistributing
models or recordings.

## Human recordings and index format

Human-recorded voices are supported without Piper. Create a pair with the same
basename, such as `my-voice.wav` and `my-voice.json`, in `alphabet_wavs\`.
The WAV must be mono 16-bit PCM; each voice may use a different sample rate.
The JSON must contain a `segments` entry for every uppercase character A–Z and
digit 0–9, with no extras. Each interval is in seconds from the start of the
WAV, includes the entire usable clip (including any silence), has an exclusive
end, and must be positive, non-overlapping, and within the file. Speak English
spelling words for letters and English digits.

This abbreviated example shows the format; a usable index must contain all 36
segments:

```json
{
  "format_version": 1,
  "display_name": "Example speaker",
  "spoken_language": "English",
  "accent": "Dutch",
  "origin": "human",
  "license": null,
  "provenance": null,
  "segments": {
    "A": {"start": 0.0, "end": 0.9},
    "B": {"start": 1.0, "end": 1.8}
  }
}
```

`accent`, `license`, and `provenance` may be strings or `null` when unknown.
`origin` is `human` or `synthetic`. Optionally add `wav_sha256` containing the
WAV file's SHA-256 hex digest; playback verifies it when present. Generated
indexes always include this checksum, model/config checksums, and speaker ID.
No recording or index editor is included.

## Tests

The complete suite includes generation tests, so install the generation extra
first, then run:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
