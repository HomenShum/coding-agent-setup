#!/usr/bin/env python3
"""Validate one portable skill contract and its bounded execution receipt."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

from path_safety import read_regular_file_bounded


MAX_DOCUMENT_BYTES = 65_536
MAX_ITEMS = 16
MAX_TEXT_CHARS = 2_048
MAX_ERRORS = 32
SKILL_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
INPUT_NAME = re.compile(r"[a-z][a-z0-9_]*\Z")
RECEIPT_FIELDS = ("skill", "status", "inputs", "evidence", "verification")
RECEIPT_STATUSES = frozenset({"PASS", "BLOCKED", "UNVERIFIED"})
VERIFICATION_ARGV = (
    "{python}",
    "scripts/validate_skill_receipt.py",
    "--contract",
    "{skill_dir}/references/contract.json",
    "--receipt",
    "{receipt}",
)


def read_object(path: Path) -> dict[str, Any]:
    candidate = Path(os.path.abspath(path))
    data = read_regular_file_bounded(
        candidate,
        MAX_DOCUMENT_BYTES,
        boundary=Path(candidate.anchor),
        label="document",
    )
    value = json.loads(data.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("document root must be an object")
    return value


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= MAX_TEXT_CHARS


def validate_contract(contract: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(contract, dict):
        return ["contract must be an object"]
    if contract.get("version") != 1:
        errors.append("contract version must equal 1")
    skill = contract.get("skill")
    if not isinstance(skill, str) or SKILL_NAME.fullmatch(skill) is None:
        errors.append("contract skill must be a portable skill name")
    for field in ("trigger", "refusal"):
        if not _text(contract.get(field)):
            errors.append(f"contract {field} must be bounded non-empty text")
    inputs = contract.get("inputs")
    if (
        not isinstance(inputs, list)
        or not 1 <= len(inputs) <= MAX_ITEMS
        or any(
            not isinstance(item, str) or INPUT_NAME.fullmatch(item) is None
            for item in inputs
        )
        or len(set(inputs)) != len(inputs)
    ):
        errors.append(
            f"contract inputs must contain 1 to {MAX_ITEMS} unique snake_case names"
        )
    if contract.get("receipt") != list(RECEIPT_FIELDS):
        errors.append("contract receipt must name the canonical five fields")
    verification = contract.get("verification")
    if not isinstance(verification, dict):
        errors.append("contract verification must be an object")
    else:
        if verification.get("argv") != list(VERIFICATION_ARGV):
            errors.append(
                "contract verification argv must include the shared validator, contract, and receipt"
            )
        if verification.get("success") != "exit 0":
            errors.append("contract verification success must equal exit 0")
    return sorted(set(errors))[:MAX_ERRORS]


def validate_receipt(contract: Any, receipt: Any) -> list[str]:
    errors = validate_contract(contract)
    if not isinstance(receipt, dict):
        return sorted(set(errors + ["receipt must be an object"]))[:MAX_ERRORS]
    if set(receipt) != set(RECEIPT_FIELDS):
        errors.append("receipt must contain exactly the canonical five fields")
    if receipt.get("skill") != contract.get("skill"):
        errors.append("receipt skill does not match the contract")
    if receipt.get("status") not in RECEIPT_STATUSES:
        errors.append("receipt status must be PASS, BLOCKED, or UNVERIFIED")
    expected_inputs = contract.get("inputs")
    inputs = receipt.get("inputs")
    if not isinstance(inputs, dict) or not isinstance(expected_inputs, list):
        errors.append("receipt inputs must be an object")
    elif set(inputs) != set(expected_inputs) or any(not _text(value) for value in inputs.values()):
        errors.append("receipt inputs must provide one bounded reference per contract input")
    evidence = receipt.get("evidence")
    if (
        not isinstance(evidence, list)
        or not 1 <= len(evidence) <= MAX_ITEMS
        or any(not _text(item) for item in evidence)
    ):
        errors.append(f"receipt evidence must contain 1 to {MAX_ITEMS} bounded entries")
    if not _text(receipt.get("verification")):
        errors.append("receipt verification must name the replayed proof and result")
    return sorted(set(errors))[:MAX_ERRORS]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    try:
        contract = read_object(args.contract)
        receipt = read_object(args.receipt)
        errors = validate_receipt(contract, receipt)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        errors = [f"cannot validate skill receipt: {type(exc).__name__}: {exc}"]
    for error in errors:
        print(f"ERROR: {error}")
    if errors:
        return 1
    print("PASS: bounded skill receipt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
