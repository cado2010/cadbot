# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Cards: text or a picture on the screen, with the face shrunk into the top-right corner.

Claude decides what to show (the show_card tool); this only lays it out and draws it.
"""

from __future__ import annotations

from dataclasses import dataclass

import pygame

from cadbot.platform.base import LOGICAL_SCREEN

SCREEN_W, SCREEN_H = LOGICAL_SCREEN
MARGIN = 24
MINI_FACE = pygame.Rect(SCREEN_W - MARGIN - 220, MARGIN, 220, 162)
TITLE_AREA = pygame.Rect(MARGIN, MARGIN + 8, MINI_FACE.x - 2 * MARGIN, MINI_FACE.h)
DONE_BUTTON = pygame.Rect(MARGIN, SCREEN_H - MARGIN - 80, 160, 80)
CONTENT_AREA = pygame.Rect(MARGIN, MINI_FACE.bottom + MARGIN, SCREEN_W - 2 * MARGIN,
                           DONE_BUTTON.y - MINI_FACE.bottom - 2 * MARGIN)

TEXT = (232, 236, 244)
DIM = (150, 156, 170)
PANEL = (20, 24, 36)
BUTTON = (60, 120, 200)

BODY_SIZES = (44, 38, 32, 28, 24)
TITLE_SIZES = (52, 44, 38, 32)


@dataclass
class Card:
    title: str = ""
    text: str = ""
    image: pygame.Surface | None = None
    caption: str = ""
    """Small line under a picture, e.g. where it came from."""
    close_at: float | None = None
    """Monotonic time to close it by itself; None keeps it until closed."""


def _font(size: int) -> pygame.font.Font:
    if not pygame.font.get_init():
        pygame.font.init()
    return pygame.font.Font(None, size)


def wrap(font: pygame.font.Font, text: str, width: int) -> list[str]:
    """Word-wrap text to a pixel width. Keeps line breaks; '- ' and '* ' become bullets."""
    lines: list[str] = []
    for paragraph in text.replace("\r", "").split("\n"):
        stripped = paragraph.strip()
        if stripped[:2] in ("- ", "* "):
            stripped = "• " + stripped[2:]
        if not stripped:
            lines.append("")
            continue
        line = ""
        for word in stripped.split(" "):
            candidate = f"{line} {word}".strip()
            if font.size(candidate)[0] <= width or not line:
                line = candidate
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


def _fit_text(text: str, width: int, height: int,
              sizes: tuple[int, ...]) -> tuple[pygame.font.Font, list[str]]:
    """The largest font size at which the text fits; truncated at the smallest if needed."""
    for size in sizes:
        font = _font(size)
        lines = wrap(font, text, width)
        if len(lines) * font.get_linesize() <= height:
            return font, lines
    font = _font(sizes[-1])
    lines = wrap(font, text, width)
    keep = max(1, height // font.get_linesize())
    if len(lines) > keep:
        lines = [*lines[: keep - 1], lines[keep - 1].rstrip(" .,;") + " …"]
    return font, lines


def _blit_lines(surface: pygame.Surface, font: pygame.font.Font, lines: list[str],
                topleft: tuple[int, int], colour: tuple[int, int, int]) -> int:
    x, y = topleft
    for line in lines:
        if line:
            surface.blit(font.render(line, True, colour), (x, y))
        y += font.get_linesize()
    return y


def render_content(card: Card, size: tuple[int, int] = CONTENT_AREA.size) -> pygame.Surface:
    """The card body: the picture (fitted, never stretched) and/or the text."""
    surface = pygame.Surface(size)
    surface.fill(PANEL)
    width, height = size
    pad = 20
    inner_w, top = width - 2 * pad, pad
    text_room = height - 2 * pad
    if card.image is not None:
        image_room = height - 2 * pad if not card.text else int((height - 2 * pad) * 0.62)
        if card.caption:
            image_room -= _font(26).get_linesize()
        iw, ih = card.image.get_size()
        scale = min(inner_w / iw, image_room / ih)
        fitted = pygame.transform.smoothscale(
            card.image, (max(1, int(iw * scale)), max(1, int(ih * scale))))
        surface.blit(fitted, ((width - fitted.get_width()) // 2, top))
        top += fitted.get_height() + 8
        if card.caption:
            caption = _font(26).render(card.caption, True, DIM)
            surface.blit(caption, ((width - caption.get_width()) // 2, top))
            top += _font(26).get_linesize()
        top += 16
        text_room = height - pad - top
    if card.text and text_room > 0:
        font, lines = _fit_text(card.text, inner_w, text_room, BODY_SIZES)
        _blit_lines(surface, font, lines, (pad, top), TEXT)
    return surface


def render_title(title: str, size: tuple[int, int] = TITLE_AREA.size) -> pygame.Surface:
    surface = pygame.Surface(size, pygame.SRCALPHA)
    if title:
        font, lines = _fit_text(title, size[0], size[1], TITLE_SIZES)
        _blit_lines(surface, font, lines, (0, 0), TEXT)
    return surface


def draw_done_button(screen: pygame.Surface) -> None:
    pygame.draw.rect(screen, BUTTON, DONE_BUTTON, border_radius=18)
    label = _font(48).render("Done", True, (255, 255, 255))
    screen.blit(label, label.get_rect(center=DONE_BUTTON.center))
