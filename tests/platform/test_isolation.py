# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Hardware libraries, OS commands and platform checks live only in cadbot/platform."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "cadbot"
ALLOWED = (ROOT / "platform",)

FORBIDDEN_MODULES = {
    "sounddevice", "gpiozero", "serial", "lgpio", "RPi", "smbus", "psutil", "keyring",
    "subprocess", "winreg", "platform",
}
FORBIDDEN_ATTRIBUTES = {
    "sys.platform", "os.name", "os.uname", "os.system", "os.popen", "platform.system",
    "cv2.VideoCapture", "pygame.display", "pygame.event", "pygame.mouse", "pygame.mixer",
    "pygame.init",
}


def app_sources() -> list[Path]:
    return sorted(p for p in ROOT.rglob("*.py")
                  if not any(p.is_relative_to(allowed) for allowed in ALLOWED))


def dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def violations(source: str) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [f"import {a.name}" for a in node.names
                      if a.name.split(".")[0] in FORBIDDEN_MODULES]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            if node.module.split(".")[0] in FORBIDDEN_MODULES:
                found.append(f"from {node.module} import ...")
            found += [f"from {node.module} import {a.name}" for a in node.names
                      if f"{node.module}.{a.name}" in FORBIDDEN_ATTRIBUTES]
        elif isinstance(node, ast.Attribute) and dotted(node) in FORBIDDEN_ATTRIBUTES:
            found.append(str(dotted(node)))
    return found


def test_scanner_catches_violations() -> None:
    bad = ("import sounddevice\nimport sys\nfrom pygame import display\n"
           "if sys.platform == 'win32':\n    import pygame\n    pygame.display.init()\n")
    found = violations(bad)
    assert "import sounddevice" in found
    assert "sys.platform" in found
    assert "pygame.display" in found
    assert "from pygame import display" in found
    assert violations("import pygame\npygame.draw.circle(s, c, p, 3)\n") == []


@pytest.mark.parametrize("path", app_sources(), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_no_hardware_access_outside_platform(path: Path) -> None:
    assert violations(path.read_text(encoding="utf-8")) == []
