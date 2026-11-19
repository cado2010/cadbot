# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Download and verify model files. A file is only moved into place after its hash matches."""

from __future__ import annotations

import hashlib
import logging
import ssl
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import httpx
import truststore

from cadbot.models.manifest import MANIFEST, ModelFile

log = logging.getLogger(__name__)

CHUNK = 1 << 20


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(CHUNK):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class FileStatus:
    entry: ModelFile
    path: Path
    state: str  # "ok", "missing", "bad-size", "bad-hash"


def check(models_dir: Path, entries: Iterable[ModelFile] = MANIFEST,
          verify_hash: bool = True) -> list[FileStatus]:
    statuses = []
    for entry in entries:
        path = models_dir / entry.dest
        if not path.is_file():
            state = "missing"
        elif path.stat().st_size != entry.size:
            state = "bad-size"
        elif verify_hash and sha256_of(path) != entry.sha256:
            state = "bad-hash"
        else:
            state = "ok"
        statuses.append(FileStatus(entry, path, state))
    return statuses


def download(entry: ModelFile, dest: Path, client: httpx.Client,
             progress: Callable[[int, int], None] | None = None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    digest = hashlib.sha256()
    done = 0
    with client.stream("GET", entry.url, follow_redirects=True) as response:
        response.raise_for_status()
        with tmp.open("wb") as f:
            for block in response.iter_bytes(CHUNK):
                f.write(block)
                digest.update(block)
                done += len(block)
                if progress:
                    progress(done, entry.size)
    if digest.hexdigest() != entry.sha256:
        tmp.unlink(missing_ok=True)
        raise ValueError(f"hash mismatch for {entry.dest}: got {digest.hexdigest()}")
    tmp.replace(dest)


def ensure(models_dir: Path, entries: Iterable[ModelFile] = MANIFEST,
           progress: Callable[[ModelFile, int, int], None] | None = None) -> list[FileStatus]:
    """Download whatever is missing or damaged. Returns the final status of every file."""
    entries = list(entries)
    todo = [s for s in check(models_dir, entries) if s.state != "ok"]
    if todo:
        context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)  # honours the OS trust store
        with httpx.Client(verify=context, timeout=httpx.Timeout(30.0, read=120.0)) as client:
            for status in todo:
                log.info("downloading %s (%s)", status.entry.dest, status.state)
                callback = None
                if progress is not None:
                    entry = status.entry

                    def callback(done: int, total: int, entry: ModelFile = entry) -> None:
                        progress(entry, done, total)

                download(status.entry, status.path, client, callback)
    return check(models_dir, entries)
