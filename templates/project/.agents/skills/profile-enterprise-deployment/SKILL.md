---
name: profile-enterprise-deployment
description: Map and check customer deployment ownership, processing regions, tracing and evaluation, operator access and IP boundaries before proposing an enterprise deployment.
---

# Profile enterprise deployment

## Trigger and refusal

Use when a customer asks where its application/data may run or who owns and
operates it. Do not provision resources, choose unverified regional models,
transfer customer material or interpret a profile as legal/deployment approval.

## Workflow

1. Keep customer-owned and vendor-owned deployment options distinct. Record the
   exact customer scope, application location and reviewed policy before design.
   State binary/source/managed delivery and customer-admin visibility separately;
   administrative access to a customer account does not imply source delivery.
2. Map storage (including backups/queues), model processing and fallback, trace
   and eval stores/exports, operator/support/egress access, and IP/data/harness
   ownership separately. Local storage does not prove local model processing.
   List exact permitted egress endpoints, including trace and support endpoints;
   an enabled/disabled switch alone does not describe an egress policy.
3. Read current primary provider routing/self-hosting documentation for the
   chosen service. Verify the actual profile and all destinations; a geography
   or endpoint label is not evidence of country confinement.
4. Record a reference, content digest, review date and reviewer role for each
   surface; keep private evidence in its authorized store. Unknowns stay null.
   Role labels and hashes do not authenticate reviewers or prove permission.
5. If the setup kit is present, use its deployment-profile template and offline
   `scripts/deployment_profile.py` checker. Otherwise produce the same explicit
   boundary inventory and name the missing validator; never invent its location.
6. Reject prohibited cross-region/fallback/trace/support/egress/global-eval use.
   Return NO_GATE for unresolved evidence. PROFILE_CONSISTENT means declared
   policy consistency only, never compliance/readiness or deployment approval.
7. Show the same profile digest and decision in machine, HTML and ASCII reports.
   Make the unresolved operator, model and legal decisions visible. Stop at the
   named evidence gap before performing a transfer or provisioning operation.

## Receipt

Return the exact profile, source references, decision, unresolved boundaries,
verification command/output and remaining authorization. Synthetic examples
must stay labeled. Do not copy customer evidence into a public setup repository.

Read [the execution contract](references/contract.json) before starting. Validate
the generic receipt with its parameterized `verification.argv`, replacing `{python}`,
`{skill_dir}` and `{receipt}`. Receipt validation does not verify deployment.
