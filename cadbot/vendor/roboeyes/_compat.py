# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""CPython stand-ins for the MicroPython features the RoboEyes port uses."""

import time as _time


def const(value):
    """micropython.const: a plain value on CPython."""
    return value


class ticks:
    """The subset of MicroPython's `time` module that roboeyes.py calls."""

    @staticmethod
    def ticks_ms():
        return int(_time.monotonic() * 1000)

    @staticmethod
    def ticks_diff(a, b):
        return a - b

    @staticmethod
    def ticks_add(a, b):
        return a + b
