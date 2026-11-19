# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""The thin seam between the agent loop and the Anthropic SDK, so tests can use a fake."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol

import anthropic


class ClaudeStream(Protocol):
    def __aiter__(self) -> Any: ...
    async def get_final_message(self) -> Any: ...


class ClaudeClient(Protocol):
    def stream(self, **params: Any) -> AbstractAsyncContextManager[ClaudeStream]: ...


class AnthropicClient:
    """Streams from the beta Messages endpoint (needed for server-side refusal fallbacks).

    Retries are done by the agent (1 s then 4 s, with spoken feedback), so the SDK's own
    retries are off.
    """

    def __init__(self, api_key: str, timeout_s: float) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=0,
                                                timeout=timeout_s)

    def stream(self, **params: Any) -> AbstractAsyncContextManager[ClaudeStream]:
        return self._client.beta.messages.stream(**params)

    async def close(self) -> None:
        await self._client.close()
