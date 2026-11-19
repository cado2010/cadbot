# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Hardware interfaces and the plain data types that cross the platform boundary.

Everything above this layer talks to hardware only through these protocols. No
platform-specific type (sounddevice streams, VideoCapture, GPIO pins...) leaks out.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

import numpy as np

if TYPE_CHECKING:  # pygame surfaces are drawing objects, not hardware; only the type is needed
    import pygame

PlatformName = Literal["windows", "pi", "fake"]

AUDIO_SAMPLE_RATE = 16_000
"""Sample rate of every AudioIn chunk (mono float32)."""

LOGICAL_SCREEN = (1280, 720)
"""Size of the Display surface the app draws on, whatever the real window size."""


# --------------------------------------------------------------------------- data types


@dataclass(frozen=True)
class Capabilities:
    """What this platform can actually do. Goes into the system prompt and steers the app."""

    night_vision: bool = False
    presence_sensor: bool = False
    privacy_switch: bool = False
    echo_cancellation: bool = False
    touch: bool = False
    keyboard: bool = False
    camera: bool = True
    wifi_scan: bool = False

    def describe(self) -> list[str]:
        """Plain-language lines for the system prompt."""
        def yes_no(flag: bool, yes: str, no: str) -> str:
            return yes if flag else no

        return [
            yes_no(self.camera, "has a camera", "has no camera"),
            yes_no(self.night_vision, "can see in the dark (infrared)",
                   "cannot see in the dark"),
            yes_no(self.echo_cancellation,
                   "has echo cancellation, so people can talk over you",
                   "has no echo cancellation: the mic is muted while you speak, so people "
                   "interrupt with the stop button or the Esc key"),
            yes_no(self.touch, "has a touchscreen", "has no touchscreen (mouse clicks only)"),
            yes_no(self.presence_sensor, "has a presence sensor", "has no presence sensor"),
            yes_no(self.privacy_switch, "has a physical privacy switch",
                   "has no physical privacy switch"),
        ]


@dataclass(frozen=True)
class Frame:
    """One camera frame: BGR uint8 image (H, W, 3)."""

    image: np.ndarray
    timestamp: float
    is_night: bool = False


@dataclass(frozen=True)
class AudioChunk:
    """Mono float32 samples in [-1, 1] at AUDIO_SAMPLE_RATE."""

    samples: np.ndarray
    timestamp: float
    sample_rate: int = AUDIO_SAMPLE_RATE


@dataclass(frozen=True)
class WifiAP:
    bssid: str
    rssi_dbm: int
    ssid: str


@dataclass(frozen=True)
class InputEvent:
    """A user input from the display: key press, click/touch, or window close.

    `pos` is in LOGICAL_SCREEN coordinates.
    """

    kind: Literal["key", "pointer_down", "quit"]
    key: str = ""
    pos: tuple[int, int] = (0, 0)


@dataclass
class PresenceReading:
    present: bool
    distance_cm: int | None = None
    extra: dict[str, int] = field(default_factory=dict)


# --------------------------------------------------------------------------- interfaces


@runtime_checkable
class Camera(Protocol):
    def open(self) -> None: ...
    def read(self) -> Frame | None: ...
    def set_focus(self, value: int | None) -> None: ...
    def set_exposure(self, value: int | None) -> None: ...
    def close(self) -> None: ...


@runtime_checkable
class AudioIn(Protocol):
    """Microphone. `chunks()` yields AudioChunks until `stop()` is called."""

    async def start(self) -> None: ...
    def chunks(self) -> AsyncIterator[AudioChunk]: ...
    async def stop(self) -> None: ...


@runtime_checkable
class AudioOut(Protocol):
    """Speaker. `play` returns when the audio has finished or was stopped."""

    async def start(self) -> None: ...
    async def play(self, samples: np.ndarray, sample_rate: int) -> bool:
        """Play mono float32 samples. Returns False if stopped before the end."""
        ...
    def stop(self) -> None:
        """Stop playback at once (target: under 200 ms) and drop anything queued."""
        ...
    def level(self) -> float:
        """Current output level, 0..1, for the mouth animation."""
        ...
    @property
    def is_playing(self) -> bool: ...
    async def close(self) -> None: ...


@runtime_checkable
class Display(Protocol):
    def open(self) -> None: ...
    @property
    def surface(self) -> pygame.Surface:
        """LOGICAL_SCREEN-sized surface to draw on."""
        ...
    def present(self) -> None: ...
    def poll_events(self) -> list[InputEvent]: ...
    def close(self) -> None: ...


@runtime_checkable
class PresenceSensor(Protocol):
    def read(self) -> PresenceReading: ...
    def close(self) -> None: ...


@runtime_checkable
class PrivacySwitch(Protocol):
    def is_private(self) -> bool: ...
    def set_led(self, on: bool) -> None: ...


@runtime_checkable
class WifiScanner(Protocol):
    def scan(self) -> list[WifiAP]: ...


@runtime_checkable
class SystemInfo(Protocol):
    def cpu_temperature_c(self) -> float | None: ...
    def cpu_load(self) -> float: ...
    def model_name(self) -> str: ...


@runtime_checkable
class Paths(Protocol):
    @property
    def data_dir(self) -> Path: ...
    @property
    def config_dir(self) -> Path: ...
    @property
    def cache_dir(self) -> Path: ...
    @property
    def models_dir(self) -> Path: ...
    @property
    def logs_dir(self) -> Path: ...
    def get_secret(self, name: str) -> str | None:
        """Read a secret (API key...). Never log the value."""
        ...


@runtime_checkable
class Lifecycle(Protocol):
    def notify_ready(self) -> None: ...
    def watchdog_ping(self) -> None: ...
    def notify_stopping(self) -> None: ...


# --------------------------------------------------------------------------- the bundle


@dataclass
class Platform:
    """Everything hardware-specific, chosen once at startup by get_platform()."""

    name: PlatformName
    capabilities: Capabilities
    paths: Paths
    system: SystemInfo
    lifecycle: Lifecycle
    _camera: Callable[[], Camera]
    _audio_in: Callable[[str | None], AudioIn]
    _audio_out: Callable[[str | None], AudioOut]
    _display: Callable[[], Display]
    _presence: Callable[[], PresenceSensor]
    _privacy: Callable[[], PrivacySwitch]
    _wifi: Callable[[], WifiScanner]

    def camera(self) -> Camera:
        return self._camera()

    def audio_in(self, device: str | None = None) -> AudioIn:
        return self._audio_in(device)

    def audio_out(self, device: str | None = None) -> AudioOut:
        return self._audio_out(device)

    def display(self) -> Display:
        return self._display()

    def presence_sensor(self) -> PresenceSensor:
        return self._presence()

    def privacy_switch(self) -> PrivacySwitch:
        return self._privacy()

    def wifi_scanner(self) -> WifiScanner:
        return self._wifi()


def not_implemented(platform: str, interface: str, milestone: str) -> NotImplementedError:
    return NotImplementedError(
        f"{interface} is not implemented on the '{platform}' platform yet "
        f"(planned for {milestone}). See docs/cadbot-design.md, 'Hardware abstraction layer'."
    )
