# LostLink Engineering Guidelines

These rules apply to all implementation, review, testing, and maintenance work in this repository. They combine Karpathy's problem-solving principles with the project's Ponytail Ultra engineering safeguards. If guidance overlaps, use the more specific requirement; do not duplicate mechanisms or add process for its own sake.

## 1. Think before coding (Karpathy)
- Inspect the relevant code, callers, configuration, tests, migrations, and current branch state before editing.
- State the actual defect or user outcome being addressed. Identify constraints and likely regressions first.
- Do not assume a requested implementation is the right solution; explain material trade-offs before making broad changes.

## 2. Prefer the simplest complete solution (Karpathy)
- Choose the smallest design that fully satisfies the requirement and is supportable in production.
- Avoid unnecessary abstractions, dependencies, frameworks, duplicate services, speculative features, and rewrites.
- Complete the end-to-end behaviour; do not leave placeholder paths, fake success, dead code, or TODOs for required functionality.

## 3. Make surgical changes (Karpathy)
- Preserve working architecture, APIs, data, configuration, security boundaries, and backwards compatibility unless a deliberate migration is required.
- Reuse existing utilities and patterns when they are sound. Do not replace a working implementation wholesale to add one feature.
- Keep changes focused and reviewable. Separate unrelated work into separate commits or pull requests.

## 4. Define and verify measurable success (Karpathy)
- Define observable acceptance criteria before implementation.
- Add or update tests for normal behaviour, edge cases, failure paths, security, and regressions.
- Run relevant checks, then the broadest practical test suite. Fix failures caused by the change.
- Report exactly what was run and its result. Never claim a test, integration, deployment, or feature works unless it was actually verified.

## 5. Ponytail Ultra implementation safeguards
- Finish the whole requested workflow, including validation, authorization, persistence, error handling, user-visible feedback, and operational behaviour.
- Review security and privacy boundaries, input validation, resource limits, accessibility where applicable, and safe defaults.
- Check affected callers, API contracts, environment variables, migrations, deployment configuration, and compatibility.
- Avoid hidden fallbacks that silently weaken security or data integrity. Fail closed where required.
- Update focused documentation when behaviour, setup, configuration, or operational expectations change.
- Review the diff for unnecessary complexity, duplication, unrelated edits, and incomplete paths before calling work complete.

## 6. Repository workflow and authority
- Work on a focused feature or integration branch; inspect the latest base before starting.
- Do not force-push, merge pull requests, or deploy without explicit user approval.
- Never merge a stale/diverged branch blindly. Reconcile it against current main and validate the combined result.
- Prefer preserving the best existing implementation over choosing code merely because it is newer or comes from a particular branch.
- For competing implementations, compare correctness, security, maintainability, performance, compatibility, test coverage, and operational cost. Keep one coherent implementation and port only missing capabilities.
- Distinguish implemented, tested, integration-tested, and deployed status in all reports.

## 7. Definition of done
A change is complete only when:
1. Its acceptance criteria are met.
2. The relevant end-to-end path is implemented.
3. Regression and failure-mode tests are added or updated and pass.
4. Security, compatibility, migration, and configuration impacts are addressed.
5. Documentation and the final change summary accurately describe the result.
6. No required behaviour is left as a placeholder or unverified claim.
