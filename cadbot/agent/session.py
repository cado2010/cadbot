# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""The running conversation with Claude. Append-only.

History is never edited: Opus 5.5 keeps its thinking blocks valid only while earlier turns
stay unchanged. Interruptions are reported in the next user message instead of rewriting
cadbot's last turn. Long-session trimming (compaction) arrives in a later milestone.
"""

from __future__ import annotations

from typing import Any


def to_param(block: Any) -> dict[str, Any]:
    """An SDK content block (or a dict) as a request parameter, unchanged."""
    if isinstance(block, dict):
        return block
    return block.to_dict()


class Session:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    def add_user(self, content: list[dict[str, Any]]) -> None:
        """Add user content; merges into the previous message if that was also from the user."""
        if not content:
            return
        if self.messages and self.messages[-1]["role"] == "user":
            self.messages[-1]["content"].extend(content)
        else:
            self.messages.append({"role": "user", "content": list(content)})

    def add_assistant(self, content: list[Any]) -> None:
        self.messages.append({"role": "assistant", "content": [to_param(b) for b in content]})

    def window(self) -> list[dict[str, Any]]:
        return self.messages

    def reset(self) -> None:
        """Start fresh; used only when a request is too large to send at all."""
        self.messages.clear()

    def pending_tool_use_ids(self) -> list[str]:
        """tool_use ids in the last assistant message that have no tool_result yet."""
        if not self.messages or self.messages[-1]["role"] != "assistant":
            return []
        return [b["id"] for b in self.messages[-1]["content"] if b.get("type") == "tool_use"]
