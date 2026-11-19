# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Physical privacy switch and LED via gpiozero (lgpio backend on the Pi 5).

UNTESTED: written before the hardware arrived. Pins come from CADBOT_PRIVACY_SWITCH_PIN and
CADBOT_PRIVACY_LED_PIN (BCM numbering).
"""

from __future__ import annotations

import os


class GpioPrivacySwitch:
    def __init__(self, switch_pin: int, led_pin: int) -> None:
        from gpiozero import LED, Button

        self._switch = Button(switch_pin, pull_up=True)
        self._led = LED(led_pin)

    def is_private(self) -> bool:
        return bool(self._switch.is_pressed)

    def set_led(self, on: bool) -> None:
        if on:
            self._led.on()
        else:
            self._led.off()


def make_privacy() -> GpioPrivacySwitch:
    return GpioPrivacySwitch(
        switch_pin=int(os.environ.get("CADBOT_PRIVACY_SWITCH_PIN", "17")),
        led_pin=int(os.environ.get("CADBOT_PRIVACY_LED_PIN", "27")),
    )
