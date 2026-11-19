# Security policy

cadbot runs in people's homes with a microphone, a camera and (in later milestones) access to
email accounts, so security reports are very welcome.

## Reporting a problem

Please **don't open a public issue** for a security problem. Use GitHub's private vulnerability
reporting instead: the repository's **Security** tab → **Report a vulnerability**. Include what
you found, how to reproduce it, and what an attacker could do with it.

You should get a reply within a week. Fixes are released as new tagged versions, and devices
pick them up through the verified-release updater described in the design.

## In scope

- Anything that leaks secrets (API keys, OAuth tokens) or personal data (transcripts, face data,
  memory files) off the device or into logs.
- Ways to bypass the rules enforced in code: the confirmation gate for sending or deleting, the
  consent gate for remembering people, incognito and group mode.
- Prompt injection that makes cadbot act against its owner (for example through web pages or
  email content).
- Problems in the update and release process.

## Not in scope

- Behaviour of Claude itself; report that to Anthropic.
- Issues that need physical access to an unlocked device.

## Never in the repository

API keys, OAuth client files and tokens, `.env` and `secrets.env`, databases, memory files,
face data, photos, logs, model files, and recordings of real people. If you spot any of these in
the repository or its history, report it as above.
