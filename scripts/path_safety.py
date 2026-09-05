#!/usr/bin/env python3
"""Shared lexical path guards for repository-local setup tools."""

from __future__ import annotations

import os
from pathlib import Path
import stat


def is_link_like(path: Path) -> bool:
    """Detect symbolic links and Windows junction/reparse-point entries."""

    try:
        details = os.lstat(path)
    except FileNotFoundError:
        return False
    attributes = getattr(details, "st_file_attributes", 0)
    reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(details.st_mode) or bool(attributes & reparse_point)


def reject_linked_path(path: Path, boundary: Path, *, label: str) -> None:
    """Reject a path outside its boundary or with a link-like component."""

    candidate = Path(os.path.abspath(path))
    root = Path(os.path.abspath(boundary))
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} escapes its declared root") from exc

    current = root
    if is_link_like(current):
        raise ValueError(f"linked {label} path component: declared root")
    for part in relative.parts:
        current = current / part
        if is_link_like(current):
            raise ValueError(f"linked {label} path component: {part}")


def read_regular_file_bounded(
    path: Path,
    max_bytes: int,
    *,
    boundary: Path | None = None,
    label: str = "file",
) -> bytes:
    """Read one complete regular file without following a checked link-like path."""

    if max_bytes < 0:
        raise ValueError(f"{label} byte cap must be non-negative")
    candidate = Path(os.path.abspath(path))
    root = Path(os.path.abspath(boundary)) if boundary is not None else None
    if root is not None:
        reject_linked_path(candidate, root, label=label)
    if is_link_like(candidate):
        raise ValueError(f"{label} is link-like")

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(candidate, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"{label} is not a regular file")
        if metadata.st_size > max_bytes:
            raise ValueError(f"{label} exceeds {max_bytes} bytes")

        if root is not None:
            reject_linked_path(candidate, root, label=label)
        if is_link_like(candidate):
            raise ValueError(f"{label} changed to a link-like path")
        current = candidate.lstat()
        if (current.st_dev, current.st_ino) != (metadata.st_dev, metadata.st_ino):
            raise ValueError(f"{label} changed while opening")

        chunks: list[bytes] = []
        observed = 0
        while observed <= max_bytes:
            chunk = os.read(descriptor, min(65_536, max_bytes + 1 - observed))
            if not chunk:
                break
            chunks.append(chunk)
            observed += len(chunk)
        content = b"".join(chunks)
        if len(content) > max_bytes:
            raise ValueError(f"{label} grew beyond {max_bytes} bytes")
        return content
    finally:
        os.close(descriptor)
