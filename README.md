# cadbot

cadbot is a friendly home assistant bot for the desk. It listens, talks and shows an animated
face, and it introduces itself as cadbot. Every decision is made by Claude (`claude-opus-5-5`):
the device only senses (microphone, later the camera), transcribes speech locally, speaks, and
carries out the tool calls Claude asks for.

The full design is in [docs/cadbot-design.md](docs/cadbot-design.md). It targets a Raspberry
Pi 5 with a touchscreen, and runs on a Windows PC for development.

**Status: milestone M1, "cadbot talks".** Microphone → voice activity detection (Silero) →
speech-to-text (faster-whisper, on the device) → Claude → speech (Piper), with a face window
showing the expressions Claude chooses. Seeing people, remembering names, reminders and Google
accounts come in later milestones.

## Privacy notice

Please read this before running cadbot, and tell people near the device what it does.

- **What leaves the device:** the *text* of what the microphone hears is sent to the Claude API
  (Anthropic) so Claude can decide whether and how to answer. There is no wake word, so this
  includes speech that wasn't meant for cadbot. When Claude searches the web, the search runs on
  Anthropic's side. Anthropic's API data-retention terms apply to what is sent.
- **What stays on the device:** raw audio is processed in memory and never saved or uploaded.
  Speech-to-text (Whisper) and text-to-speech (Piper) run locally. In M1 nothing is stored about
  anyone; application logs are written to the data folder, and include what was heard only with
  `--verbose`.
- **Your API key** stays in your local `.env` file, which Git ignores.

Later milestones send camera frames to Claude and can remember people who agree to it; the
design document describes the consent and deletion rules, which are enforced in code.

## Setup on Windows

You need Windows 10 or 11 (64-bit), Git, a microphone and **headphones** (cadbot's own voice
would otherwise reach the mic; until there's an echo-cancelling speakerphone, cadbot mutes the
mic while it talks). Run natively, not in WSL.

```powershell
# 1. Install uv (Python manager), then open a new terminal
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 2. Get the code and install everything (uv fetches Python 3.14 if needed)
git clone https://github.com/<you>/cadbot.git
cd cadbot
uv sync --extra dev

# 3. Add your Anthropic API key (set a monthly spend limit in the Claude Console first)
Copy-Item .env.example .env
notepad .env

# 4. Download the speech, voice and face models (about 585 MB, checked against pinned hashes)
uv run python -m cadbot.models ensure

# 5. Self-tests, then start cadbot
uv run python -m cadbot.selftest --offline
uv run python -m cadbot.selftest --hardware
uv run python -m cadbot.selftest --api
uv run python -m cadbot
```

Talk to it; it answers through the headphones. Press **Esc** or click **Stop** in the face
window to cut it off; close the window to quit. Optional settings (microphone name, Whisper on
the GPU, household wishes) go in `config.yaml`: copy `config.example.yaml` to start.

**Troubleshooting**

- *`invalid peer certificate: UnknownIssuer` from uv:* something on the PC (antivirus, a
  company proxy) re-signs HTTPS traffic. Add `--system-certs` to uv commands. cadbot itself
  already uses the Windows certificate store.
- *GPU:* with an NVIDIA GPU, CUDA 12 and cuDNN 9, Whisper uses the GPU automatically; if the
  libraries are missing it falls back to the CPU and logs why.
- *Wrong microphone:* set `audio.input_device` in `config.yaml` to part of the device's name.

## Development

```powershell
uv run pytest -q          # fake hardware and a fake Claude: no devices, no API calls
uv run ruff check .
$env:CADBOT_PLATFORM = "windows"; uv run pytest -m hardware   # contract tests on real devices
```

All hardware access goes through `cadbot/platform` (`windows`, `pi`, `fake`); see
[CLAUDE.md](CLAUDE.md) for the project rules and [CONTRIBUTING.md](CONTRIBUTING.md).

## Credits

- The eyes are [RoboEyes](https://github.com/FluxGarage/RoboEyes) by Dennis Hoelscher,
  FluxGarage, through the MicroPython port
  [micropython-roboeyes](https://github.com/mchobby/micropython-roboeyes) by Meurisse
  Dominique, MC Hobby. Both GPL-3.0; the port is vendored in `cadbot/vendor/roboeyes/` with its
  notices and with cadbot's changes marked.
- Speech uses [Piper](https://github.com/OHF-Voice/piper1-gpl), [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  and [Silero VAD](https://github.com/snakers4/silero-vad). See
  [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for every component and its licence.

## Licence

cadbot is free software under the GNU General Public License, version 3 or (at your option)
any later version. See [LICENSE](LICENSE).
