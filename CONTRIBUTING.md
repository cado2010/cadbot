# Contributing to cadbot

Thanks for helping. cadbot is licensed under GPL-3.0-or-later, and **contributions are accepted
under the same licence**: by opening a pull request you agree that your contribution is
licensed under GPL-3.0-or-later.

## Before you start

- Read [docs/cadbot-design.md](docs/cadbot-design.md). The "Decisions" section is settled.
- Read [CLAUDE.md](CLAUDE.md) for the project rules. The important ones:
  - Claude makes every decision. Local code senses, speaks and executes tool calls; it doesn't
    decide whom to greet or what matters. The exceptions are the safety rules enforced in code.
  - Hardware is reached only through `cadbot.platform`. No `sys.platform` or `os.name` checks,
    and no hardware libraries, anywhere else (a test enforces this).
  - Never commit secrets or personal data, including recordings or face images of real people.

## Workflow

```powershell
uv sync --extra dev
uv run pytest -q      # fake hardware, fake Claude client: no devices or API key needed
uv run ruff check .
```

- Keep functions small and typed, use `async` for I/O, and log with the `logging` module.
- Every source file starts with the licence header:
  `# SPDX-License-Identifier: GPL-3.0-or-later` and `# Copyright (C) <year> cadbot contributors`.
- New tools need help metadata (`HelpInfo`); a test fails without it.
- Test media (audio, images) must be synthetic or properly licensed, with a `<file>.LICENSE` note
  next to it.
- When you add a dependency, add it to `THIRD_PARTY_NOTICES.md`.
- Pull requests from forks run CI without secrets; that's expected.

## Reporting bugs

Open an issue with steps to reproduce. For security problems, see [SECURITY.md](SECURITY.md).
