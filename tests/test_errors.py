# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Real SDK exceptions map to the design's error table."""

from __future__ import annotations

from typing import Any

import anthropic
import httpx2
import pytest

from cadbot.actuators.canned import CANNED
from cadbot.agent.errors import CANNED_KEY, NEEDS_OWNER, RETRYABLE, ErrorKind, classify

REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def status_error(cls: type[anthropic.APIStatusError], status: int, err_type: str,
                 message: str = "x", headers: dict[str, str] | None = None,
                 error_code: str | None = None) -> anthropic.APIStatusError:
    error: dict[str, Any] = {"type": err_type, "message": message}
    if error_code:
        error["details"] = {"error_code": error_code}
    body = {"type": "error", "error": error}
    response = httpx2.Response(status, json=body, request=REQUEST, headers=headers or {})
    return cls(message, response=response, body=body)


@pytest.mark.parametrize(("exc", "kind"), [
    (status_error(anthropic.OverloadedError, 529, "overloaded_error"), ErrorKind.OVERLOADED),
    (status_error(anthropic.RateLimitError, 429, "rate_limit_error"), ErrorKind.RATE_LIMIT),
    (status_error(anthropic.InternalServerError, 500, "api_error"), ErrorKind.SERVER_ERROR),
    (status_error(anthropic.AuthenticationError, 401, "authentication_error"), ErrorKind.AUTH),
    (status_error(anthropic.PermissionDeniedError, 403, "permission_error"),
     ErrorKind.PERMISSION),
    (status_error(anthropic.NotFoundError, 404, "not_found_error"), ErrorKind.PERMISSION),
    (status_error(anthropic.ContentTooLargeError, 413, "request_too_large"),
     ErrorKind.TOO_LARGE),
    (status_error(anthropic.BadRequestError, 400, "invalid_request_error",
                  "prompt is too long: 1200000 tokens"), ErrorKind.TOO_LARGE),
    (status_error(anthropic.BadRequestError, 400, "invalid_request_error",
                  "Your credit balance is too low"), ErrorKind.BUDGET),
    (status_error(anthropic.PaymentRequiredError, 402, "billing_error"), ErrorKind.BUDGET),
    (status_error(anthropic.BadRequestError, 400, "invalid_request_error", "bad field"),
     ErrorKind.BAD_REQUEST),
    (anthropic.APIConnectionError(request=REQUEST), ErrorKind.OFFLINE),
    (anthropic.APITimeoutError(request=REQUEST), ErrorKind.TIMEOUT),
    (RuntimeError("boom"), ErrorKind.UNKNOWN),
])
def test_classify(exc: BaseException, kind: ErrorKind) -> None:
    assert classify(exc).kind == kind


def test_retry_after_and_request_id_are_kept() -> None:
    exc = status_error(anthropic.RateLimitError, 429, "rate_limit_error",
                       headers={"retry-after": "30", "request-id": "req_123"})
    failure = classify(exc)
    assert failure.retry_after_s == 30.0 and failure.request_id == "req_123"


def test_policy_tables_are_complete() -> None:
    assert set(CANNED_KEY) == set(ErrorKind)
    assert all(key in CANNED for key in CANNED_KEY.values())
    assert RETRYABLE.isdisjoint(NEEDS_OWNER)
