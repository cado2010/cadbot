# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""LD2410C mmWave presence sensor on the GPIO UART (/dev/serial0), 256000 baud.

UNTESTED on hardware. The frame parser is unit-tested with synthetic bytes.
"""

from __future__ import annotations

import struct

from cadbot.platform.base import PresenceReading

HEADER = b"\xf4\xf3\xf2\xf1"
FOOTER = b"\xf8\xf7\xf6\xf5"


def parse_frames(buffer: bytearray) -> list[PresenceReading]:
    """Consume complete report frames from the buffer; keep any trailing partial frame."""
    readings: list[PresenceReading] = []
    while True:
        start = buffer.find(HEADER)
        if start < 0:
            del buffer[: max(0, len(buffer) - (len(HEADER) - 1))]
            return readings
        del buffer[:start]
        if len(buffer) < 6:
            return readings
        (length,) = struct.unpack_from("<H", buffer, 4)
        end = 6 + length + len(FOOTER)
        if len(buffer) < end:
            return readings
        payload = bytes(buffer[6 : 6 + length])
        footer_ok = bytes(buffer[6 + length : end]) == FOOTER
        del buffer[:end]
        reading = _parse_payload(payload) if footer_ok else None
        if reading is not None:
            readings.append(reading)


def _parse_payload(payload: bytes) -> PresenceReading | None:
    # type(0x01 engineering / 0x02 basic), 0xAA, state, moving dist(2), moving energy,
    # stationary dist(2), stationary energy, detection dist(2), ...
    if len(payload) < 11 or payload[0] not in (0x01, 0x02) or payload[1] != 0xAA:
        return None
    state = payload[2]
    mov_dist, mov_energy, stat_dist, stat_energy, det_dist = struct.unpack_from(
        "<HBHBH", payload, 3)
    present = state != 0
    distance: int | None = None
    if state == 1:
        distance = mov_dist
    elif state == 2:
        distance = stat_dist
    elif state == 3:
        distance = min(mov_dist, stat_dist)
    return PresenceReading(present=present, distance_cm=distance, extra={
        "state": state, "moving_energy": mov_energy, "stationary_energy": stat_energy,
        "detection_distance_cm": det_dist,
    })


class LD2410CSensor:
    def __init__(self, port: str = "/dev/serial0", baud: int = 256_000) -> None:
        import serial

        self._serial = serial.Serial(port, baud, timeout=0)
        self._buffer = bytearray()
        self._last = PresenceReading(present=False)

    def read(self) -> PresenceReading:
        self._buffer.extend(self._serial.read(4096))
        readings = parse_frames(self._buffer)
        if readings:
            self._last = readings[-1]
        return self._last

    def close(self) -> None:
        self._serial.close()


def make_presence() -> LD2410CSensor:
    return LD2410CSensor()
