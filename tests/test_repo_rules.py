# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Repository rules: licence headers, pinned models, no unlicensed media or secrets."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from cadbot.models.manifest import MANIFEST, VOICE_FILES, WHISPER_DIR

REPO = Path(__file__).resolve().parents[1]
HEADER = "# SPDX-License-Identifier: GPL-3.0-or-later"
VENDORED = {REPO / "cadbot" / "vendor" / "roboeyes" / "roboeyes.py"}
MEDIA = {".wav", ".mp3", ".flac", ".ogg", ".png", ".jpg", ".jpeg", ".mp4", ".avi", ".webm"}


def python_files() -> list[Path]:
    return sorted(p for folder in ("cadbot", "tests") for p in (REPO / folder).rglob("*.py"))


@pytest.mark.parametrize("path", python_files(), ids=lambda p: p.relative_to(REPO).as_posix())
def test_licence_header(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if path in VENDORED:
        assert "GNU General Public License" in text and "cadbot change" in text
    else:
        assert text.startswith(HEADER), f"{path} needs the GPL-3.0 header"


def test_models_are_pinned_and_hashed() -> None:
    dests = [m.dest for m in MANIFEST]
    assert len(dests) == len(set(dests))
    for model in MANIFEST:
        assert re.fullmatch(r"[0-9a-f]{64}", model.sha256), model.dest
        assert model.url.startswith("https://") and model.size > 0
        assert re.search(r"/resolve/[0-9a-f]{40}/", model.url), f"{model.dest} not pinned"
    assert any(m.dest.startswith(WHISPER_DIR + "/") for m in MANIFEST)
    assert all(rel in dests for rel in VOICE_FILES.values())
    for needed in ("face_detection_yunet_2023mar.onnx", "face_recognition_sface_2021dec.onnx"):
        assert any(m.dest.endswith(needed) for m in MANIFEST)


def test_no_unlicensed_media_in_tests() -> None:
    """Recordings or face images in tests need a matching licence note (<file>.LICENSE)."""
    for path in (REPO / "tests").rglob("*"):
        if path.suffix.lower() in MEDIA:
            assert path.with_name(path.name + ".LICENSE").is_file(), f"{path} has no licence"


def test_gitignore_covers_private_data() -> None:
    ignore = (REPO / ".gitignore").read_text(encoding="utf-8")
    for pattern in (".env", "secrets.env", "*.db", "memories/", "faces/", "photos/", "logs/",
                    "models/", "recordings/", "client_secret*.json", "token*.json", "config.yaml"):
        assert pattern in ignore, pattern


def committable_files() -> list[Path]:
    """Files git would commit: tracked, plus untracked ones that aren't ignored."""
    try:
        out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                             cwd=REPO, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git not available")
    return [REPO / line for line in out.splitlines() if line]


def test_no_api_keys_committed() -> None:
    key = re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")
    for path in committable_files():
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        assert not key.search(text), f"possible API key in {path}"
