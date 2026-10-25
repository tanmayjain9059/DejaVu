# LostLink product-readiness checklist

This is a release gate, not a claim that LostLink is already production-ready.
Complete and record each gate before using real student data or opening the service
to the public internet.

## P0 — Establish a safe code baseline

- [ ] Review the database adapter and transaction changes in the hardening PR.
- [ ] Reconcile the hardening branch with the latest `main` changes.
- [ ] Require passing CI on the exact candidate commit; keep `main` unchanged until a human approves the PR.
- [x] Add regression coverage for PostgreSQL placeholder conversion around quoted strings and SQL comments.
- [x] Add baseline browser security response headers with response-level tests.

## P1 — Workflow integrity and concurrency

- [ ] Add concurrent integration tests for competing claims on one item.
- [ ] Prove duplicate handover requests cannot create duplicate handover/reward events.
- [ ] Prove report closure and claim approval cannot race into an invalid state.
- [ ] Verify rollback behavior when an audit, notification, or reward write fails partway through a workflow.
- [ ] Confirm database constraints are the final guard for unique handovers, reward event keys, and notification event keys.

## P2 — Security and privacy

- [x] Add same-host Origin/Referer checks for unsafe API mutations; [ ] verify reverse-proxy/canonical-host behavior in the deployed environment.
- [ ] Review every API route for object-level authorisation and private evidence access.
- [ ] Configure production HTTPS, a managed secret, secure session cookies, and a supported deployment configuration.
- [ ] Add a tested retention/deletion policy for reports, evidence images, audit events, and account data.
- [ ] Verify upload storage is persistent, private where required, backed up, and not publicly mounted.
- [ ] Define backup access controls, restoration drills, monitoring, and incident response.

## P3 — Database operations

- [ ] Use a versioned migration system with a documented rollback/recovery approach.
- [ ] Test a backup restore against the exact PostgreSQL schema and application revision.
- [ ] Document a one-time SQLite-to-PostgreSQL migration and validate row counts, relationships, and image paths.
- [ ] Measure pool saturation and transaction/advisory-lock contention under representative concurrent use.
- [x] Add liveness and database-readiness endpoints; [ ] verify deployment health checks and a repeatable clean-environment release test.

## P4 — Matching quality and operational pilot

- [ ] Build a representative, privacy-reviewed labelled campus evaluation set.
- [ ] Measure top-k retrieval, false positives, missed matches, and subgroup/category performance; do not call scores ownership probabilities.
- [ ] Test mobile layouts and keyboard/screen-reader flows on real devices.
- [ ] Confirm campus office procedures for intake, storage, sensitive items, disputes, and physical handover.
- [ ] Run a supervised pilot with synthetic or approved test data and record acceptance criteria before scaling.

## Current known limitations

- PostgreSQL support is implemented through a compatibility adapter and needs ongoing dialect coverage.
- Existing SQLite data is not automatically migrated when `DATABASE_URL` is set.
- PostgreSQL does not persist local uploaded files; image/evidence storage needs a separate durable storage plan.
- Matching benchmark data is small and synthetic; it is not evidence of real-campus accuracy.
- A passing CI run is not a security audit, load test, backup/restore test, or production-readiness certification.
