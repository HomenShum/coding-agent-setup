#!/usr/bin/env python3
"""Validate bounded LOOP/GRAPH state without third-party packages."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import sys
from typing import Any

from path_safety import is_link_like, read_regular_file_bounded


MAX_STATE_BYTES = 65_536
MAX_ERRORS = 64
MAX_STEPS = 12
MAX_WORKERS = 5
MAX_RECEIPTS = 64
MAX_EVENT_ID_CHARS = 64
MAX_HANDOFF_CHARS = 256
MAX_HANDOFF_BYTES = 65_536
NODES = frozenset({"human", "planner", "worker", "gate", "judge", "recovery"})
DISPOSITIONS = frozenset({"PASS", "REVISE", "REPLAN", "HITL", "BLOCKED"})
WHY_GRAPH = frozenset(
    {
        "distinct-specialties",
        "fan-out-fan-in",
        "different-toolsets",
        "auditable-routing",
        "isolated-failure",
        "dedicated-reviewer",
    }
)
STATE_FIELDS = frozenset(
    {
        "version",
        "mode",
        "why_graph",
        "caps",
        "current",
        "path",
        "events",
        "receipts",
        "disposition",
        "delivered",
    }
)
CAP_FIELDS = frozenset({"steps", "workers", "receipts"})
RECEIPT_FIELDS = frozenset({"claim", "worker", "certainty", "evidence"})
EVENT_FIELDS = frozenset({"type", "from", "to", "handoff", "handoff_sha256"})
EVENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
SHA256_HEX = re.compile(r"[0-9A-Fa-f]{64}\Z")
SENSITIVE_HANDOFF_PARTS = frozenset(
    {
        ".agent-local",
        ".claude",
        ".codex",
        ".cursor",
        ".env",
        ".git",
        ".venv",
        "node_modules",
        "secret",
        "secrets",
    }
)
ALLOWED_TRANSITIONS = {
    "LOOP": frozenset(
        {
            ("human", "planner"),
            ("planner", "gate"),
            ("planner", "recovery"),
            ("gate", "planner"),
            ("gate", "recovery"),
            ("gate", "human"),
            ("recovery", "planner"),
        }
    ),
    "GRAPH": frozenset(
        {
            ("human", "planner"),
            ("planner", "worker"),
            ("worker", "planner"),
            ("planner", "gate"),
            ("gate", "planner"),
            ("gate", "judge"),
            ("judge", "planner"),
            ("judge", "human"),
            ("planner", "recovery"),
            ("worker", "recovery"),
            ("gate", "recovery"),
            ("judge", "recovery"),
            ("recovery", "planner"),
        }
    ),
}


def _error(errors: list[str], message: str) -> None:
    if len(errors) < MAX_ERRORS:
        errors.append(message)


def _contains_ordered_stages(path: list[str], stages: tuple[str, ...]) -> bool:
    """Return whether each required stage occurs in order, allowing repair loops."""
    next_stage = 0
    for node in path:
        if next_stage < len(stages) and node == stages[next_stage]:
            next_stage += 1
    return next_stage == len(stages)


def validate_state(state: Any, project_root: Path | None = None) -> list[str]:
    errors: list[str] = []
    if not isinstance(state, dict):
        return ["state must be a JSON object"]

    missing_state_fields = sorted(STATE_FIELDS - state.keys())
    extra_state_fields = sorted(state.keys() - STATE_FIELDS)
    if missing_state_fields:
        _error(errors, f"state missing fields: {', '.join(missing_state_fields)}")
    if extra_state_fields:
        _error(errors, f"state has unknown fields: {', '.join(extra_state_fields)}")

    if state.get("version") != 1:
        _error(errors, "version must equal 1")
    mode = state.get("mode")
    if mode not in {"LOOP", "GRAPH"}:
        _error(errors, "mode must be LOOP or GRAPH")

    caps = state.get("caps")
    if not isinstance(caps, dict):
        _error(errors, "caps must be an object")
        caps = {}
    else:
        missing_caps = sorted(CAP_FIELDS - caps.keys())
        extra_caps = sorted(caps.keys() - CAP_FIELDS)
        if missing_caps:
            _error(errors, f"caps missing fields: {', '.join(missing_caps)}")
        if extra_caps:
            _error(errors, f"caps has unknown fields: {', '.join(extra_caps)}")
    cap_limits = {"steps": MAX_STEPS, "workers": MAX_WORKERS, "receipts": MAX_RECEIPTS}
    for key, maximum in cap_limits.items():
        value = caps.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1 or value > maximum:
            _error(errors, f"caps.{key} must be an integer from 1 to {maximum}")

    why_graph = state.get("why_graph")
    if not isinstance(why_graph, list) or any(not isinstance(item, str) for item in why_graph):
        _error(errors, "why_graph must be a string array")
        why_graph = []
    invalid_reasons = sorted(set(why_graph) - WHY_GRAPH)
    if invalid_reasons:
        _error(errors, f"unknown why_graph reasons: {', '.join(invalid_reasons)}")
    if mode == "GRAPH" and len(set(why_graph)) < 2:
        _error(errors, "GRAPH requires at least two distinct why_graph reasons")
    if mode == "LOOP" and why_graph:
        _error(errors, "LOOP must not carry why_graph reasons")

    path = state.get("path")
    if not isinstance(path, list) or not path:
        _error(errors, "path must be a non-empty array")
        path = []
    elif any(not isinstance(node, str) or node not in NODES for node in path):
        _error(errors, "path contains an unknown node")
        path = []
    step_cap = caps.get("steps", MAX_STEPS)
    if isinstance(step_cap, int) and len(path) - 1 > step_cap:
        _error(errors, "path exceeds the configured step cap")
    current = state.get("current")
    if not isinstance(current, str) or current not in NODES:
        _error(errors, "current must be a known node")
    if path and current != path[-1]:
        _error(errors, "current must equal the last path node")
    if path and path[0] != "human":
        _error(errors, "path must start at human")
    if path and "human" in path[1:-1]:
        _error(errors, "human may appear only at route boundaries")
    if mode in ALLOWED_TRANSITIONS:
        for index, edge in enumerate(zip(path, path[1:])):
            if edge not in ALLOWED_TRANSITIONS[mode]:
                _error(errors, f"{mode} forbids transition {edge[0]} -> {edge[1]}")
            if (
                mode == "GRAPH"
                and edge in {("planner", "gate"), ("gate", "judge")}
                and "worker" not in path[: index + 1]
            ):
                _error(errors, f"GRAPH {edge[1]} requires an earlier worker stage")

    receipts = state.get("receipts")
    if not isinstance(receipts, list):
        _error(errors, "receipts must be an array")
        receipts = []
    receipt_cap = caps.get("receipts", MAX_RECEIPTS)
    if isinstance(receipt_cap, int) and len(receipts) > receipt_cap:
        _error(errors, "receipts exceed the configured cap")
    worker_ids: set[str] = set()
    receipt_keys: set[tuple[str, str]] = set()
    evidenced_worker_receipts = 0
    for index, receipt in enumerate(receipts):
        if not isinstance(receipt, dict):
            _error(errors, f"receipt {index} must be an object")
            continue
        missing = sorted(RECEIPT_FIELDS - receipt.keys())
        extra = sorted(receipt.keys() - RECEIPT_FIELDS)
        if missing:
            _error(errors, f"receipt {index} missing: {', '.join(missing)}")
        if extra:
            _error(errors, f"receipt {index} has unknown fields: {', '.join(extra)}")
        if missing:
            continue
        if not all(
            isinstance(receipt[key], str) and receipt[key].strip()
            for key in RECEIPT_FIELDS
        ):
            _error(errors, f"receipt {index} fields must be non-empty strings")
            continue
        if receipt["certainty"] not in {"MEASURED", "INFERRED", "UNVERIFIED"}:
            _error(errors, f"receipt {index} has invalid certainty")
        elif receipt["certainty"] in {"MEASURED", "INFERRED"}:
            evidenced_worker_receipts += 1
        worker_ids.add(receipt["worker"])
        key = (receipt["claim"], receipt["worker"])
        if key in receipt_keys:
            _error(errors, f"duplicate receipt for {key[0]} from {key[1]}")
        receipt_keys.add(key)
    worker_cap = caps.get("workers", MAX_WORKERS)
    if isinstance(worker_cap, int) and len(worker_ids) > worker_cap:
        _error(errors, "distinct receipt workers exceed the configured cap")

    events = state.get("events")
    if not isinstance(events, list) or len(events) > MAX_RECEIPTS:
        _error(errors, f"events must be an array with at most {MAX_RECEIPTS} items")
        events = []
    event_root: Path | None = None
    if events:
        if project_root is None:
            _error(errors, "eventful state requires an explicit project root")
        else:
            event_root = Path(os.path.abspath(project_root))
            if not event_root.is_dir() or is_link_like(event_root):
                _error(errors, "project root must be an existing non-link directory")
                event_root = None
    observed_handoff_paths: set[str] = set()
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            _error(errors, f"event {index} must be an object")
            continue
        missing = sorted(EVENT_FIELDS - event.keys())
        extra = sorted(event.keys() - EVENT_FIELDS)
        if missing:
            _error(errors, f"event {index} missing: {', '.join(missing)}")
        if extra:
            _error(errors, f"event {index} has unknown fields: {', '.join(extra)}")
        if missing:
            continue
        if event.get("type") != "host-switch":
            _error(errors, f"event {index} type must equal host-switch")
        source = event.get("from")
        destination = event.get("to")
        for field, value in (("from", source), ("to", destination)):
            if not isinstance(value, str) or EVENT_ID.fullmatch(value) is None:
                _error(
                    errors,
                    f"event {index} {field} must be a bounded non-empty host identifier",
                )
        if isinstance(source, str) and isinstance(destination, str) and source == destination:
            _error(errors, f"event {index} must switch between different hosts")
        handoff = event.get("handoff")
        handoff_sha256 = event.get("handoff_sha256")
        digest_is_valid = (
            isinstance(handoff_sha256, str)
            and SHA256_HEX.fullmatch(handoff_sha256) is not None
        )
        if not digest_is_valid:
            _error(errors, f"event {index} handoff_sha256 must be a 64-hex SHA-256")
        if not isinstance(handoff, str) or not handoff or len(handoff) > MAX_HANDOFF_CHARS:
            _error(errors, f"event {index} handoff must be a bounded repository-relative path")
            continue
        if "\\" in handoff:
            _error(errors, f"event {index} handoff must use repository-relative POSIX syntax")
            continue
        handoff_path = PurePosixPath(handoff)
        lowered_parts = tuple(part.lower() for part in handoff_path.parts)
        if (
            handoff_path.is_absolute()
            or not handoff_path.parts
            or any(part in {"", ".", ".."} for part in handoff_path.parts)
            or any(part in SENSITIVE_HANDOFF_PARTS for part in lowered_parts)
            or len(handoff_path.parts) != 3
            or handoff_path.parts[0] != "handoffs"
            or re.fullmatch(r"[0-9]{4}", handoff_path.parts[1]) is None
            or handoff_path.name != "HANDOFF.md"
        ):
            _error(
                errors,
                f"event {index} handoff must reference an immutable handoffs/NNNN/HANDOFF.md snapshot",
            )
            continue
        normalized_handoff = handoff_path.as_posix().lower()
        if normalized_handoff in observed_handoff_paths:
            _error(
                errors,
                f"event {index} handoff must be an immutable per-switch snapshot",
            )
            continue
        observed_handoff_paths.add(normalized_handoff)
        if event_root is not None and digest_is_valid:
            handoff_file = event_root.joinpath(*handoff_path.parts)
            try:
                content = read_regular_file_bounded(
                    handoff_file,
                    MAX_HANDOFF_BYTES,
                    boundary=event_root,
                    label=f"event {index} handoff",
                )
            except (OSError, ValueError) as exc:
                _error(
                    errors,
                    f"event {index} handoff cannot be verified: {type(exc).__name__}: {exc}",
                )
            else:
                observed_sha256 = hashlib.sha256(content).hexdigest()
                if observed_sha256 != handoff_sha256.lower():
                    _error(errors, f"event {index} handoff_sha256 does not match current content")

    disposition = state.get("disposition")
    if disposition not in DISPOSITIONS:
        _error(errors, "disposition is invalid")
    delivered = state.get("delivered")
    if not isinstance(delivered, bool):
        _error(errors, "delivered must be boolean")
    elif delivered:
        if disposition != "PASS":
            _error(errors, "only PASS may be delivered")
        if current != "human":
            _error(errors, "delivered state must end at human")
        if mode == "LOOP" and not _contains_ordered_stages(
            path, ("human", "planner", "gate", "human")
        ):
            _error(errors, "LOOP delivery requires human -> planner -> gate -> human")
        if mode == "GRAPH":
            if not _contains_ordered_stages(
                path, ("human", "planner", "worker", "planner", "gate", "judge", "human")
            ):
                _error(
                    errors,
                    "GRAPH delivery requires human -> planner -> worker -> planner -> gate -> judge -> human",
                )
            if evidenced_worker_receipts < 1:
                _error(errors, "GRAPH delivery requires at least one evidenced worker receipt")
    else:
        if disposition == "PASS":
            _error(errors, "PASS disposition must be delivered")
        if len(path) > 1 and path[-1] == "human":
            _error(errors, "a completed route ending at human must be marked delivered")

    return sorted(set(errors))


def load_state(path: Path) -> Any:
    candidate = Path(os.path.abspath(path))
    if is_link_like(candidate):
        raise ValueError("state must be a regular non-symlink file")
    data = read_regular_file_bounded(
        candidate,
        MAX_STATE_BYTES,
        boundary=Path(candidate.anchor),
        label="state",
    )
    return json.loads(data.decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state", type=Path)
    parser.add_argument(
        "--project-root",
        type=Path,
        help="explicit repository root used to verify event handoff receipts",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        state = load_state(args.state)
        errors = validate_state(state, args.project_root)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        errors = [f"cannot load state: {type(exc).__name__}: {exc}"]
    payload = {"ok": not errors, "errors": errors}
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    elif errors:
        for error in errors:
            print(f"ERROR: {error}")
    else:
        print("PASS: bounded agent state")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
