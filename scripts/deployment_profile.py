#!/usr/bin/env python3
"""Offline deployment-policy consistency check and shared JSON/ASCII/HTML report."""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import html
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from path_safety import read_regular_file_bounded

MAX_BYTES = 262_144
ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "deployment-profile/v1"
REGION_FIELDS = ("application_regions", "storage_regions", "processing_regions", "trace_regions", "eval_regions", "operator_regions")
FLAG_FIELDS = ("cross_region_inference", "model_fallback", "trace_export", "support_access", "network_egress", "customer_content_global_eval")
DELIVERY_MODES = ("source", "binary", "source-and-binary", "managed-service")
ADMIN_VISIBILITY = ("full", "limited", "none")
SURFACE_KEYS = {
    "storage": {"owner", "regions", "evidence"},
    "model_processing": {"provider", "model", "regions", "cross_region_inference", "fallback_enabled", "evidence"},
    "trace_eval": {"trace_owner", "trace_regions", "eval_owner", "eval_regions", "trace_export_enabled", "customer_content_global_eval", "evidence"},
    "operations": {"operator_owner", "operator_regions", "support_access_enabled", "network_egress_enabled", "egress_endpoints", "evidence"},
    "ip": {"application_owner", "customer_data_owner", "harness_owner", "legal_review", "evidence"},
}


def fail(message):
    raise ValueError(message)


def exact(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        fail(f"{label}: exact declared fields required")


def wording(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 2000 or any(ord(c) < 32 for c in value):
        fail(f"{label}: bounded nonempty single-line text required")


def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            fail("duplicate JSON key")
        result[key] = value
    return result


def read_profile(path):
    path = Path(path).absolute()
    body = read_regular_file_bounded(path, MAX_BYTES, boundary=Path(path.anchor), label="deployment profile")
    return json.loads(body.decode("utf-8"), object_pairs_hook=pairs,
                      parse_constant=lambda _: fail("nonfinite JSON is not evidence"))


def regions(value, label, *, unknown=True):
    if value is None and unknown:
        return
    if not isinstance(value, list) or not 1 <= len(value) <= 32:
        fail(f"{label}: one through 32 explicit region identifiers required")
    if any(not isinstance(item, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", item) for item in value):
        fail(f"{label}: invalid region identifier")
    if len(set(value)) != len(value):
        fail(f"{label}: duplicate region")


def evidence(value, label):
    if value is None:
        return
    exact(value, {"reference", "sha256", "reviewed_on", "reviewer_role"}, label)
    for key in ("reference", "reviewer_role"):
        wording(value[key], f"{label}.{key}")
    if not isinstance(value["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", value["sha256"]):
        fail(f"{label}: evidence SHA-256 required")
    if not isinstance(value["reviewed_on"], str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value["reviewed_on"]):
        fail(f"{label}: review date required")
    date.fromisoformat(value["reviewed_on"])


def endpoints(value, label, *, unknown=True):
    if value is None and unknown:
        return
    if not isinstance(value, list) or len(value) > 32:
        fail(label + ": at most 32 exact endpoints required")
    for endpoint in value:
        wording(endpoint, label)
        parsed = urlsplit(endpoint)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment
                or "*" in endpoint or "\\" in endpoint or any(c.isspace() for c in endpoint)):
            fail(label + ": exact HTTPS endpoint without credentials, wildcard, query or fragment required")
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            fail(label + ": invalid endpoint port")
    if len(set(value)) != len(value):
        fail(label + ": duplicate endpoint")


def allowed_choices(value, choices, label):
    if (not isinstance(value, list) or not 1 <= len(value) <= len(choices)
            or any(item not in choices for item in value) or len(set(value)) != len(value)):
        fail(label + ": explicit distinct allowed choices required")


def assess(profile):
    """Check declarations, not cloud state, evidence authenticity or legal approval."""
    exact(profile, {"schema_version", "profile_id", "synthetic", "deployment", "policy", *SURFACE_KEYS}, "profile")
    if profile["schema_version"] != SCHEMA or type(profile["synthetic"]) is not bool:
        fail("unsupported schema or missing explicit synthetic flag")
    wording(profile["profile_id"], "profile_id")
    deployment = profile["deployment"]
    exact(deployment, {"owner", "customer_scope", "application_region", "delivery_mode", "customer_admin_visibility", "evidence"}, "deployment")
    for key in ("customer_scope", "application_region"):
        wording(deployment[key], f"deployment.{key}")
    if deployment["owner"] not in ("customer", "vendor"):
        fail("deployment.owner must name customer or vendor")
    policy = profile["policy"]
    exact(policy, {*REGION_FIELDS, *("allow_" + key for key in FLAG_FIELDS), "allowed_egress_endpoints",
                   "allowed_delivery_modes", "allowed_customer_admin_visibility", "evidence"}, "policy")
    for key in REGION_FIELDS:
        regions(policy[key], "policy." + key, unknown=False)
    for key in FLAG_FIELDS:
        if type(policy["allow_" + key]) is not bool:
            fail("policy flags must be explicit booleans")
    unknowns, violations = [], []
    endpoints(policy["allowed_egress_endpoints"], "policy.allowed_egress_endpoints", unknown=False)
    for key, policy_key, choices in (("delivery_mode", "allowed_delivery_modes", DELIVERY_MODES),
                                     ("customer_admin_visibility", "allowed_customer_admin_visibility", ADMIN_VISIBILITY)):
        allowed_choices(policy[policy_key], choices, "policy." + policy_key)
        value = deployment[key]
        if value is None:
            unknowns.append("deployment." + key + ": unresolved")
        elif value not in choices:
            fail("deployment." + key + ": invalid choice")
        elif value not in policy[policy_key]:
            violations.append("deployment." + key + ": prohibited by declared policy")
    if deployment["application_region"] not in policy["application_regions"]:
        violations.append("deployment.application_region: outside declared allowed regions")
    for label, surface in (("deployment", deployment), ("policy", policy),
                           *((key, profile[key]) for key in SURFACE_KEYS)):
        if label in SURFACE_KEYS:
            exact(surface, SURFACE_KEYS[label], label)
        evidence(surface["evidence"], label + ".evidence")
        if surface["evidence"] is None:
            unknowns.append(label + ": evidence unresolved")
    for label in ("storage", "trace_eval", "operations", "ip"):
        for key, value in profile[label].items():
            if key.endswith("owner"):
                if value not in ("customer", "vendor", "shared", None):
                    fail(label + "." + key + ": invalid owner")
                if value is None:
                    unknowns.append(label + "." + key + ": owner unresolved")
    for key in ("provider", "model"):
        value = profile["model_processing"][key]
        if value is None:
            unknowns.append("model_processing." + key + ": unresolved")
        else:
            wording(value, "model_processing." + key)
    for surface_name, key, policy_key in (
        ("storage", "regions", "storage_regions"),
        ("model_processing", "regions", "processing_regions"),
        ("trace_eval", "trace_regions", "trace_regions"),
        ("trace_eval", "eval_regions", "eval_regions"),
        ("operations", "operator_regions", "operator_regions"),
    ):
        value = profile[surface_name][key]
        label = surface_name + "." + key
        regions(value, label)
        if value is None:
            unknowns.append(label + ": processing or storage locations unresolved")
        elif not set(value).issubset(policy[policy_key]):
            violations.append(label + ": outside declared allowed regions")
    for surface_name, key, policy_key in (
        ("model_processing", "cross_region_inference", "cross_region_inference"),
        ("model_processing", "fallback_enabled", "model_fallback"),
        ("trace_eval", "trace_export_enabled", "trace_export"),
        ("trace_eval", "customer_content_global_eval", "customer_content_global_eval"),
        ("operations", "support_access_enabled", "support_access"),
        ("operations", "network_egress_enabled", "network_egress"),
    ):
        value = profile[surface_name][key]
        label = surface_name + "." + key
        if value is None:
            unknowns.append(label + ": unresolved")
        elif type(value) is not bool:
            fail(label + ": explicit boolean or null required")
        elif value and not policy["allow_" + policy_key]:
            violations.append(label + ": prohibited by declared policy")
    destinations = profile["operations"]["egress_endpoints"]
    endpoints(destinations, "operations.egress_endpoints")
    if destinations is None:
        unknowns.append("operations.egress_endpoints: unresolved")
    else:
        if not set(destinations).issubset(policy["allowed_egress_endpoints"]):
            violations.append("operations.egress_endpoints: outside exact endpoint allowlist")
        if destinations and profile["operations"]["network_egress_enabled"] is False:
            violations.append("operations.egress_endpoints: declared destinations contradict disabled egress")
    legal = profile["ip"]["legal_review"]
    if legal not in ("reviewed", "unresolved", "rejected"):
        fail("ip.legal_review: invalid state")
    if legal == "unresolved":
        unknowns.append("ip: legal and IP terms unresolved")
    elif legal == "rejected":
        violations.append("ip: declared legal review rejected")
    verdict = "REJECT" if violations else "NO_GATE" if unknowns else "PROFILE_CONSISTENT"
    encoded = json.dumps(profile, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return {"verdict": verdict, "profile_sha256": hashlib.sha256(encoded).hexdigest(),
            "synthetic": profile["synthetic"], "violations": sorted(violations), "unresolved": sorted(unknowns),
            "deployment_authorized": False, "compliance_approved": False,
            "limits": ["Declarations only; evidence references are not opened or authenticated.",
                       "No resource provisioning, runtime, region availability, legal or readiness verification."]}


def render(profile, assessment, format_name):
    # One record is the source for every presentation, including exact profile and digest.
    record = {"assessment": assessment, "profile": profile}
    serialized = json.dumps(record, sort_keys=True, indent=2, ensure_ascii=True)
    if format_name == "json":
        return serialized
    title = "Deployment profile: " + assessment["verdict"]
    if format_name == "ascii":
        return title + "\n" + "=" * len(title) + "\n" + serialized
    return ('<!doctype html><html lang="en"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Deployment profile review</title><style>body{font:16px system-ui;max-width:90ch;'
            'margin:2rem auto;padding:0 1rem}pre{white-space:pre-wrap;overflow-wrap:anywhere;'
            'background:#f3f5f7;padding:1rem}</style><main><h1>' + html.escape(title) +
            '</h1><p>Declared-policy consistency only. This is not deployment or compliance approval.</p>'
            '<pre>' + html.escape(serialized) + '</pre></main></html>')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=ROOT / "templates/harness/deployment-profile.json")
    parser.add_argument("--format", choices=("json", "ascii", "html"), default="json")
    args = parser.parse_args(argv)
    profile = None
    try:
        profile = read_profile(args.profile)
        assessment = assess(profile)
    except (ValueError, OSError, TypeError, KeyError, RecursionError) as exc:
        # Do not echo potentially sensitive malformed file content or absolute paths.
        profile = None
        assessment = {"verdict": "NO_GATE", "reason": "Profile unreadable or invalid: " + type(exc).__name__,
                      "deployment_authorized": False, "compliance_approved": False}
    print(render(profile, assessment, args.format))
    return {"PROFILE_CONSISTENT": 0, "REJECT": 1, "NO_GATE": 2}[assessment["verdict"]]


if __name__ == "__main__":
    raise SystemExit(main())
