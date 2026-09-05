# Customer deployment boundaries

A customer platform owner needs to decide where an application may process
customer material and who may operate it. A database in the requested country
does not establish where a model request, trace export, evaluation job or support
session goes. Record each destination and owner separately before selecting a
deployment (a deployment profile).

The kit checks the consistency of those declarations offline. It never creates
cloud resources, calls a model, verifies contracts or grants deployment approval.

## Profile and evidence

Start from [the synthetic profile](../templates/harness/deployment-profile.json).
Its Korea customer-owned scenario is a hypothetical restriction, not a claim
that any particular product, model or law supports the configuration. Provider,
model processing, support and legal evidence deliberately remain unresolved.

| Boundary | Required decision and evidence |
| --- | --- |
| Deployment | Customer-owned or vendor-owned account, application location, exact customer scope, delivery mode and customer-admin visibility. |
| Storage | Owner and all locations, including replicas, backups, queues, attachments and exports. |
| Model processing | Named provider/model; every possible processing location, cross-region inference and fallback behavior. |
| Trace and evaluation | Separate owners/locations; raw-content export, retention and customer-content use in global evaluation. |
| Operations | Operator locations, support access, network egress plus exact endpoint allowlist, access review, recovery and deletion responsibilities. |
| IP and terms | Application, customer-data and harness owners; applicable contract, model/data licenses and qualified legal review. |

The policy's allowed regions and permissions are the customer's declared
requirements; preserve their reviewed revision outside a candidate agent's edit
authority. Region identifiers are explicit scope labels, not geolocation logic.
Use the same granularity on both sides: `KR` does not automatically match an AWS
region string. Do not use broad geography labels as proof of country confinement.

Declare `delivery_mode` as `source`, `binary`, `source-and-binary` or
`managed-service`, independently of customer-admin visibility (`full`, `limited`
or `none`). The policy explicitly lists permitted choices. A customer owning the
account and seeing running containers does not imply delivery of source code or
ownership of vendor IP; the reviewed artifact/license manifest establishes what
is actually supplied. Unknown delivery/access decisions remain `null`.

`operations.egress_endpoints` lists every declared outgoing destination, checked
by exact string equality against `policy.allowed_egress_endpoints`. Use an empty
list for a known no-egress configuration, `null` for unresolved inventory. Lists
are capped at 32 HTTPS endpoints; wildcards, credentials, queries and fragments
are refused. This is an offline inventory check, not a firewall. Evidence must
bind the actual DNS/proxy/network controls and include fallback, trace, support
and model endpoints. The checker never resolves or requests any supplied URL.

Every `evidence` record is either `null` (unknown) or an object with a bounded
`reference`, lowercase `sha256`, `reviewed_on` date (`YYYY-MM-DD`) and
`reviewer_role`. Keep the actual reviewed documents in the customer's authorized
store; do not paste private contracts, tenant identifiers, credentials or customer
content into this public repository. The validator does not open those references
or authenticate a role label. Filling the fields is not proof that a review occurred.

Use `null` for unknown owners, model identity, destination lists and observed
booleans. Empty arrays and strings are not evidence that a service is disabled.
Each surface has a single evidence record; it may identify an immutable manifest
covering all its component sources. A later provider/configuration change requires
fresh evidence and a new profile digest. Authentication, availability, retention,
key management, backups, disaster recovery and regulatory decisions remain separate
reviews; this intentionally small checker cannot certify them.

## Run and inspect

```bash
python scripts/deployment_profile.py --profile templates/harness/deployment-profile.json
python scripts/deployment_profile.py --profile templates/harness/deployment-profile.json --format ascii
python scripts/deployment_profile.py --profile templates/harness/deployment-profile.json --format html
```

All formats print to stdout and use one exact profile plus assessment record.
Save HTML only in an authorized local location; reports include the supplied
profile. The HTML is static, escapes profile values and makes no remote requests.

- `NO_GATE` / exit 2: missing evidence, unknown decisions, malformed or oversized
  input. The template must return this, not green.
- `REJECT` / exit 1: declared region or policy violation, or a rejected legal
  review. A known violation outranks other unresolved evidence.
- `PROFILE_CONSISTENT` / exit 0: complete declarations agree with the declared
  policy. This is **not** compliance, legal, readiness, production or deployment
  approval, including for synthetic examples.

Prohibited cross-region inference, fallback, trace export, support access, egress
or customer-content use in global evals rejects the profile. Both customer-owned
and vendor-owned deployments use the same rule; ownership alone grants no exception.
The checker has no network or provisioning path, caps reads at 256 KiB, rejects
linked paths, duplicate JSON keys and nonfinite values, and bounds region lists.

## Verify vendor behavior when selecting it

Model requests can have a different location from the source endpoint: AWS
documents inference profiles that route across regions within a geography or
globally. Inspect the exact profile and observed processing locations rather
than treating a source endpoint as confinement. [AWS cross-region inference](https://docs.aws.amazon.com/bedrock/latest/userguide/cross-region-inference.html)

Self-hosted tracing still has multiple storage and operational boundaries.
Langfuse documents application containers, transactional and analytical stores,
cache/queue, object storage and an optional model gateway. Review the selected
configuration's complete data flow rather than assuming self-hosting establishes
residency. [Langfuse self-hosting](https://langfuse.com/self-hosting)

Sources accessed 2026-09-05. Re-check current provider availability, routing,
terms and customer requirements when making a deployment decision. No regional
model availability or legal conclusion is embedded in this template.
