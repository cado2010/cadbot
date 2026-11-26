# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Download a picture for a card, carefully.

Only public internet addresses (never the home network: a web page must not be able to point
cadbot at the router or other devices), only real image types, a size cap, and a few redirects
at most, each checked again. Only the picture is used; nothing is sent back to Claude.
"""

from __future__ import annotations

import asyncio
import io
import ipaddress
import logging
import socket
import ssl
from collections.abc import Awaitable, Callable
from urllib.parse import urljoin, urlsplit

import httpx
import pygame
import truststore

from cadbot import __version__

log = logging.getLogger(__name__)

MAX_BYTES = 8 * 1024 * 1024
MAX_REDIRECTS = 3
MAX_SIDE = 1440  # downscale bigger pictures: the screen is 720 wide
IMAGE_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/gif", "image/webp", "image/bmp"}

Resolver = Callable[[str], Awaitable[list[str]]]


class ImageError(Exception):
    """A picture that can't or mustn't be shown; the message is safe to give to Claude."""


async def resolve(host: str) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


async def check_public(url: str, resolver: Resolver = resolve) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ImageError("only http(s) links to pictures can be shown")
    try:
        addresses = [parts.hostname] if _is_ip(parts.hostname) else await resolver(parts.hostname)
    except OSError as exc:
        raise ImageError(f"couldn't find {parts.hostname}") from exc
    if not addresses:
        raise ImageError(f"couldn't find {parts.hostname}")
    for address in addresses:
        if not ipaddress.ip_address(address.split("%")[0]).is_global:
            raise ImageError("that address is on a private network; only public pictures")


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _client() -> httpx.AsyncClient:
    context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    return httpx.AsyncClient(verify=context, timeout=httpx.Timeout(10.0, read=20.0),
                             follow_redirects=False,
                             headers={"User-Agent": f"cadbot/{__version__} (home assistant)"})


async def fetch_image(url: str, *, resolver: Resolver = resolve,
                      client_factory: Callable[[], httpx.AsyncClient] = _client) -> bytes:
    """The picture's bytes, or ImageError with a reason Claude can pass on."""
    async with client_factory() as client:
        for _ in range(MAX_REDIRECTS + 1):
            await check_public(url, resolver)
            async with client.stream("GET", url) as response:
                if response.is_redirect and "location" in response.headers:
                    url = urljoin(url, response.headers["location"])
                    continue
                if response.status_code != 200:
                    raise ImageError(f"the picture didn't load (HTTP {response.status_code})")
                kind = response.headers.get("content-type", "").split(";")[0].strip().lower()
                if kind not in IMAGE_TYPES:
                    raise ImageError(f"that link isn't a picture ({kind or 'unknown type'}); "
                                     "find a direct link to a .jpg, .png, .gif or .webp file")
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_BYTES:
                        raise ImageError("that picture is too big (over 8 MB)")
                return bytes(data)
    raise ImageError("too many redirects")


def decode_image(data: bytes) -> pygame.Surface:
    """Bytes to a picture, scaled down if it's huge. Blocking: run it in a thread."""
    try:
        image = pygame.image.load(io.BytesIO(data))
    except (pygame.error, ValueError) as exc:
        raise ImageError("the picture couldn't be read") from exc
    w, h = image.get_size()
    if w < 1 or h < 1:
        raise ImageError("the picture is empty")
    rgba = pygame.Surface((w, h), pygame.SRCALPHA, 32)  # any format (GIF palettes...) -> 32-bit
    rgba.blit(image, (0, 0))
    scale = min(1.0, MAX_SIDE / max(w, h))
    if scale < 1.0:
        rgba = pygame.transform.smoothscale(rgba, (max(1, int(w * scale)),
                                                   max(1, int(h * scale))))
    return rgba
