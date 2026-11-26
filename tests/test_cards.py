# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Cards: text or pictures on the screen with the face in the corner, and safe downloads."""

from __future__ import annotations

import io
import time
from collections.abc import Iterator
from typing import Any

import httpx
import pygame
import pytest

from cadbot.face.card import CONTENT_AREA, DONE_BUTTON, MINI_FACE, Card, render_content, wrap
from cadbot.face.renderer import STOP_BUTTON, Face, FaceCallbacks
from cadbot.net.images import ImageError, check_public, decode_image, fetch_image
from cadbot.platform.base import InputEvent
from cadbot.platform.common.pygame_display import PygameDisplay
from tests.fakes.claude import reply, tool_use
from tests.fakes.harness import AgentHarness, make_harness, utterance
from tests.fakes.vision import frame


@pytest.fixture
def display() -> Iterator[PygameDisplay]:
    d = PygameDisplay(fullscreen=False, video_driver="dummy")
    d.open()
    yield d
    d.close()


def png(size: tuple[int, int] = (64, 32), colour: tuple[int, int, int] = (200, 30, 30)) -> bytes:
    surface = pygame.Surface(size)
    surface.fill(colour)
    buffer = io.BytesIO()
    pygame.image.save(surface, buffer, "x.png")
    return buffer.getvalue()


def draw(face: Face, frames: int = 3) -> None:
    for _ in range(frames):
        face.eyes.fpsTimer = -10_000
        face.tick()


# ----------------------------------------------------------------------- layout


def test_text_wraps_and_bullets() -> None:
    pygame.font.init()
    font = pygame.font.Font(None, 40)
    lines = wrap(font, "Ingredients:\n- two eggs\n- " + "flour " * 30, 400)
    assert lines[0] == "Ingredients:" and lines[1] == "• two eggs"
    assert len(lines) > 3 and all(font.size(line)[0] <= 400 for line in lines)


def test_long_text_shrinks_then_truncates() -> None:
    pygame.font.init()
    short = render_content(Card(text="Hello"))
    assert short.get_size() == CONTENT_AREA.size
    render_content(Card(text="word " * 3000))  # far too long: truncated, never overflows


def test_picture_is_fitted_not_stretched() -> None:
    picture = decode_image(png((400, 100), (0, 200, 0)))
    content = render_content(Card(image=picture))
    green = [x for x in range(content.get_width())
             if content.get_at((x, 40))[:3] == (0, 200, 0)]
    assert green and len(green) <= CONTENT_AREA.w  # 4:1 picture keeps its shape


# ----------------------------------------------------------------------- showing and closing


def test_card_shrinks_the_face_into_the_corner(display: PygameDisplay) -> None:
    face = Face(display)
    face.eyes.set_auto_blinker(0)
    draw(face, 20)  # let the eyes open
    face.show_card(Card(title="Recipe", text="- two eggs"))
    draw(face)
    corner = [display.surface.get_at((x, y))[:3] for x in range(MINI_FACE.x, MINI_FACE.right, 2)
              for y in range(MINI_FACE.y, MINI_FACE.bottom, 2)]
    assert any(min(c) > 200 for c in corner)  # the white of the eyes, drawn small top-right
    face.hide_card()
    draw(face)
    assert display.surface.get_at(MINI_FACE.center)[:3] != (20, 24, 36)


def test_done_button_and_esc_close_the_card(display: PygameDisplay) -> None:
    closed: list[tuple[str, str]] = []
    stops: list[int] = []
    face = Face(display, callbacks=FaceCallbacks(
        on_stop=lambda: stops.append(1),
        on_card_closed=lambda title, why: closed.append((title, why))))
    face.show_card(Card(title="List", text="a"))
    face.handle_events([InputEvent("pointer_down", pos=DONE_BUTTON.center)])
    assert face.card is None and closed == [("List", "touch")]
    face.show_card(Card(title="Map", text="b"))
    face.set_busy(True)  # while speaking, Esc stops the speech first
    face.handle_events([InputEvent("key", key="escape")])
    assert stops == [1] and face.card is not None
    face.set_busy(False)
    face.handle_events([InputEvent("key", key="escape")])
    assert face.card is None and closed[-1] == ("Map", "touch")
    face.set_busy(True)
    face.handle_events([InputEvent("pointer_down", pos=STOP_BUTTON.center)])
    assert stops == [1, 1]  # Stop still works without a card


def test_card_closes_by_itself(display: PygameDisplay) -> None:
    closed: list[tuple[str, str]] = []
    face = Face(display, callbacks=FaceCallbacks(
        on_card_closed=lambda title, why: closed.append((title, why))))
    face.show_card(Card(title="Soon gone", text="x", close_at=time.monotonic() - 1))
    face.tick()
    assert face.card is None and closed == [("Soon gone", "timeout")]


def test_claude_closing_it_is_not_reported_back(display: PygameDisplay) -> None:
    closed: list[tuple[str, str]] = []
    face = Face(display, callbacks=FaceCallbacks(
        on_card_closed=lambda title, why: closed.append((title, why))))
    face.show_card(Card(text="x"))
    assert face.hide_card("claude") and closed == []
    assert face.hide_card("claude") is False


# ----------------------------------------------------------------------- safe downloads


async def public(_host: str) -> list[str]:
    return ["93.184.216.34"]


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/a.png", "http://192.168.1.1/router.png", "http://[::1]/x.png",
    "ftp://example.com/a.png", "file:///etc/passwd", "http://10.0.0.5/cam.jpg",
])
async def test_private_and_odd_addresses_are_refused(url: str) -> None:
    with pytest.raises(ImageError):
        await check_public(url, public)


async def test_names_that_resolve_to_the_home_network_are_refused() -> None:
    async def home(_host: str) -> list[str]:
        return ["192.168.0.10"]

    with pytest.raises(ImageError, match="private network"):
        await check_public("http://printer.local/status.png", home)


def client_for(handler: Any) -> Any:
    return lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_fetches_a_picture() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=png(), headers={"content-type": "image/png"})

    data = await fetch_image("https://example.com/a.png", resolver=public,
                             client_factory=client_for(handler))
    assert decode_image(data).get_size() == (64, 32)


async def test_web_pages_are_not_pictures() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>", headers={"content-type": "text/html"})

    with pytest.raises(ImageError, match="isn't a picture"):
        await fetch_image("https://example.com/page", resolver=public,
                          client_factory=client_for(handler))


async def test_redirects_into_the_home_network_are_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://192.168.1.1/admin.png"})

    with pytest.raises(ImageError, match="private network"):
        await fetch_image("https://example.com/a.png", resolver=public,
                          client_factory=client_for(handler))


async def test_huge_downloads_are_cut_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("cadbot.net.images.MAX_BYTES", 1000)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"\x89PNG" + b"0" * 5000,
                              headers={"content-type": "image/png"})

    with pytest.raises(ImageError, match="too big"):
        await fetch_image("https://example.com/a.png", resolver=public,
                          client_factory=client_for(handler))


def test_broken_and_huge_pictures() -> None:
    with pytest.raises(ImageError):
        decode_image(b"not a picture")
    big = decode_image(png((4000, 1000)))
    assert max(big.get_size()) == 1440  # scaled down for the 720-wide screen


# ----------------------------------------------------------------------- the tools


def card_result(h: AgentHarness) -> dict[str, Any]:
    return h.client.requests[-1]["messages"][-1]["content"][0]


async def test_show_text_then_hide(harness: AgentHarness) -> None:
    harness.client.script = [reply(tool_use("show_card", title="Shopping", text="- milk")),
                             reply()]
    await harness.agent.handle(utterance("put the list on the screen"))
    assert "Shown on the screen" in card_result(harness)["content"]
    card = harness.face.card
    assert card is not None and card.title == "Shopping" and card.close_at is not None
    harness.client.script = [reply(tool_use("hide_card")), reply()]
    await harness.agent.handle(utterance("ok done"))
    assert harness.face.card is None and "Closed" in card_result(harness)["content"]


async def test_show_a_web_picture(harness: AgentHarness,
                                  monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(url: str) -> bytes:
        assert url == "https://upload.example.org/panda.png"
        return png()

    monkeypatch.setattr("cadbot.agent.tools.card.fetch_image", fake_fetch)
    harness.client.script = [reply(tool_use("show_card", title="Red panda",
                                            image_url="https://upload.example.org/panda.png")),
                             reply()]
    await harness.agent.handle(utterance("show me a red panda"))
    card = harness.face.card
    assert card is not None and card.image is not None and card.caption == "upload.example.org"


async def test_bad_picture_is_reported_to_claude(harness: AgentHarness,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(url: str) -> bytes:
        raise ImageError("that link isn't a picture (text/html)")

    monkeypatch.setattr("cadbot.agent.tools.card.fetch_image", fake_fetch)
    harness.client.script = [reply(tool_use("show_card", image_url="https://x.org/page")),
                             reply()]
    await harness.agent.handle(utterance("show me"))
    result = card_result(harness)
    assert result["is_error"] and "isn't a picture" in result["content"]
    assert harness.face.card is None


async def test_camera_photo() -> None:
    h = make_harness(with_vision=True)
    assert h.reader is not None
    h.reader.push(frame())
    h.client.script = [reply(tool_use("show_card", camera_photo=True)), reply()]
    await h.agent.handle(utterance("how do I look?"))
    card = h.face.card
    assert card is not None and card.image is not None and card.image.get_size() == (1280, 720)


async def test_closing_by_touch_is_told_to_claude(harness: AgentHarness) -> None:
    harness.face.callbacks.on_card_closed = lambda title, why: harness.agent.add_note(
        f"[Note: the card \"{title}\" was closed ({why}).]")
    harness.client.script = [reply(tool_use("show_card", title="Recipe", text="eggs")), reply()]
    await harness.agent.handle(utterance("show me the recipe"))
    harness.face.handle_events([InputEvent("pointer_down", pos=DONE_BUTTON.center)])
    harness.client.script = [reply()]
    await harness.agent.handle(utterance("thanks"))
    text = harness.client.requests[-1]["messages"][-1]["content"][-1]["text"]
    assert 'the card "Recipe" was closed (touch)' in text


async def test_card_needs_something_to_show(harness: AgentHarness) -> None:
    harness.client.script = [reply(tool_use("show_card", title="Empty")), reply()]
    await harness.agent.handle(utterance("show"))
    assert card_result(harness)["is_error"] and harness.face.card is None
