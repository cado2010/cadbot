# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Dennis Hoelscher - www.fluxgarage.com (Arduino version)
# Copyright (C) 2025 Meurisse Dominique - shop.mchobby.be (MicroPython version)
# Copyright (C) 2026 cadbot contributors (CPython adaptation)
"""RoboEyes, vendored from https://github.com/mchobby/micropython-roboeyes (GPL-3.0).

See README.vendored.md for the upstream commit and the list of changes.
"""

from .roboeyes import (
    ANGRY,
    BGCOLOR,
    CURIOUS,
    DEFAULT,
    E,
    FGCOLOR,
    FROZEN,
    HAPPY,
    N,
    NE,
    NW,
    OFF,
    ON,
    S,
    SCARY,
    SE,
    SW,
    TIRED,
    W,
    RoboEyes,
)

__all__ = [
    "ANGRY", "BGCOLOR", "CURIOUS", "DEFAULT", "FGCOLOR", "FROZEN", "HAPPY", "NE", "NW", "OFF",
    "ON", "SCARY", "SE", "SW", "TIRED", "E", "N", "RoboEyes", "S", "W",
]
