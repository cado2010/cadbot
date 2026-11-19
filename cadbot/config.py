# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Settings: defaults here, overridden by config.yaml and its per-platform section.

Lookup order for the file: $CADBOT_CONFIG, ./config.yaml, <platform config dir>/config.yaml.
Secrets never live here; they come from Paths.get_secret().
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

log = logging.getLogger(__name__)


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AudioConfig(_Section):
    input_device: str | None = None
    output_device: str | None = None
    vad_threshold: float = Field(0.5, ge=0.05, le=0.95)
    end_silence_ms: int = 700
    min_speech_ms: int = 250
    max_utterance_s: float = 30.0
    pre_roll_ms: int = 300
    half_duplex_tail_ms: int = 300
    barge_in_min_s: float = 0.4


class SttConfig(_Section):
    model: str = "small.en"
    device: Literal["auto", "cuda", "cpu"] = "auto"
    compute_type_cpu: str = "int8"
    compute_type_cuda: str = "int8_float16"
    beam_size: int = 1
    language: str | None = "en"
    hotwords: str = "cadbot"
    """Words Whisper should expect, so it hears "cadbot" rather than "Kedbot"."""


class TtsConfig(_Section):
    voices: dict[str, str] = Field(default_factory=lambda: {"en": "en_US-lessac-medium"})


class AgentConfig(_Section):
    model: str = "claude-opus-5-5"
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "low"
    max_tokens: int = 1500
    max_tool_rounds: int = 8
    speak_max_words: int = 60
    web_search_max_uses: int = 3
    fallbacks: Literal["default", "off"] = "default"
    request_timeout_s: float = 60.0
    one_moment_after_s: float = 3.0
    retry_delays_s: list[float] = Field(default_factory=lambda: [1.0, 4.0])
    compact_at_tokens: int = Field(60_000, ge=50_000)
    """Server-side compaction summarises older history beyond this many input tokens."""


CameraToClaude = Literal["images", "readings", "none"]


class VisionConfig(_Section):
    enabled: bool = True
    """False switches the camera off entirely (no recognition, no eye-following)."""
    send_to_claude: CameraToClaude = "images"
    """Cost control; face recognition keeps running locally in every mode.
    images: frames and face readings on scene change, new face or heartbeat.
    readings: face readings as text only, when someone appears or at the heartbeat.
    none: no camera events; what you say still carries who is in view, as text."""
    camera_index: int = 0
    analyze_hz: float = 4.0
    """Face detection rate while something is happening (1 Hz when the scene is still)."""
    gate_pixel_delta: int = 25
    """Grey-level change (0-255) for a pixel to count as changed."""
    gate_change_fraction: float = 0.03
    """Share of changed pixels that makes a frame worth sending."""
    min_observation_interval_s: float = 10.0
    default_watch_interval_s: float = 300.0
    """Heartbeat: an observation at least this often, until Claude sets its own interval."""
    jpeg_quality: int = Field(80, ge=30, le=95)
    min_face_px: int = 40
    match_confident: float = 0.50
    match_maybe: float = 0.363
    """SFace cosine similarity: above maybe = "not sure", above confident = a match."""
    max_views_per_person: int = 8
    pending_forget_after_s: float = 600.0
    """Unsaved (pending or declined) people are dropped this long after leaving view."""
    track_timeout_s: float = 2.0


class FaceConfig(_Section):
    fps: int = 30
    idle_after_speech_s: float = 2.5


class NetConfig(_Section):
    health_url: str = "https://api.anthropic.com/"
    health_interval_s: float = 30.0
    failures_before_offline: int = 2
    canned_min_interval_s: float = 60.0


class PricingConfig(_Section):
    """Prices for cost estimates, in USD. Defaults are claude-opus-5-5's list prices as of
    Nov 2026; check https://www.anthropic.com/pricing and update if they change."""

    input_per_mtok: float = 4.00
    output_per_mtok: float = 20.00
    cache_write_per_mtok: float = 5.00
    """5-minute prompt-cache writes: 1.25x the input price."""
    cache_read_per_mtok: float = 0.20
    web_search_per_1k: float = 10.00


class AccountConfig(_Section):
    api_key_id: str | None = None
    """The Console id of cadbot's API key (apikey_...), for `cadbot.admin spend`. Found
    automatically from the key's hint when left empty."""


class HouseholdConfig(_Section):
    wishes: str = ""
    """Free text for the system prompt: greeting habits, quiet hours, preferences."""


class Config(_Section):
    audio: AudioConfig = Field(default_factory=AudioConfig)
    stt: SttConfig = Field(default_factory=SttConfig)
    tts: TtsConfig = Field(default_factory=TtsConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    face: FaceConfig = Field(default_factory=FaceConfig)
    vision: VisionConfig = Field(default_factory=VisionConfig)
    net: NetConfig = Field(default_factory=NetConfig)
    household: HouseholdConfig = Field(default_factory=HouseholdConfig)
    pricing: PricingConfig = Field(default_factory=PricingConfig)
    account: AccountConfig = Field(default_factory=AccountConfig)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def find_config_file(config_dir: Path | None) -> Path | None:
    candidates = [os.environ.get("CADBOT_CONFIG"), "config.yaml"]
    if config_dir is not None:
        candidates.append(str(config_dir / "config.yaml"))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return None


def load_config(platform_name: str, config_dir: Path | None = None,
                path: Path | None = None) -> Config:
    """Read config.yaml (if any) and apply its `platforms.<name>` section on top."""
    path = path or find_config_file(config_dir)
    raw: dict[str, Any] = {}
    if path is not None:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        log.info("config: %s", path)
    platforms = raw.pop("platforms", {}) or {}
    raw = _deep_merge(raw, platforms.get(platform_name, {}) or {})
    return Config.model_validate(raw)
