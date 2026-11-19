# cadbot: notes for Claude Code

The full design is in `docs/cadbot-design.md`; it is the source of truth, and its "Decisions"
section is settled. Read the relevant section before changing behaviour.

## Key rules

- **Claude decides everything.** Every input becomes an event message to Claude; Claude acts
  only through tool calls. Local code senses, transcribes, speaks, animates and executes tools.
  Don't add local logic that decides whom to greet, what matters or what to say.
- **Except the safety rules enforced in code:** the confirmation gate on sending/deleting, the
  consent gate for remembering people, incognito and group-mode storage rules, and the canned
  replies when Claude can't be reached (`cadbot/actuators/canned.py`, `cadbot/agent/errors.py`).
- **Hardware only through `cadbot.platform`** (`windows`, `pi`, `fake`). No `sys.platform` /
  `os.name` checks and no hardware libraries (sounddevice, cv2.VideoCapture, gpiozero, serial,
  pygame.display/event, subprocess) outside `cadbot/platform/`. `tests/platform/test_isolation.py`
  enforces this.
- **Conversation history is append-only.** Opus 5.5 always thinks, and its thinking blocks are
  only valid while earlier turns are unchanged. Report interruptions in the next user message;
  never rewrite earlier turns.
- **Never commit secrets or personal data:** API keys, `.env`, tokens, databases, memory files,
  face data, photos, logs, models, recordings. Tests use the fake platform and the fake Claude
  client in `tests/fakes/`; no real API calls in tests or CI.
- **GPL-3.0-or-later.** Every source file starts with the SPDX header (a test checks). Changes to
  vendored code (`cadbot/vendor/`) are marked with a dated `cadbot change` comment.
- Keep functions small and typed, async throughout, logging via `logging`. Commit in small,
  logical steps; don't push unless asked.

## Layout

- `cadbot/platform/`: hardware abstraction (`base.py` interfaces, `windows/`, `pi/` untested,
  `fake/`, `common/` shared implementations)
- `cadbot/agent/`: agent loop, tool executor, error mapping, tools (`tools/`), session
- `cadbot/prompts/system.md`: the system prompt; behaviour lives here, not in code
- `cadbot/sensors/`: VAD, Whisper, listener · `cadbot/actuators/`: Piper speech, canned clips
- `cadbot/face/`: RoboEyes adapter, expressions, mouth, renderer · `cadbot/vendor/roboeyes/`
- `cadbot/vision/`: camera task (`loop.py`), frame gate, YuNet/SFace (`faces.py`), tracker
- `cadbot/people/`: consent-gated SQLite store (`store.py`), in-memory registry and matcher
- `cadbot/models/`: pinned model downloads · `cadbot/selftest/`: per-machine checks
- `cadbot/admin/`: owner commands (`python -m cadbot.admin people | forget`)

## Commands

```powershell
uv sync --extra dev                       # add --system-certs if TLS is intercepted
uv run pytest -q                          # all tests, fake hardware (CADBOT_PLATFORM=fake default)
uv run ruff check .
$env:CADBOT_PLATFORM="windows"; uv run pytest -m hardware   # contract tests on real devices
uv run python -m cadbot.models ensure     # download and verify models
uv run python -m cadbot.selftest --offline   # also --hardware, --api
uv run python -m cadbot                   # run (add -v to log transcripts)
uv run python -m cadbot.admin people      # whom cadbot remembers; `forget --name X` erases
uv run python -m cadbot.admin spend       # estimated API spend from cadbot's own log
```

## Milestones

M1 (talks), M2 (sees: camera, frame gate, observation events, eyes that follow) and M3
(remembers names: YuNet + SFace, tracker, multi-angle views, remember/confirm/forget with the
consent and confirmation gates) are done. Next is M4 (reminders: APScheduler + SQLite, timer
events). Don't build later milestones early; add them as new tools in `cadbot/agent/tools/`
and new event types in `cadbot/bus.py`.

- Images make history grow fast: server-side compaction (beta `compact-2026-01-12`) keeps it
  bounded. Don't trim or edit history by hand.
- Nothing about a person may be written without consent: go through `PeopleRegistry` /
  `PeopleStore`, which enforce it. Frames are never written to disk.
