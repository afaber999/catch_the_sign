# SSB call sign trainer

Practice recognizing amateur radio call signs spoken in English NATO phonetics
over randomized background noise. Speech is generated locally by Piper.

## Setup (Windows)

Install Python 3.12, then create and use a local virtual environment:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

Provide a Piper `.onnx` voice model and its companion `.onnx.json` file. For
example, download a voice to the ignored `models` directory:

```powershell
.\.venv\Scripts\python.exe -m piper.download_voices en_US-lessac-medium --download-dir models
```

The download requires internet access; practice runs offline once the model is
available. Piper is GPL-3.0-or-later; voice models have separate licenses.
Check a voice's license before redistributing it.

To download another voice, choose one from the [Piper voice samples](https://rhasspy.github.io/piper-samples/)
and use its model name. For example:

```powershell
.\.venv\Scripts\python.exe -m piper.download_voices en_GB-alan-medium --download-dir models
```

## Practice

```powershell
.\.venv\Scripts\ssb-callsign-trainer.exe --model .\models\en_US-lessac-medium.onnx
```

To use the downloaded British voice instead:

```powershell
.\.venv\Scripts\ssb-callsign-trainer.exe --model .\models\en_GB-alan-medium.onnx
```

Use `--config PATH` if the voice configuration is not next to the model as
`MODEL.onnx.json`. Each session has 20 rounds. Enter the call sign after
listening; a wrong answer replays it more slowly. Enter `?` to reveal the answer,
then enter the answer to continue. Press Ctrl+C to stop early. Generated call
signs are practice examples and are not guaranteed to be assigned or valid.

## Accents

The trainer can speak the same English phonetic words using Piper voices
trained in other languages. Choose an accent and download its voice first:

| Accent | Voice name |
| --- | --- |
| `german` | `de_DE-thorsten-medium` |
| `french` | `fr_FR-siwis-medium` |
| `dutch` | `nl_NL-pim-medium` |
| `italian` | `it_IT-paola-medium` |
| `russian` | `ru_RU-irina-medium` |

For example:

```powershell
.\.venv\Scripts\python.exe -m piper.download_voices fr_FR-siwis-medium --download-dir models
.\.venv\Scripts\ssb-callsign-trainer.exe --accent french
```

Use the corresponding voice name and accent for the other choices. Without
`--accent` or `--model`, the trainer uses `models\en_US-lessac-medium.onnx`.
These voices use their own language's pronunciation rules, so the resulting
accents are approximations and some English words may be mispronounced.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
