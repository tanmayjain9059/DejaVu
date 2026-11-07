# LostLink product-readiness checklist

This is a release gate, not a claim that LostLink is already production-ready.
Complete and record each gate before using real student data or opening the service
to the public internet.

## P0 — Establish a safe code baseline

- [x] Review the database adapter, transaction boundaries, and route-level authorization code; retain independent human review before merge.
- [x] Reconcile and merge `codex/hardening-db-mobile` into `main`; `codex/product-readiness-hardening` was already an ancestor of the merged branch and contributed no unique commits.
- [x] The merged `main` commit `b601d0048658cbb22d32bab735a658da7cd00651` passed the exact-head CI run, including unit/workflow tests, PostgreSQL integration and concurrency regressions, Docker/Compose validation, and semantic matching evaluation. This is CI evidence, not a production certification.
- [x] Add regression coverage for PostgreSQL placeholder conversion around quoted strings and SQL comments.
- [x] Add baseline browser security response headers with response-level tests.

## P1 — Workflow integrity and concurrency

- [x] Add concurrent integration tests for competing claims on one item; verify both claims enter the disputed state.
- [x] Add a regression test for concurrent duplicate handover requests and assert one handover and one reward event; the exact merged-head PostgreSQL CI run passed.
- [x] Add a concurrent regression for report closure versus approval of a linked claim; approval now rechecks linked-report state inside the serialized transaction.
- [x] Add fault-injection tests for audit failure during image upload and notification/reward failures during handover; verify rollback and filesystem cleanup.
- [x] Add versioned unique-index guards for handovers, reward event keys, and notification event keys; migration fails closed on duplicate historical keys.

## P2 — Security and privacy

- [x] Add same-host Origin/Referer checks for unsafe API mutations and configurable trusted-host validation; [ ] verify reverse-proxy/canonical-host behavior in the deployed environment.
- [x] Add no-store API response headers to reduce sensitive browser-cache persistence.
- [x] Review API route authorization for reports, claims, private evidence, notifications, certificates, activity, and office endpoints; existing private-evidence and linked-report authorization regressions cover key boundaries. [ ] Complete staging verification.
- [x] Add a non-root production container configuration requiring HTTPS cookies, a session secret, database URL, and explicit host allowlist; [ ] validate it behind the actual production proxy.
- [x] Add an institution-facing retention policy template; [ ] obtain approval for actual periods/holds and implement/test a dry-run-first deletion process.
- [x] Add a persistent private uploads volume and encrypted uploads backup/restore utilities; [ ] verify permissions and complete a coordinated database-plus-uploads backup/restore drill.
- [x] Add encrypted PostgreSQL dump and guarded restore scripts plus a daily systemd timer template; [ ] complete an off-host backup and restore drill and configure monitoring/incident response.

## P3 — Database operations

- [x] Add an ordered, forward-only migration ledger (v1 legacy baseline, v2 active-claim indexes, v3 workflow uniqueness guards, v4 legacy additive columns/image fingerprint backfill), with a documented recovery policy. Core table bootstrap remains at startup; future schema changes must use versioned migrations.
- [x] Add a conservative SQLite-to-PostgreSQL migration utility with dry-run mode, empty-destination guard, integrity/FK checks, row-count verification, sequence repair, and referenced-upload copy; [ ] rehearse it against a representative backup and independently verify results.
- [x] Add forward-only migration v7 to reconcile AI enrichment fields, the persistent embedding cache, and composite matching indexes across the current-main and PR #3 v5/v6 histories; regression coverage simulates the PR #3 lineage.
- [x] Add encrypted PostgreSQL backup and guarded restore scripts; [ ] test a restore against the exact PostgreSQL schema/application revision and restore matching uploads.
- [ ] Run `scripts/probe_database_contention.py` against a representative staging workload and record p50/p95/max latency, throughput, failures, pool size, and database instance size; CI race regressions are correctness tests, not capacity measurements.
- [x] Add liveness/readiness endpoints, local PostgreSQL setup, production container configuration, and database runbooks; [ ] verify deployment health checks and a repeatable clean-environment release test.

## P4 — Matching quality and operational pilot

- [ ] Build a representative, privacy-reviewed labelled campus evaluation set.
- [ ] Measure top-k retrieval, false positives, missed matches, and subgroup/category performance; do not call scores ownership probabilities.
- [ ] Test mobile layouts and keyboard/screen-reader flows on real devices.
- [ ] Confirm campus office procedures for intake, storage, sensitive items, disputes, and physical handover.
- [ ] Run a supervised pilot with synthetic or approved test data and record acceptance criteria before scaling.


## PR #3 integration backlog

This section tracks relevant PR #3 capabilities that are not yet present on the
integration branch. PR #3 is not merged wholesale: its older matching and migration
implementations must not replace the current AI baseline.

### P0 — Operational correctness and bounded data access

- [x] Add keyset cursor pagination to report listing, with deterministic
  `created_at DESC, id DESC` ordering, a bounded page size (1–100), opaque
  cursor validation, and existing role/visibility/search filters preserved.
- [x] Add keyset pagination to student claims and office claim queues. Cursor
  order uses immutable creation time and ID; office staff can page disputed,
  pending and remaining queues separately, and each row exposes a priority rank.
  This avoids using mutable status as a cursor key.
- [x] Office intake/inventory lists use the shared report-list cursor API with
  deterministic creation-time/ID ordering and bounded page sizes.
- [x] Replace the fixed 500-row cutoff with a bounded two-tier indexed shortlist
  (75% same-category, remainder cross-category/location; default 2,000 and
  configurable up to 10,000). Existing category-aware scoring, MiniLM cache,
  batched CLIP inference, and AI caption/keyword fields are retained. Exhaustive
  recall and campus capacity still require representative staging measurements.
- [x] Add composite report candidate/recent indexes in migration v7. [ ] Record
  SQLite and PostgreSQL query-plan and latency measurements on staging.
- [x] Re-read top-ranked candidates after inference and drop records that are no
  longer available or visible to the requesting student.
- [x] Preserve AI caption and keyword fields in report search and candidate
  retrieval; current matcher text composition includes enrichment fields.
- [x] Add report/claim cursor regression tests for tied timestamps, filters,
  malformed cursors, bounded page sizes, and duplicate/skip detection. [ ] Add
  a live PostgreSQL mutation-between-pages regression before release.

### P1 — Workflow and storage

- [x] Add report editing with owner/office authorization, immutable report type,
  workflow-state restrictions, validation, and an audit event.
- [x] Add a private S3-compatible object-storage adapter while retaining local
  filesystem storage as the default development/test backend.
- [x] Route report photos and claim evidence through the storage adapter and
  existing authenticated routes; preserve visibility, sensitive-category,
  watermark, and no-store checks. CLIP and BLIP read through the adapter.
- [x] Add a dry-run-first local-to-S3 copy utility that preserves database keys
  and local originals. [ ] Add provider-specific integrity and coordinated
  database/object backup-restore drills before switching a populated deployment.

### P2 — Controlled onboarding and operations

- [ ] Add office-issued, email-bound, single-use student invites only if the
  institution confirms this onboarding model. Store only invite hashes, enforce
  expiry and one-time use, and do not permit public office registration.
- [ ] Require staff to verify student identity and institutional email through
  an out-of-band process before issuing an invite; possession of an invite code
  alone is not proof of email ownership.
- [x] Document S3-compatible configuration, private bucket policy, migration,
  lifecycle and recovery in `docs/OBJECT_STORAGE.md`. [ ] Verify the selected
  provider's monitoring, lifecycle and restore controls in staging.

### Migration reconciliation requirement

- [x] Add forward-only migration v7 to reconcile current report AI-enrichment
  columns, the persistent embedding cache, and composite matching indexes even
  when versions 5/6 were already recorded by the PR #3 lineage. A regression test
  simulates a database with PR #3 versions 5/6 applied but the main AI objects
  absent, then verifies that v7 repairs the schema. Existing PR #3 invite tables
  are left untouched if present; LostLink does not create a new invite workflow
  until the institution approves the onboarding and identity-verification policy.


## Current known limitations

- PostgreSQL support is implemented through a compatibility adapter and needs ongoing dialect coverage and concurrency/load testing. A local development service and production-oriented container configuration are provided; no hosted production database has been provisioned.
- Existing SQLite data is not automatically migrated at startup; an explicit utility is available but has not been rehearsed on the production dataset.
- Image/evidence files can use the local filesystem or a private S3-compatible backend. The S3 migration tool is dry-run by default and preserves local originals; provider-specific object backup/restore and a coordinated database/object restore drill remain open.
- Matching benchmark data is small and synthetic; it is not evidence of real-campus accuracy.
- The migration ledger records the legacy bootstrap baseline and applies versioned forward migrations for new changes; older additive compatibility updates still run in the legacy bootstrap, and each future migration needs an explicit recovery plan.
- The visual pass only slightly reduces shadow, radius, and ambient contrast; it does not change product navigation or workflows.
- A passing CI run is not a security audit, load test, backup/restore test, live deployment verification, or production-readiness certification.
