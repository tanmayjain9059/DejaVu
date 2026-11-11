# Liquid Glass port verification

Source of truth: unified `bcd8ba3be9fc22799b9394d889c20060db911023`.
Visual source: PR #21 `fd752d87fe6ae0355a555b93d4e6f10be724589a`.

Only the allowed frontend, frontend-test, audit and new documentation paths changed. No backend, deployment configuration, database schema, matching logic, authentication or privacy contract was changed. No branch/tag was deleted; no PR was opened. PR #21 must not be merged wholesale: its older application code removes current workflows.

## Changes

- Ported the cool blue glass palette and material styling while retaining unified's selectors and responsive workflow layouts.
- Added the PR's CSS aurora and a glass public hero. Preserved the public navigation, login, Lost, Found, browse, track, claim, evidence, privacy and office screens.
- Added a CSS glass navigation indicator with a small spring controller, badge/text/visibility remeasurement, mobile scrolling and active-item centering. Reduced-motion users get immediate placement and a stationary aurora.
- Replaced decorative glyphs with inline SVG; close buttons share the same X and accessible `Close` name. No external scripts added.
- Added previously missing workflow class rules, readable inputs and shared privacy dialog styling.
- Preserved the existing AI helper label/icon across requests.

## Baseline and final checks

| Check | Baseline | Final |
| --- | ---: | ---: |
| Unique HTML IDs | 347 | 347 |
| Input/select/textarea controls | 114 | 114 |
| API path expressions in app.js | 36 | 36 |
| Inventoried CSS class names | 315 | 320 |
| Frontend contract test functions | 41 | 44 |
| Full pytest suite | 189 passed | 192 passed |
| Additional pytest subtests | 4 passed | 4 passed |
| External/local script source list | 2 existing sources | same 2 |

Zero missing baseline IDs, API expressions, CSS classes or test functions. All 347 ID-bearing elements retain their original tag and non-style attributes. All 114 controls retain their attributes, including names, types, validation and consent controls. All 100 original named JS functions remain. Dynamic matching-strength classes are expanded from the backend enum and UI fallback for the class check. Inventories include JS class attributes, className assignments and classList operations.

The existing palette test keeps its original function name for traceability, but now checks the requested blue theme, rejects the obsolete beige primary colors, and asserts glass coverage across report, office, browse and dialog surfaces. No test was deleted. Added regressions execute the actual navbar controller with Node and check badge resizing, spring settling, resize handling, reduced motion and hiding; separate contracts cover accessible close icons and decorative aurora.

Each implementation commit passed the full SQLite pytest suite (189 before added regressions; 192 afterward). Final suite: 10 existing dependency/deprecation warnings, no skips. Node syntax, Python compilation, `git diff --check`, preservation checks and allowed-path checks passed. Baseline/final outputs and verification scripts are recorded in `/tmp` for this workspace session.

## Browser and database limitations

**The manual acceptance checklist is not yet verified.** Playwright is installed, but local Chromium fails before loading a page: `socket() failed: Operation not permitted` in `ProcessSingleton`. The environment disallows Unix sockets. An escalated launch was rejected by the environment approval policy. Installing Playwright's headless shell also failed (truncated/invalid browser archive). The audit launch failure is in `/tmp/layout-audit.txt`; it is not a passing audit or a UI failure.

The existing audit keeps `#publicHomeContent`, adds 390px and 1280px alongside 320/375/768/1440, and now asserts spring-indicator geometry before and after a temporary badge change. `PLAYWRIGHT_CHROMIUM_EXECUTABLE` optionally selects an installed browser; CI uses the default Playwright browser. The existing GitHub workflows run the browser audit on pushes to unified.

| Requested browser check (390px and 1280px) | Local result |
| --- | --- |
| Lost submit, success, reference | Not run: browser launch blocked |
| Found submit | Not run: browser launch blocked |
| Browse/search results, empty state, error recovery | Not run: browser launch blocked |
| Track, matches, close, evidence | Not run: browser launch blocked |
| Claim with secret; field validation | Not run: browser launch blocked |
| Privacy action and export | Not run: browser launch blocked |
| Office login, claims and handover queues | Not run: browser launch blocked |
| Spring, badges, mobile overflow | Controller unit regression passed; browser geometry unverified |
| Browser console | Unverified: no page loaded |

Local PostgreSQL binaries are unavailable, so the PostgreSQL subset was not run locally. SQLite tests exercise the existing backend workflows, but are not a substitute for the requested full browser or PostgreSQL checks.

## PR features deliberately not imported

- Unified has no profile-edit form or profile-update endpoint (auth offers login/logout/config/me). A phone-save feature cannot be added truthfully within this frontend-only scope. Existing public report/claim contact-phone payloads are preserved. No local-only profile saving is added.
- Unified has no role-switch buttons; public students do not log in. Its existing office entry and dashboard-return wording are preserved. No student switch or authentication is reintroduced.
- PR #21's rewrites, reduced tests, planning files and browser-storage tracking credentials are not imported. Tracking secrets remain in memory and request headers as before.
- Component licence checks and notices are in [THIRD_PARTY.md](THIRD_PARTY.md): aurora/navbar MIT; icons ISC/MIT. Fonts and script sources remain unchanged.
