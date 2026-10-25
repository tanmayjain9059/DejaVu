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
- [x] Add a regression test for concurrent duplicate handover requests and assert one handover and one reward event; [ ] confirm it passes on the exact candidate CI run.
- [ ] Prove report closure and claim approval cannot race into an invalid state.
- [x] Add a regression test that simulates an audit-write failure during image upload and verifies rollback/file cleanup; [ ] extend fault-injection coverage to notifications and rewards.
- [ ] Confirm database constraints are the final guard for unique handovers, reward event keys, and notification event keys.

## P2 — Security and privacy

- [x] Add same-host Origin/Referer checks for unsafe API mutations and configurable trusted-host validation; [ ] verify reverse-proxy/canonical-host behavior in the deployed environment.
- [x] Add no-store API response headers to reduce sensitive browser-cache persistence.
- [ ] Review every API route for object-level authorisation and private evidence access.
- [x] Add a non-root production container configuration requiring HTTPS cookies, a session secret, database URL, and explicit host allowlist; [ ] validate it behind the actual production proxy.
- [ ] Define and test a retention/deletion policy for reports, evidence images, audit events, and account data.
- [x] Add a persistent private uploads volume to the production Compose configuration; [ ] verify permissions, coordinated backups, and restoration.
- [x] Add encrypted PostgreSQL dump and guarded restore scripts; [ ] complete an off-host backup and restore drill and configure monitoring/incident response.

## P3 — Database operations

- [x] Add an ordered, forward-only schema migration runner and ledger (version 1 records the legacy baseline; version 2 adds active-claim lookup indexes); [ ] define rollback/recovery policy for future migrations and gradually move legacy additive changes out of startup bootstrap.
- [x] Add a conservative SQLite-to-PostgreSQL migration utility with dry-run mode, empty-destination guard, integrity/FK checks, row-count verification, sequence repair, and referenced-upload copy; [ ] rehearse it against a representative backup and independently verify results.
- [x] Add encrypted PostgreSQL backup and guarded restore scripts; [ ] test a restore against the exact PostgreSQL schema/application revision and restore matching uploads.
- [ ] Measure pool saturation and transaction/advisory-lock contention under representative concurrent use.
- [x] Add liveness/readiness endpoints, local PostgreSQL setup, production container configuration, and database runbooks; [ ] verify deployment health checks and a repeatable clean-environment release test.

## P4 — Matching quality and operational pilot

- [ ] Build a representative, privacy-reviewed labelled campus evaluation set.
- [ ] Measure top-k retrieval, false positives, missed matches, and subgroup/category performance; do not call scores ownership probabilities.
- [ ] Test mobile layouts and keyboard/screen-reader flows on real devices.
- [ ] Confirm campus office procedures for intake, storage, sensitive items, disputes, and physical handover.
- [ ] Run a supervised pilot with synthetic or approved test data and record acceptance criteria before scaling.

## Current known limitations

- PostgreSQL support is implemented through a compatibility adapter and needs ongoing dialect coverage and concurrency/load testing. A local development service and production-oriented container configuration are provided; no hosted production database has been provisioned.
- Existing SQLite data is not automatically migrated at startup; an explicit utility is available but has not been rehearsed on the production dataset.
- Image/evidence files remain filesystem-backed. Production Compose provides a persistent volume, but coordinated off-host backup and restoration must be verified.
- Matching benchmark data is small and synthetic; it is not evidence of real-campus accuracy.
- The migration ledger records the legacy bootstrap baseline and applies versioned forward migrations for new changes; older additive compatibility updates still run in the legacy bootstrap, and each future migration needs an explicit recovery plan.
- The visual pass only slightly reduces shadow, radius, and ambient contrast; it does not change product navigation or workflows.
- A passing CI run is not a security audit, load test, backup/restore test, live deployment verification, or production-readiness certification.
