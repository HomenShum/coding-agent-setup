#!/usr/bin/env python3
"""Bounded local scaffold and numerical harness comparison; no activation authority."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import tempfile

from path_safety import read_regular_file_bounded, reject_linked_path

ROOT = Path(__file__).resolve().parents[1]


def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def read(path):
    return json.loads(read_regular_file_bounded(path, 2_000_000),
                      object_pairs_hook=pairs,
                      parse_constant=lambda value: fail("nonfinite JSON"))


def fail(message):
    raise ValueError(message)


def wording(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 4000


def policy_at(bundle):
    policy = read(bundle / "policy.json")
    if policy.get("version") != 1 or policy.get("activation") != "distinct-human-review":
        fail("unsupported policy")
    for field in ("gates", "dimensions"):
        if not isinstance(policy.get(field), dict) or not 1 <= len(policy[field]) <= 30:
            fail("missing or oversized criteria")
    for gate in policy["gates"].values():
        if not isinstance(gate, dict) or set(gate) != {"question", "pass", "fail"} or not all(map(wording, gate.values())):
            fail("gates need question, pass and fail wording")
    for anchors in policy["dimensions"].values():
        if not isinstance(anchors, dict) or set(anchors) != set("12345") or not all(map(wording, anchors.values())):
            fail("dimensions need five descriptive anchors")
    return policy


def validate_run(run, policy):
    identity = run.get("identity")
    if not isinstance(identity, dict) or set(identity) != {"dataset", "rubric", "model", "evaluator"} or not all(map(wording, identity.values())):
        fail("complete versioned identity required")
    if not wording(run.get("harness")) or type(run.get("synthetic")) is not bool:
        fail("harness identity and explicit synthetic flag required")
    cases = run.get("cases")
    if not isinstance(cases, list) or not 2 <= len(cases) <= 1000:
        fail("run must contain 2 through 1000 cases")
    indexed, groups = {}, {}
    for case in cases:
        if not isinstance(case, dict) or not all(wording(case.get(k)) for k in ("id", "group", "trace")):
            fail("case requires id, group and trace receipt")
        if case["id"] in indexed or case.get("status") != "ok":
            fail("duplicate case or failed execution; infrastructure errors are not grades")
        split = case.get("split")
        if split not in ("visible", "heldout") or groups.get(case["group"], split) != split:
            fail("invalid split or cross-split group leakage")
        groups[case["group"]] = split
        for field, definitions in (("gates", policy["gates"]), ("scores", policy["dimensions"])):
            grades = case.get(field)
            if not isinstance(grades, dict) or set(grades) != set(definitions):
                fail("exact criteria coverage required")
            for grade in grades.values():
                if not isinstance(grade, dict) or not wording(grade.get("rationale")):
                    fail("every grade requires a rationale")
                value = grade.get("value")
                if field == "gates" and type(value) is not bool:
                    fail("boolean gate required")
                if field == "scores" and (type(value) is not int or not 1 <= value <= 5):
                    fail("ordinal grade must be an integer 1 through 5")
        indexed[case["id"]] = case
    if {c["split"] for c in cases} != {"visible", "heldout"}:
        fail("both splits required")
    return indexed


def compare(policy, baseline, candidate):
    left, right = validate_run(baseline, policy), validate_run(candidate, policy)
    if baseline["identity"] != candidate["identity"] or baseline["synthetic"] != candidate["synthetic"] or set(left) != set(right):
        fail("incompatible identities or case coverage")
    for key in left:
        if any(left[key][field] != right[key][field] for field in ("split", "group")):
            fail("case assignment changed")
    verdict = "NO_CHANGE"
    if any(not g["value"] for c in right.values() for g in c["gates"].values()):
        verdict = "REJECT"
    else:
        deltas = [sum(right[k]["scores"][dimension]["value"] - left[k]["scores"][dimension]["value"]
                      for k in left if left[k]["split"] == split)
                  for split in ("visible", "heldout") for dimension in policy["dimensions"]]
        verdict = "REJECT" if min(deltas) < 0 else "NUMERICALLY_ELIGIBLE" if max(deltas) > 0 else "NO_CHANGE"
    return {"verdict": verdict, "synthetic": candidate["synthetic"], "activated": False,
            "unverified": ["judge calibration", "source authenticity", "heldout isolation", "human acceptance", "UI and hosted trace proof"]}


def initialize(target):
    target = target.absolute()
    reject_linked_path(target, Path(target.anchor), label="target")
    if not target.is_dir():
        fail("target must be an existing directory")
    destination = target / "evals" / "learning"
    reject_linked_path(destination, target, label="learning destination")
    if destination.exists():
        fail("learning destination already exists; refusing overwrite")
    destination.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".learning-", dir=destination.parent) as temporary:
        staging = Path(temporary) / "bundle"
        staging.mkdir()
        for name in ("policy.json", "README.md"):
            content = read_regular_file_bounded(ROOT / "templates" / "learning" / name, 100_000)
            (staging / name).write_bytes(content)
        staging.rename(destination)
    return {"status": "UNCONFIGURED", "destination": str(destination)}


def demo(policy):
    baseline = {"identity": dict.fromkeys(("dataset", "rubric", "model", "evaluator"), "synthetic-v1"),
                "harness": "baseline", "synthetic": True, "cases": []}
    for split in ("visible", "heldout"):
        baseline["cases"].append({"id": split, "group": split, "split": split, "status": "ok", "trace": "synthetic:" + split,
            "gates": {k: {"value": True, "rationale": "Synthetic gate fixture."} for k in policy["gates"]},
            "scores": {k: {"value": 3, "rationale": "Synthetic baseline fixture."} for k in policy["dimensions"]}})
    candidate = copy.deepcopy(baseline)
    candidate["harness"] = "candidate"
    for case in candidate["cases"]:
        for grade in case["scores"].values():
            grade["value"] = 4
    return baseline, candidate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "check", "compare", "demo"))
    parser.add_argument("--target", type=Path)
    parser.add_argument("--bundle", type=Path, default=ROOT / "templates" / "learning")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--candidate", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "init":
            if args.target is None:
                fail("--target required")
            result = initialize(args.target)
        else:
            policy = policy_at(args.bundle)
            if args.command == "check":
                result = {"status": "VALID_SCAFFOLD", "application_verified": False}
            elif args.command == "demo":
                result = compare(policy, *demo(policy))
            else:
                if args.baseline is None or args.candidate is None:
                    fail("--baseline and --candidate required")
                result = compare(policy, read(args.baseline), read(args.candidate))
        print(json.dumps(result, sort_keys=True))
        return 1 if result.get("verdict") == "REJECT" else 0
    except (ValueError, OSError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        print(json.dumps({"verdict": "NO_GATE", "reason": str(exc), "activated": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
