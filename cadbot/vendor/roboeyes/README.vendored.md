# Vendored: RoboEyes (MicroPython port)

- **Upstream:** https://github.com/mchobby/micropython-roboeyes
- **Commit:** `f3e609f8a1f5dcb8d2b4c86860246edf795edb39` (file `lib/roboeyes.py`)
- **Original Arduino library:** https://github.com/FluxGarage/RoboEyes
- **Copyright:** (C) 2024 Dennis Hoelscher, FluxGarage (Arduino version);
  (C) 2025 Meurisse Dominique, MC Hobby (MicroPython version)
- **Licence:** GNU General Public License v3.0. The full text is in `LICENSE.txt`, copied
  unchanged from upstream. `upstream_readme.md` is the upstream README, unchanged.

## Changes made for cadbot (2026-11-19)

Every change in `roboeyes.py` is marked in the code with a `cadbot change 2026-11-19` comment.

1. **CPython compatibility:** `micropython.const`, `time.ticks_ms/ticks_diff/ticks_add` and the
   separate `fbutil` library don't exist on CPython. They are replaced by `_compat.py`, and the
   framebuffer passed in provides `fill_rrect()` and `fill_triangle()` itself (cadbot's
   `PygameFrameBuffer` in `cadbot/face/fb_pygame.py`).
2. **Bug fix:** position `S` set the Y target from the X constraint, which moved the eyes off
   the bottom of the screen; it now uses the Y constraint.
3. **Continuous gaze:** new `look_at(x, y)` with x and y in -1..1, so the eyes can follow a
   person smoothly instead of jumping between the nine fixed positions.

`__init__.py` and `_compat.py` are new files written for cadbot.
