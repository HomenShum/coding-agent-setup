#!/usr/bin/env python3
"""Outcome contracts, bounded append-only records and derived review views.

Local evidence integrity is not authenticated approval or permission to activate.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from bootstrap_learning import pairs, read, wording
from path_safety import read_regular_file_bounded, reject_linked_path

ROUTES = {
    "FEATURE_REQUESTED": ["profile", "curate", "baseline", "implement", "evaluate", "human-review"],
    "JUDGE_CHANGED": ["seal-evaluator", "rescore-frozen-outputs", "calibrate", "human-review"],
    "PIPELINE_CHANGED": ["seal-envelope", "affected-execution", "regression"],
    "CORPUS_CHANGED": ["seal-corpus", "freshness", "affected-retrieval"],
    "RETRIEVER_CHANGED": ["seal-retriever", "component-ablation", "end-to-end-regression"],
    "ANNOTATION_ADDED": ["seal-dataset", "calibrate", "baseline-and-candidate"],
    "GATE_FAILED": ["inspect-case-trace-source", "bounded-repair", "reverify"],
    "SPEC_CHANGED": ["impact-analysis", "affected-cases", "human-review"],
    "HOST_SWITCH": ["verify-handoff", "preserve-failures-budget-approvals", "resume"],
    "DEPLOYMENT_CHANGED": ["profile-enterprise-deployment", "data-boundary-proof", "human-review"],
    "DOCUMENTATION_CHANGED": ["verify-documentation-only", "links-and-contracts"],
}
MODES = {"DETERMINISTIC_RETRIEVAL", "AGENTIC_SEARCH", "WORKFLOW_CHAIN", "DURABLE_JOB", "SANDBOX_MULTI_TURN"}
ENVELOPE_FIELDS = {"code", "model", "prompt", "tools", "retriever", "corpus", "dataset", "rubric", "runtime", "deployment_profile"}
EVENTS = {"RUN_INITIALIZED", "BASELINE_CAPTURED", "CONTEXT_REFRESHED", "HYPOTHESIS_RECORDED", "CANDIDATE_CREATED", "GATE_FAILED", "GATE_PASSED", "REPAIR_APPLIED", "EVAL_COMPLETED", "REVIEW_REQUESTED", "REVIEW_RECORDED", "TARGET_AMENDED", "HOST_SWITCH", "CANDIDATE_REJECTED", "CANDIDATE_ELIGIBLE"}
MAX_EVENTS = 500


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def strings(value, label, maximum=100):
    if not isinstance(value, list) or not 1 <= len(value) <= maximum or not all(map(wording, value)) or len(set(value)) != len(value):
        raise ValueError(f"{label} requires a bounded unique nonempty string list")


def validate_contract(contract):
    if not isinstance(contract, dict) or contract.get("version") != 1 or contract.get("state") not in {"DISCOVERY", "READY"}:
        raise ValueError("invalid outcome contract version/state")
    for field in ("experiment", "goal", "target_state", "expected_improvement", "next_action", "review_owner"):
        if not wording(contract.get(field)):
            raise ValueError(f"missing {field}")
    if contract.get("trigger") not in ROUTES or contract.get("pipeline_mode") not in MODES:
        raise ValueError("unknown trigger or pipeline mode")
    for field in ("current", "candidate"):
        envelope = contract.get(field)
        if not isinstance(envelope, dict) or set(envelope) != ENVELOPE_FIELDS or not all(map(wording, envelope.values())):
            raise ValueError(f"{field} must pin every version envelope field")
    for field in ("case_ids", "invariants", "stop_criteria", "forbidden_actions", "required_approvals"):
        strings(contract.get(field), field)
    if type(contract.get("max_attempts")) is not int or not 1 <= contract["max_attempts"] <= 3:
        raise ValueError("max_attempts must be 1 through 3")
    if type(contract.get("timeout_seconds")) is not int or not 1 <= contract["timeout_seconds"] <= 14400:
        raise ValueError("timeout_seconds must be bounded")
    if contract["state"] == "READY":
        if any(v in {"UNMEASURED", "UNRESOLVED"} for f in ("current", "candidate") for v in contract[f].values()):
            raise ValueError("unresolved envelope must stay in DISCOVERY")
        if contract["current"] == contract["candidate"]:
            raise ValueError("candidate must change a declared component")
    return {"status": "DISCOVERY" if contract["state"] == "DISCOVERY" else "CONTRACT_VALID", "contract_sha256": digest(contract), "workflow": ROUTES[contract["trigger"]], "activation_authority": False}


def validate_event(event):
    if not isinstance(event, dict) or event.get("type") not in EVENTS:
        raise ValueError("unsupported event")
    for key in ("actor", "summary", "next_action"):
        if not wording(event.get(key)):
            raise ValueError(f"event requires {key}")
    for key in ("failed_gates", "evidence"):
        value = event.get(key)
        if not isinstance(value, list) or len(value) > 100 or not all(map(wording, value)):
            raise ValueError(f"invalid event {key}")
    # Receipt references are displayed as data; never executed or auto-fetched.
    if event["type"] == "GATE_FAILED" and not event["failed_gates"]:
        raise ValueError("failed event needs failed gate IDs")
    if event["type"] == "GATE_PASSED" and (not event["failed_gates"] or not event["evidence"]):
        raise ValueError("passing event needs gate IDs and replayable evidence references")


def history(path):
    if not path.exists():
        return []
    raw = read_regular_file_bounded(path, 4_000_000)
    if raw and not raw.endswith(b"\n"):
        raise ValueError("incomplete ledger tail; preserve for recovery")
    lines = raw.splitlines()
    if len(lines) > MAX_EVENTS:
        raise ValueError("ledger event limit exceeded")
    records, previous = [], "0" * 64
    for line in lines:
        record = json.loads(line, object_pairs_hook=pairs, parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
        body = record["body"]
        if body["sequence"] != len(records) or body["previous"] != previous or digest(body) != record["sha256"]:
            raise ValueError("ledger sequence or hash mismatch")
        if len(records) == 0:
            validate_contract(body["contract"])
        else:
            validate_event(body["event"])
        if records and body["contract_sha256"] != records[0]["body"]["contract_sha256"]:
            raise ValueError("contract changed without a new experiment")
        if not records and digest(body["contract"]) != body["contract_sha256"]:
            raise ValueError("contract hash mismatch")
        records.append(record)
        previous = record["sha256"]
    return records


def append(path, *, contract=None, event=None, expected_head=None):
    path = path.absolute()
    reject_linked_path(path, Path(path.anchor), label="outcome ledger")
    if not path.parent.is_dir():
        raise ValueError("ledger parent must already exist")
    lock = path.with_name(path.name + ".lock")
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        records = history(path)
        if len(records) >= MAX_EVENTS:
            raise ValueError("ledger is full; archive explicitly, never evict evidence")
        if contract is not None:
            validate_contract(contract)
            if path.exists():
                raise ValueError("refusing to overwrite existing outcome ledger")
            body = {"contract": contract, "contract_sha256": digest(contract)}
        else:
            validate_event(event)
            if not records or expected_head != records[-1]["sha256"]:
                raise ValueError("stale or missing expected ledger head")
            if event["type"] == "CANDIDATE_CREATED":
                attempts = sum(r["body"].get("event", {}).get("type") == "CANDIDATE_CREATED" for r in records)
                if attempts >= records[0]["body"]["contract"]["max_attempts"]:
                    raise ValueError("candidate attempt budget exhausted; host switches do not reset it")
            body = {"event": event, "contract_sha256": records[0]["body"]["contract_sha256"]}
        body.update(sequence=len(records), previous=records[-1]["sha256"] if records else "0" * 64, recorded_at=datetime.now(timezone.utc).isoformat())
        record = {"body": body, "sha256": digest(body)}
        content = encoded(record) + b"\n"
        if len(content) > 64000 or (path.stat().st_size if path.exists() else 0) + len(content) > 4_000_000:
            raise ValueError("bounded ledger size exceeded")
        reject_linked_path(path, path.parent, label="outcome ledger")
        with path.open("ab") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        return record
    finally:
        os.close(descriptor)
        lock.unlink()


def review(records):
    if not records:
        raise ValueError("no initialized outcome")
    contract = records[0]["body"]["contract"]
    lines = [f"Experiment: {contract['experiment']}", f"Goal: {contract['goal']}", f"Target: {contract['target_state']}", f"State: {contract['state']}", f"Current: {digest(contract['current'])}", f"Candidate: {digest(contract['candidate'])}", f"Cases: {', '.join(contract['case_ids'])}", f"Expected: {contract['expected_improvement']}", f"Required approvals: {', '.join(contract['required_approvals'])}", f"Attempt cap: {contract['max_attempts']}; budget: {contract['timeout_seconds']} seconds", "Evidence and actor references are assertions pending independent replay."]
    # A handoff cannot erase an earlier failure by supplying an empty list.
    failures = set()
    for record in records[1:]:
        event = record["body"]["event"]
        if event["type"] == "GATE_PASSED":
            failures.difference_update(event["failed_gates"])
        else:
            failures.update(event["failed_gates"])
        lines.extend([f"{record['body']['sequence']} {event['type']}: {event['summary']}", f"  Evidence: {', '.join(event['evidence']) or 'UNAVAILABLE'}", f"  Next: {event['next_action']}"])
    lines.extend([f"Open failures: {', '.join(sorted(failures)) or 'none recorded (not proof of success)'}", "Activation: NOT AUTHORIZED by this local record", f"Head: {records[-1]['sha256']}"])
    return "\n".join(lines) + "\n"


def trajectory(receipt):
    rounds = receipt.get("rounds")
    positives = receipt.get("positive_document_ids")
    strings(positives, "positive_document_ids")
    if not isinstance(rounds, list) or not 1 <= len(rounds) <= 100:
        raise ValueError("trajectory needs 1 through 100 search observations")
    seen, queries, repeated, complete = set(), set(), 0, True
    for index, item in enumerate(rounds):
        for field in ("query", "query_origin", "retriever", "corpus_snapshot", "trace", "stop_reason"):
            if not wording(item.get(field)):
                raise ValueError(f"round {index} requires {field}")
        if type(item.get("complete")) is not bool:
            raise ValueError("completeness must be explicit")
        complete = complete and item["complete"]
        docs = item.get("document_ids")
        if not isinstance(docs, list) or len(docs) > 100 or not all(map(wording, docs)):
            raise ValueError("invalid bounded result IDs")
        query = " ".join(item["query"].casefold().split())
        repeated += int(query in queries)
        queries.add(query)
        seen.update(docs)
    return {"status": "MEASURED" if complete else "INCOMPLETE", "search_calls": len(rounds), "repeated_exact_queries": repeated, "unique_documents": len(seen), "positive_document_recall": len(seen.intersection(positives)) / len(positives), "source_support": "REQUIRES_REVIEW", "semantic_repetition": "NOT_MEASURED"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "init", "append", "render", "route", "trajectory"))
    parser.add_argument("--input", type=Path)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--expected-head")
    parser.add_argument("--trigger", choices=sorted(ROUTES))
    parser.add_argument("--format", choices=("ascii", "html"), default="ascii")
    args = parser.parse_args()
    try:
        if args.command == "route":
            result = {"trigger": args.trigger, "workflow": ROUTES[args.trigger], "execution": "explicit agent action required"}
        elif args.command == "render":
            content = review(history(args.ledger))
            print(content if args.format == "ascii" else '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Outcome review</title><style>body{font:16px/1.6 system-ui;max-width:80ch;margin:2rem auto;padding:1rem}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style><h1>Outcome review</h1><pre>' + html.escape(content) + '</pre></html>')
            return 0
        else:
            data = read(args.input)
            if args.command == "check":
                result = validate_contract(data)
            elif args.command == "trajectory":
                result = trajectory(data)
            else:
                result = append(args.ledger, contract=data) if args.command == "init" else append(args.ledger, event=data, expected_head=args.expected_head)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, OSError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        print(json.dumps({"status": "NO_GATE", "reason": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
