---
id: QA-3
branch: ext/QA-3
allowed_paths: [docs/quality_report.md]
---
# QA-3: Whole-repo quality audit (report only)
Read the entire `Extension` branch (backend `full_app/**`, frontend `full_app/production_frontend/**`, docs, Docker/CI) and write
`docs/quality_report.md`: a prioritized, concrete list of slop and risk (file:line, what is wrong, the exact fix), grouped as P1 (bugs, broken
wiring, security, data loss), P2 (duplication, dead code, inconsistent APIs, misleading docs, unused dependencies in requirements/package.json,
tests that assert nothing), P3 (style, naming, comment filler/AI-isms). Include a dependency audit (each requirement: used where? needed? optional
extra?), a list of duplicated helpers to consolidate, modules whose README/docs claim features that do not exist, and the 10 highest-value fixes.
**Do not edit code**; the integrator applies fixes after all branches merge. Verify claims by reading code and grepping callers; you may run the
suite on the runner to confirm failures.
