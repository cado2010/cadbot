# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Every model file cadbot downloads, pinned to an upstream commit and a SHA-256 hash.

Model and voice files are never stored in Git. Silero VAD needs no download: its ONNX file
ships inside the faster-whisper package.
"""

from __future__ import annotations

from dataclasses import dataclass

_HF = "https://huggingface.co"

WHISPER_REPO, WHISPER_REV = "Systran/faster-whisper-small.en", \
    "d1d751a5f8271d482d14ca55d9e2deeebbae577f"
TINY_REPO, TINY_REV = "Systran/faster-whisper-tiny.en", \
    "0d3d19a32d3338f10357c0889762bd8d64bbdeba"
PIPER_REPO, PIPER_REV = "rhasspy/piper-voices", "04ca88f5685ca5253c701af3687e155b113bd512"
YUNET_REPO, YUNET_REV = "opencv/face_detection_yunet", "3cc26e7f1014a5ee5d74a42acee58bafc9d0a310"
SFACE_REPO, SFACE_REV = "opencv/face_recognition_sface", \
    "3d7082438a6e4551e840c9b2bb60b71e8da4b524"


@dataclass(frozen=True)
class ModelFile:
    group: str
    """What it's for: 'whisper', 'voice:<lang>', 'faces'."""
    dest: str
    """Path under the models folder, with forward slashes."""
    url: str
    sha256: str
    size: int
    licence: str


def _hf(repo: str, rev: str, path: str) -> str:
    return f"{_HF}/{repo}/resolve/{rev}/{path}"


def _whisper(name: str, sha256: str, size: int) -> ModelFile:
    return ModelFile("whisper", f"whisper/small.en/{name}",
                     _hf(WHISPER_REPO, WHISPER_REV, name), sha256, size, "MIT")


def _tiny(name: str, sha256: str, size: int) -> ModelFile:
    """Whisper tiny.en: fast enough to catch "stop" while cadbot is talking."""
    return ModelFile("whisper-stop", f"whisper/tiny.en/{name}",
                     _hf(TINY_REPO, TINY_REV, name), sha256, size, "MIT")


_VOICE_DIR = "en/en_US/lessac/medium"
_VOICE_LICENCE = "see MODEL_CARD (Blizzard 2013 Lessac dataset licence)"


def _voice(name: str, sha256: str, size: int) -> ModelFile:
    return ModelFile("voice:en", f"voices/en_US-lessac-medium/{name}",
                     _hf(PIPER_REPO, PIPER_REV, f"{_VOICE_DIR}/{name}"), sha256, size,
                     _VOICE_LICENCE)


MANIFEST: tuple[ModelFile, ...] = (
    _whisper("config.json",
             "666a9605530ac1f61fa8177f3702b4dacec9966749e42610839fcc32661d5fae", 2657),
    _whisper("model.bin",
             "62b2a45b05ee59acb4a5341b33ee35e041395d378d418a18acfe4c9e768ee37a", 483_545_366),
    _whisper("tokenizer.json",
             "929c5252409436dce1b38a75d1abbcb5e132d170d8e324e4e04ed915fa2d22df", 2_128_466),
    _whisper("vocabulary.txt",
             "ff77588746d3a2595d32ab5b69ffd7b95ce2441ac57533cb66fc3eb575a115cf", 422_309),
    _tiny("config.json",
          "14b1b421a90349bc551b881461426b561a874049cb9e4c4864f2ca384f6a7cc5", 2317),
    _tiny("model.bin",
          "1a5afae06a4db91c975c9a9d78be5cc110ee4ea022ad57d55492e4550e936b2a", 75_537_502),
    _tiny("tokenizer.json",
          "929c5252409436dce1b38a75d1abbcb5e132d170d8e324e4e04ed915fa2d22df", 2_128_466),
    _tiny("vocabulary.txt",
          "ff77588746d3a2595d32ab5b69ffd7b95ce2441ac57533cb66fc3eb575a115cf", 422_309),
    _voice("en_US-lessac-medium.onnx",
           "5efe09e69902187827af646e1a6e9d269dee769f9877d17b16b1b46eeaaf019f", 63_201_294),
    _voice("en_US-lessac-medium.onnx.json",
           "efe19c417bed055f2d69908248c6ba650fa135bc868b0e6abb3da181dab690a0", 4885),
    _voice("MODEL_CARD",
           "ce49eb457742208166d399a40cdec2c7fa9db77960930031564ab56f12882645", 351),
    ModelFile("faces", "faces/face_detection_yunet_2023mar.onnx",
              _hf(YUNET_REPO, YUNET_REV, "face_detection_yunet_2023mar.onnx"),
              "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4", 232_589, "MIT"),
    ModelFile("faces", "faces/face_recognition_sface_2021dec.onnx",
              _hf(SFACE_REPO, SFACE_REV, "face_recognition_sface_2021dec.onnx"),
              "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79", 38_696_353,
              "Apache-2.0"),
)

WHISPER_DIR = "whisper/small.en"
VOICE_FILES = {"en": "voices/en_US-lessac-medium/en_US-lessac-medium.onnx"}
