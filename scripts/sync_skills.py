#!/usr/bin/env python3
"""Synchronize canonical .agents skills into Claude Code's project path."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Iterable

from path_safety import is_link_like, read_regular_file_bounded, reject_linked_path


MAX_SKILLS = 64
MAX_TARGET_ENTRIES = 128
MAX_FILES_PER_SKILL = 64
MAX_ENTRIES_PER_SKILL = 256
MAX_FILE_BYTES = 1_048_576


def read_bounded_bytes(path: Path) -> bytes:
    candidate = Path(os.path.abspath(path))
    try:
        return read_regular_file_bounded(
            candidate,
            MAX_FILE_BYTES,
            boundary=Path(candidate.anchor),
            label="skill file",
        )
    except (OSError, ValueError) as exc:
        raise ValueError(f"skill file is unsafe or too large: {path.name}") from exc


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def reject_target_links(target: Path, project_root: Path | None = None) -> None:
    """Reject links in the project-owned target chain before resolving that chain."""
    reject_linked_path(target, project_root or target.parent.parent, label="target")


def skill_files(skill: Path) -> list[Path]:
    if is_link_like(skill) or not skill.is_dir():
        raise ValueError(f"symlinked skill is not portable: {skill.name}")
    files: list[Path] = []
    directories = [skill]
    entries_seen = 0
    while directories:
        current = directories.pop()
        names: list[str] = []
        with os.scandir(current) as entries:
            for entry in entries:
                entries_seen += 1
                if entries_seen > MAX_ENTRIES_PER_SKILL:
                    raise ValueError(f"skill entry cap exceeded: {skill.name}")
                names.append(entry.name)
        for name in reversed(sorted(names)):
            path = current / name
            if is_link_like(path):
                raise ValueError(f"symlinked skill entry is not portable: {skill.name}/{name}")
            if path.is_dir():
                directories.append(path)
                continue
            if not path.is_file():
                raise ValueError(f"non-regular skill entry is not portable: {skill.name}/{name}")
            files.append(path)
            if len(files) > MAX_FILES_PER_SKILL:
                raise ValueError(f"skill file cap exceeded: {skill.name}")
            if path.stat().st_size > MAX_FILE_BYTES:
                raise ValueError(f"skill file too large: {skill.name}/{path.name}")
    return sorted(files, key=lambda path: path.relative_to(skill).as_posix())


def tree_digest(skill: Path) -> str:
    digest = hashlib.sha256()
    for path in skill_files(skill):
        relative = path.relative_to(skill).as_posix().encode("utf-8")
        content = read_bounded_bytes(path)
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def canonical_skills(source: Path) -> list[Path]:
    if is_link_like(source):
        raise ValueError(f"canonical skill root is linked: {source}")
    reject_linked_path(source, source.parent.parent, label="canonical source")
    if not source.is_dir():
        raise ValueError(f"canonical skill root is missing: {source}")
    skills: list[Path] = []
    with os.scandir(source) as entries:
        for entry in entries:
            if len(skills) >= MAX_SKILLS:
                raise ValueError(f"skill cap exceeded: more than {MAX_SKILLS}")
            path = source / entry.name
            if is_link_like(path) or not entry.is_dir(follow_symlinks=False):
                raise ValueError(f"canonical skill root contains a non-directory: {entry.name}")
            skills.append(path)
    skills.sort(key=lambda path: path.name)
    for skill in skills:
        if not (skill / "SKILL.md").is_file():
            raise ValueError(f"skill has no SKILL.md: {skill.name}")
    return skills


def target_entries(target: Path, *, create: bool) -> list[Path]:
    """Inventory the generated root without following or resolving the root itself."""
    if is_link_like(target):
        raise ValueError("symlinked target skill root is not portable")
    reject_target_links(target)
    if not target.exists():
        if not create:
            return []
        target.mkdir(parents=True, exist_ok=True)
    if is_link_like(target) or not target.is_dir():
        raise ValueError("target skill root must be a non-symlink directory")

    found: list[Path] = []
    with os.scandir(target) as entries:
        for entry in entries:
            if len(found) >= MAX_TARGET_ENTRIES:
                raise ValueError(f"target entry cap exceeded: more than {MAX_TARGET_ENTRIES}")
            found.append(target / entry.name)
    return sorted(found, key=lambda path: path.name)


def extra_target_names(source_skills: list[Path], entries: list[Path]) -> list[str]:
    expected = {skill.name for skill in source_skills}
    return sorted(entry.name for entry in entries if entry.name not in expected)


def copy_skill(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True)
    for path in skill_files(source):
        relative = path.relative_to(source)
        target = destination / relative
        if not _inside(target, destination):
            raise ValueError(f"unsafe skill file destination: {source.name}/{relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        temporary.write_bytes(read_bounded_bytes(path))
        os.replace(temporary, target)


def manifest(source: Path) -> dict[str, str]:
    return {skill.name: tree_digest(skill) for skill in canonical_skills(source)}


def sync(source: Path, target: Path, *, force: bool) -> list[str]:
    actions: list[str] = []
    skills = canonical_skills(source)
    entries = target_entries(target, create=True)
    actions.extend(f"preserved-extra:{name}" for name in extra_target_names(skills, entries))
    for skill in skills:
        destination = target / skill.name
        if not _inside(destination, target):
            raise ValueError(f"unsafe skill destination: {skill.name}")
        if is_link_like(destination):
            raise ValueError(f"divergent target preserved: {skill.name}")
        replacing = False
        if destination.exists():
            if not destination.is_dir() or tree_digest(destination) != tree_digest(skill):
                if not force:
                    raise ValueError(f"divergent target preserved: {skill.name}")
                replacing = True
            else:
                actions.append(f"unchanged:{skill.name}")
                continue
        source_digest = tree_digest(skill)
        with tempfile.TemporaryDirectory(prefix=f".{skill.name}.stage-", dir=target) as staged_root:
            staged = Path(staged_root) / skill.name
            copy_skill(skill, staged)
            if tree_digest(staged) != source_digest or tree_digest(skill) != source_digest:
                raise ValueError(f"source changed during synchronization: {skill.name}")
            if replacing:
                backup = Path(staged_root) / "previous"
                os.replace(destination, backup)
                try:
                    os.replace(staged, destination)
                except BaseException:
                    os.replace(backup, destination)
                    raise
                shutil.rmtree(backup)
                actions.append(f"replaced:{skill.name}")
            else:
                os.replace(staged, destination)
                actions.append(f"copied:{skill.name}")
    return actions


def check(source: Path, target: Path) -> list[str]:
    errors: list[str] = []
    skills = canonical_skills(source)
    expected = {skill.name: tree_digest(skill) for skill in skills}
    entries = target_entries(target, create=False)
    errors.extend(f"extra:{name}" for name in extra_target_names(skills, entries))
    for name, digest in expected.items():
        destination = target / name
        if not destination.is_dir():
            errors.append(f"missing:{name}")
            continue
        try:
            actual = tree_digest(destination)
        except (OSError, ValueError) as exc:
            errors.append(f"invalid:{name}:{type(exc).__name__}")
            continue
        if actual != digest:
            errors.append(f"drift:{name}")
    return sorted(errors)


def remove(source: Path, target: Path) -> list[str]:
    actions: list[str] = []
    skills = canonical_skills(source)
    entries = target_entries(target, create=False)
    actions.extend(f"preserved-extra:{name}" for name in extra_target_names(skills, entries))
    for skill in skills:
        destination = target / skill.name
        if not destination.exists():
            continue
        if not _inside(destination, target):
            raise ValueError(f"unsafe skill destination: {skill.name}")
        if not destination.is_dir() or tree_digest(destination) != tree_digest(skill):
            raise ValueError(f"divergent target preserved: {skill.name}")
        shutil.rmtree(destination)
        actions.append(f"removed:{skill.name}")
    return actions


def emit(items: Iterable[str], *, as_json: bool, ok: bool = True) -> None:
    ordered = sorted(items)
    if as_json:
        print(json.dumps({"ok": ok, "items": ordered}, sort_keys=True))
    else:
        for item in ordered:
            print(item)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("sync", "check", "manifest", "remove"))
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--source", type=Path)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    root = args.project_root.resolve()
    source = (args.source or root / ".agents" / "skills").absolute()
    target = root / ".claude" / "skills"
    if is_link_like(target):
        print("ERROR: symlinked target skill root is not portable")
        return 2
    try:
        reject_target_links(target, root)
    except ValueError as exc:
        print(f"ERROR: ValueError: {exc}")
        return 2
    if not _inside(target, root):
        print("ERROR: target escapes project root")
        return 2
    try:
        if args.mode == "sync":
            emit(sync(source, target, force=args.force), as_json=args.json)
        elif args.mode == "check":
            errors = check(source, target)
            emit(errors or ["skills-in-sync"], as_json=args.json, ok=not errors)
            return 1 if errors else 0
        elif args.mode == "manifest":
            payload = manifest(source)
            print(json.dumps(payload, indent=None if args.json else 2, sort_keys=True))
        else:
            emit(remove(source, target), as_json=args.json)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
