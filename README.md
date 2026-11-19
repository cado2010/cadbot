# cadbot

cadbot is a friendly home assistant bot for the desk. It listens, talks and shows an animated
face, and it introduces itself as cadbot. Every decision is made by Claude (`claude-opus-5-5`):
the device only senses (microphone, later the camera), transcribes speech locally, speaks, and
carries out the tool calls Claude asks for.

The full design is in [docs/cadbot-design.md](docs/cadbot-design.md). It targets a Raspberry
Pi 5 with a touchscreen, and runs on a Windows PC for development.

**Status: milestones M1–M3.** cadbot talks (microphone → Silero VAD → faster-whisper on the
device → Claude → Piper speech), sees (a camera frame goes to Claude when the scene changes,
a new face appears, or at an interval Claude chooses), and remembers people who agree to it
(local YuNet + SFace face matching, a tracker, and a consent-gated store). The face window
shows the expressions Claude chooses, and the eyes follow the person in front of it.
Reminders and Google accounts come in later milestones.

## Privacy notice

Please read this before running cadbot, and tell people near the device what it does.

- **What leaves the device:** the *text* of what the microphone hears, and *camera frames*
  (640×360 JPEGs) when the scene changes, a new face appears, someone speaks, or at the
  interval Claude chooses. They go to the Claude API (Anthropic) so Claude can decide what to
  do. There is no wake word, so this includes speech not meant for cadbot. Web searches run on
  Anthropic's side. Anthropic's API data-retention terms apply to what is sent.
- **What stays on the device:** raw audio and the continuous video are processed in memory and
  never saved. Speech-to-text, text-to-speech and face matching run locally.
- **Remembering people:** cadbot asks before it remembers anyone, and saves nothing about a
  person until they clearly say yes; this is enforced in code. For people who agree it keeps,
  on this device only: face embeddings (numbers, not photos), one small face thumbnail, their
  name, a short appearance note, and how and when they agreed. They are kept until the person
  says "forget me" (which erases everything after a spoken confirmation), or the owner runs
  `uv run python -m cadbot.admin forget --name <name>`. People who say no, or give no name,
  are recognised only for that visit and nothing is written. Face recognition is a
  convenience, not proof of identity.
- **Logs** are written to the data folder and include what was heard only with `--verbose`.
- **Your API key** stays in your local `.env` file, which Git ignores.

Tell people near the device that it sees and listens, for example with a small sign.

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
window to cut it off; close the window to quit. See whom it remembers with
`uv run python -m cadbot.admin people`. Optional settings (microphone name, Whisper on
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
