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
- [ ] Add keyset pagination to student claims and office claim queues. Preserve
  office disputed-first review priority without using mutable claim status as a
  cursor key; design and test the queue semantics before implementation.
- [ ] Paginate office intake/inventory views with deterministic ordering and
  bounded page sizes.
- [ ] Replace the matching endpoint's fixed 500-row candidate window with a
  measured retrieval strategy that preserves the current category-aware scorer,
  MiniLM cache, batched CLIP inference, and AI caption/keyword signals. Do not
  replace it with an unbounded in-memory full-corpus scan without capacity tests.
- [ ] Add and validate a composite candidate lookup index for the final retrieval
  query plan; include SQLite and PostgreSQL query-plan coverage.
- [ ] Revalidate candidate visibility and availability immediately before
  returning suggestions so stale or no-longer-claimable items are not exposed.
- [ ] Preserve AI caption and keyword fields in every search and candidate query.
- [ ] Add pagination regressions for tied timestamps, filters, cursor tampering,
  no duplicates/skips, and changing claim status between page requests.

### P1 — Workflow and storage

- [ ] Add report editing with owner/office authorization, report-type and workflow
  state restrictions, field validation, and an audit event for every edit.
- [ ] Introduce private S3-compatible object storage behind a storage interface;
  keep local filesystem storage for development and tests.
- [ ] Route report photos and claim evidence through authenticated private
  retrieval; never expose public bucket URLs or weaken current image visibility,
  sensitivity, watermark, and no-store controls.
- [ ] Add storage migration, integrity verification, and coordinated database +
  object backup/restore tests before switching an existing deployment.

### P2 — Controlled onboarding and operations

- [ ] Add office-issued, email-bound, single-use student invites only if the
  institution confirms this onboarding model. Store only invite hashes, enforce
  expiry and one-time use, and do not permit public office registration.
- [ ] Require staff to verify student identity and institutional email through
  an out-of-band process before issuing an invite; possession of an invite code
  alone is not proof of email ownership.
- [ ] Document provider-specific deployment settings, private storage lifecycle,
  monitoring, and recovery procedures after the storage adapter is selected.

### Migration reconciliation requirement

PR #3 and current main have incompatible migration histories. Do not renumber or
rewrite already-applied migrations. Before porting PR #3 schema features, add a
forward-only, idempotent reconciliation migration that ensures all required
objects exist for both histories, including current report AI-enrichment columns,
the persistent embedding cache, the matching-candidate index, and registration
invite storage. Test upgrades from databases initialized on either lineage.


## Current known limitations

- PostgreSQL support is implemented through a compatibility adapter and needs ongoing dialect coverage and concurrency/load testing. A local development service and production-oriented container configuration are provided; no hosted production database has been provisioned.
- Existing SQLite data is not automatically migrated at startup; an explicit utility is available but has not been rehearsed on the production dataset.
- Image/evidence files remain filesystem-backed. Production Compose provides a persistent volume, but coordinated off-host backup and restoration must be verified.
- Matching benchmark data is small and synthetic; it is not evidence of real-campus accuracy.
- The migration ledger records the legacy bootstrap baseline and applies versioned forward migrations for new changes; older additive compatibility updates still run in the legacy bootstrap, and each future migration needs an explicit recovery plan.
- The visual pass only slightly reduces shadow, radius, and ambient contrast; it does not change product navigation or workflows.
- A passing CI run is not a security audit, load test, backup/restore test, live deployment verification, or production-readiness certification.
