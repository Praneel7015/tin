# Error surface inventory

Status: complete

These are queries Shipyard's own users already type when a deploy fails; Shipyard is the only site that can answer them first, and today a forum thread or a model's guess does. Add this file to content.plan's context files to schedule the pages below.

## Ranked opportunities

| Rank | Search query | Suggested page | Score | Surface | Call sites | Evidence | Demand | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `SHIP_BUILD_OUTPUT_MISSING: Could not find build output directory (out, dist, build, .next)` | Shipyard: Could not find build output directory (rows 1-2) | 90.0 | cli | 4 | src/cli/deploy.ts:88 | not measured | new |
| 2 | `SHIP_BUILD_SCRIPT_MISSING: package.json has no "build" script` | Shipyard: Could not find build output directory (rows 1-2) | 79.2 | cli | 2 | src/cli/deploy.ts:61 | not measured | new |
| 3 | `SHIP_PREVIEW_QUOTA: preview environment limit reached for this team` | Shipyard: Preview environment limit reached | 72.0 | api | 3 | src/api/errors.py:41 | 20 (organic.keyword_plan 3f9d2c10, 2026-09-10) | new |

## Page facts for content.plan

### Shipyard: Could not find build output directory
- Reader: a person running `shipyard deploy` from a project root.
- Rows: 1, 2.
- Cause: the CLI looks for out, dist, build or .next after the build step and finds none (src/cli/deploy.ts:88); with no build script it stops earlier (src/cli/deploy.ts:61).
- Fix: add a "build" script that writes one of those directories; the message itself names them.
- Check first: https://shipyard.dev/docs/cli/deploy from the audit crawl.

### Shipyard: Preview environment limit reached
- Reader: an integrator creating previews through the API.
- Rows: 3.
- Cause: the API rejects a new preview when the team's active previews reach its plan limit (src/api/previews.py:112).
- Fix: not established from the code.
- Check first: none found in the audit crawl.

## Below the cut

None: all 3 page-worthy messages fit within the 15 requested.

## Already documented

- `SHIP_AUTH_EXPIRED: your CLI session expired, run shipyard login` — docs/cli/auth.md

## Queries you cannot win

- `Invalid input` — returned from 14 routes (src/api/validate.py:20); nothing distinctive to paste. Winnable only if each route names the field and a code, such as `SHIP_INVALID_BRANCH`.
- `Error: {msg}` — all interpolation (src/cli/output.ts:12); the invariant core is one generic word.

## Internal only

3 messages, for example `assert plan_cache is not None` (src/billing/cache.py:9).

## What this does not measure

This run measured what Shipyard emits and what its repository documents. It measured no demand, keyword difficulty, ranking or traffic of its own; the one figure shown was already observed by organic.keyword_plan. Rows marked not measured need keyword research before anybody commits to writing. The suggested pages go to content.plan for scheduling and content.generate to be written; this run writes none of them.

## Method and coverage

Depth standard. Read src/cli, src/api and web/src/locales/en.json, starting from the Code map's CLI and API surfaces. Skipped vendor/ and generated clients. Docs searched: docs/. Project files used: wiki/INDEX.md (Code map), reports/keyword-plan/3f9d2c10-0000-4000-8000-000000000001/keywords.json, reports/organic-audit/6c1f0b7e-2d1a-4e0b-9a51-0d3c2f6e8a10/evidence.json; no content plan yet. Since last run: first run.
