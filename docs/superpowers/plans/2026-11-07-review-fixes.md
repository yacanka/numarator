# Repository Review Fixes Implementation Plan

**Goal:** Correct all 16 review findings without breaking existing API routes, payloads, CLI usage or successful workflows.

**Architecture:** Keep the Django/Vue/launcher boundaries. Repair permission and transaction boundaries in their existing modules, add backwards-compatible validation routes, and avoid unrelated refactoring. Work in the shared checkout with separate file ownership; the user has explicitly authorized implementation and verification.

**Spec:** Repository review dated 2026-11-07 and the user's instruction to fix all findings with regression tests.

## Constraints

- Preserve existing routes, response envelopes, cookie names and command-line options.
- Do not modify real application data, existing migrations, or user files.
- No new runtime libraries unless compatibility requires them; upgrade existing Django dependencies only as needed.
- No commits, deletion of placeholder files, or removal of deployment services in this task.

## Tasks

### 1. Number generation and document validation (findings 3, 4, 6–9)

Owner: numbering agent. Files: `backend/apps/formats/` and `backend/apps/documents/`.

- [x] Add failing regression tests for batch rollback, advancing past collisions, preserving metadata, invalid context configuration, safe preview of historical invalid data, lifecycle validity, and separator-containing numbers.
- [x] Keep the format lock for the whole batch transaction; preserve single-generation behavior and distinguish duplicate-number conflicts from other database errors.
- [x] Preserve the existing validation URL and add a query/body-compatible route if needed. Coordinate its exact signature with the frontend owner.
- [x] Add `DDMMYYYY` backend support with a literal date test so the existing frontend option remains available.
- [x] Run `manage.py test apps.formats apps.documents` against an isolated database.

### 2. Frontend flows (findings 11–15)

Owner: frontend agent. Files: `frontend/`.

- [x] Add failing behavior tests for pagination/filtering, modal close/format-switch cleanup, CSV escaping/formula safety, draft preview and date formatting.
- [x] Preserve API envelopes and UI actions; load all format options or paginate server-side consistently.
- [x] Ensure in-flight generation cannot populate a newly selected format's modal.
- [x] Keep saved previews for read-only views and use draft values while editing.
- [x] Run `npm test` and `npm run build`.

### 3. Docker security and connectivity (findings 2, 5)

Owner: runtime agent. Files: Dockerfiles, dockerignore files, Docker Nginx/Compose, production proxy settings, deployment docs and dedicated deployment tests.

- [x] Demonstrate the broken command/port/proxy contracts with regression checks.
- [x] Exclude local secrets/data from build contexts, use a single exec Gunicorn command, correct frontend serving and configure TLS plus trusted proxy recognition.
- [x] Document certificate paths and keep native HTTPS settings isolated.
- [x] Run deployment checks and launcher/native tests using temporary data.

### 4. Integration authorization and idempotency (findings 1, 10)

Owner: root. Files: `backend/apps/integrations/` and private API docs.

- [x] Add failing tests for soft-deleted allowlisted formats, explicit all-format permission, allowed mixed sets, and unchanged read/generate/status restrictions.
- [x] Read actual permission relationships without interpreting a filtered empty set as unrestricted access.
- [x] Add failing replay tests after context edits, archival, payload conflict and revoked/removed access.
- [x] Resolve an existing authorized idempotency result before applying current generation-only format rules; preserve concurrent retry atomicity.
- [x] Run the integration test module.

### 5. Supported Django runtime (finding 16)

Owner: root. Files: backend requirements, compatibility adjustments and upgrade documentation.

- [x] Verify supported patch versions from official package/vendor sources and choose Django 5.2 LTS.
- [x] Validate the upgrade in a separate temporary virtual environment before modifying the repository environment.
- [x] Upgrade only companion packages required for compatibility; document the runtime floor and external-package migrations.
- [x] Verify authentication, schema generation, migration consistency and native startup on the upgraded stack.

### 6. Integration and independent review

- [x] Review combined diffs for scope, data safety and compatibility.
- [x] Run full Django, launcher, native, frontend tests, type/build, Django checks, migration dry-run, dependency consistency and `git diff --check`.
- [x] Obtain an independent review of the combined changes and resolve actionable regressions.
- [x] Record actual results and unexecuted checks in the final response.

## Review focus

Concurrent idempotency requests must not invert database/cache lock order; bulk failure must roll back both documents and counters; deleted format permissions must fail closed; stale frontend async responses must not restore old modal data; TLS proxy trust must remain limited to the container ingress while native settings remain unaffected.


## Completion evidence

- Django 5.2.19 + DRF 3.16.1 were first validated in a temporary environment, then installed into the existing backend virtual environment without changing other pinned packages.
- Final SQLite Django suite: 82/82; launcher/native/deployment: 37/37; frontend: 22/22. Total: 141 passing tests (49 additional tests compared with the review baseline).
- Frontend type check/build, Django check, migration dry-run and dependency consistency pass. The existing large frontend chunk warning remains.
- PostgreSQL 17 validation: 64/64 application tests passed; the final 65/65 application tests (including schema regression) also passed with real Redis 7 locks in disposable containers.
- Docker tests exercised synthetic build exclusions, actual Nginx config/TLS/redirect/SPA/assets/API/admin behavior using disposable fixtures. Full Compose stack was not run because the host lacks the Compose plugin.
- Independent final review found no actionable correctness/security regressions. New schema operation-ID collision discovered by native startup was reproduced in a regression test and corrected; full native suite then passed.
- Existing public routes/envelopes and the five-candidate retry bound remain. Query-based number validation is additive. Catalog views load all pages to retain local filtering; memory/network use grows with catalog size.
- No production database was touched, no repository migration was added, no source file was deleted, and no commit/push was performed.

## Subsequent browser validation and bundle optimization

- Real Chrome flows were exercised against an isolated SQLite database: login/logout, format/category creation and editing, repeated duplication, single/bulk generation, CSV, document status/filtering, API keys, profile/preferences and non-admin access restrictions.
- Five additional fixes cover repeated format duplication, document filter/count refresh, preview sequence start, misleading segment sequence controls and stale format-load responses. Fifteen tests were added: the final suites passed 85 backend, 34 frontend and 37 launcher/native/deployment tests (156 total).
- Removed redundant global Naive UI registration; all used components already have explicit local imports. Largest production JavaScript chunk fell from 1,524.79 kB to 390.49 kB (gzip 426.25 kB to 125.09 kB), with the default chunk-warning threshold unchanged.
- Re-ran all 34 frontend tests, typecheck/build and diff checks after the bundle change. Production-preview browser verification passed login/logout, dashboard, formats, generation, documents, API-key listing and settings/theme flows.
- Full Docker Compose and Firefox/Safari remain outside the executed browser coverage. Earlier completion evidence above describes the preceding review checkpoint.
