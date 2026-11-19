# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""The parts of the (untested-on-hardware) Pi implementation that can be checked without it."""

from __future__ import annotations

import struct

from cadbot.platform.pi.camera import v4l2_controls
from cadbot.platform.pi.presence import FOOTER, HEADER, parse_frames
from cadbot.platform.pi.wifi import parse_nmcli, signal_percent_to_dbm


def ld2410_frame(state: int, moving: int, stationary: int) -> bytes:
    payload = bytes([0x02, 0xAA, state]) + struct.pack("<HBHBH", moving, 60, stationary, 40, 150) \
        + bytes([0x55, 0x00])
    return HEADER + struct.pack("<H", len(payload)) + payload + FOOTER


def test_ld2410_frames_across_reads() -> None:
    data = bytearray(b"\x00\x01" + ld2410_frame(1, 120, 0) + ld2410_frame(2, 0, 85)[:7])
    readings = parse_frames(data)
    assert len(readings) == 1
    assert readings[0].present and readings[0].distance_cm == 120
    data.extend(ld2410_frame(2, 0, 85)[7:])
    readings = parse_frames(data)
    assert readings[0].distance_cm == 85 and readings[0].extra["state"] == 2
    assert data == bytearray()


def test_ld2410_no_target_and_bad_footer() -> None:
    frame = ld2410_frame(0, 0, 0)
    assert parse_frames(bytearray(frame))[0].present is False
    broken = bytearray(frame[:-1] + b"\x00")
    assert parse_frames(broken) == []


def test_nmcli_parsing_with_escaped_colons() -> None:
    out = ("AA\\:BB\\:CC\\:DD\\:EE\\:FF:80:Home Net\n"
           "11\\:22\\:33\\:44\\:55\\:66:30:Cafe\\: Guest\n"
           "garbage\n")
    aps = parse_nmcli(out)
    assert [(a.bssid, a.rssi_dbm, a.ssid) for a in aps] == [
        ("aa:bb:cc:dd:ee:ff", -60, "Home Net"),
        ("11:22:33:44:55:66", -85, "Cafe: Guest"),
    ]
    assert signal_percent_to_dbm(100) == -50 and signal_percent_to_dbm(0) == -100


def test_v4l2_commands() -> None:
    assert v4l2_controls("/dev/video0", "focus", None) == [
        ["v4l2-ctl", "-d", "/dev/video0", "-c", "focus_automatic_continuous=1"]]
    cmds = v4l2_controls("/dev/video0", "exposure", 250)
    assert cmds[0][-1] == "auto_exposure=1" and cmds[1][-1] == "exposure_time_absolute=250"
