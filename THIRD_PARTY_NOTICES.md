# Third-party notices

cadbot is licensed under GPL-3.0-or-later. It includes or uses the components below; each keeps
its own licence. Model and voice files are downloaded at install time by
`python -m cadbot.models ensure` and are never stored in this repository.

## Included in this repository

| Component | Licence | Where | Notes |
| --- | --- | --- | --- |
| RoboEyes, MicroPython port (mchobby/micropython-roboeyes, commit `f3e609f`), based on FluxGarage RoboEyes | GPL-3.0 | `cadbot/vendor/roboeyes/` | Copyright (C) 2024 Dennis Hoelscher (FluxGarage), (C) 2025 Meurisse Dominique (MC Hobby). Full licence in `LICENSE.txt`; changes listed in `README.vendored.md` and marked in the code |

## Installed Python packages (main ones)

| Component | Licence | How cadbot uses it |
| --- | --- | --- |
| Anthropic Python SDK (`anthropic`) | MIT | Claude API client |
| Piper TTS (`piper-tts`) | GPL-3.0 | Text-to-speech, imported as a library |
| faster-whisper | MIT | Speech-to-text; also ships the Silero VAD ONNX model cadbot uses |
| CTranslate2 | MIT | Whisper inference engine (via faster-whisper) |
| Silero VAD model | MIT | Voice activity detection (file bundled with faster-whisper) |
| ONNX Runtime | MIT | Runs Silero VAD and Piper voices |
| OpenCV (`opencv-python`) | Apache-2.0 | Camera access and, later, face detection and matching |
| NumPy | BSD-3-Clause | Audio and image arrays |
| sounddevice / PortAudio | MIT | Microphone and speaker |
| pygame-ce | LGPL-2.1 | Face window, drawing |
| Pydantic, PyYAML, python-dotenv, platformdirs | MIT | Configuration |
| httpx, truststore | BSD-3-Clause, MIT | Downloads and health checks using the OS certificate store |
| psutil, pyserial, keyring | BSD-3-Clause, BSD-3-Clause, MIT | Hardware helpers and secrets |
| gpiozero (Linux only) | BSD-3-Clause | GPIO on the Raspberry Pi |
| APScheduler, SQLAlchemy | MIT | Reminders and storage (later milestones) |
| FastAPI, Uvicorn | MIT, BSD-3-Clause | Local web UI (later milestones) |
| Google API client libraries | Apache-2.0 | Gmail and Calendar (later milestones) |
| Playwright, pyotp | Apache-2.0, MIT | Web logins (later milestones) |
| timezonefinder | MIT | Time zone from location (later milestones) |

## Downloaded models and voices

| File | Licence | Source (pinned commit) |
| --- | --- | --- |
| Whisper `small.en`, CTranslate2 conversion | MIT | huggingface.co/Systran/faster-whisper-small.en @ `d1d751a` |
| Whisper `tiny.en`, CTranslate2 conversion (stop phrases) | MIT | huggingface.co/Systran/faster-whisper-tiny.en @ `0d3d19a` |
| Piper voice `en_US-lessac-medium` | Voice trained on the Blizzard 2013 Lessac dataset; see the voice's `MODEL_CARD` and the dataset licence, which may restrict commercial use | huggingface.co/rhasspy/piper-voices @ `04ca88f` |
| YuNet face detector `face_detection_yunet_2023mar.onnx` | MIT | huggingface.co/opencv/face_detection_yunet @ `3cc26e7` |
| SFace face recognition `face_recognition_sface_2021dec.onnx` | Apache-2.0 | huggingface.co/opencv/face_recognition_sface @ `3d70824` |

Exact URLs and SHA-256 hashes are in `cadbot/models/manifest.py`.

## Online services used

| Service | Used for | Terms |
| --- | --- | --- |
| beaconDB (api.beacondb.net) | Position from nearby Wi-Fi networks, or an IP estimate | Public-domain database; experimental. IP data by DB-IP |
| OpenStreetMap Nominatim | Address from coordinates | Nominatim usage policy (max 1 request/s, identifying User-Agent); data © OpenStreetMap contributors, ODbL |

This is a practical summary, not legal advice. When adding a dependency, add it here.
