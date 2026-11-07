# LostLink Backend Architecture

## Purpose

This describes the actual modular layout of the LostLink prototype. The refactor preserves existing API URLs and workflow behaviour while separating route handlers from infrastructure and domain services.

## Project layout

- app/main.py — FastAPI composition root, session middleware, baseline Origin/Referer checks, browser security headers, health endpoints, static files, router registration and DB initialisation.
- app/schemas.py — Pydantic request-body validation.
- app/matching.py — explainable lost/found matching, category-aware signal weighting, cached MiniLM text similarity and optional CLIP similarity.
- app/services/embedding_cache.py — bounded, model-revision-aware persistence for text and CLIP embeddings; stores content hashes and vectors, not raw descriptions or images.
- app/services/image_enrichment.py — opt-in BLIP photo captioning and deterministic keyword/attribute extraction; generated fields remain separate from student-authored text.
- app/services/category_classification.py — advisory MiniLM/keyword category suggestions; the report owner confirms the final category.
- app/core/config.py — environment settings, directories and shared category/privacy policy.
- app/core/database.py — SQLite lifecycle plus optional PostgreSQL connection pooling/compatibility adapter, schema migrations, audit events and demo seed data.
- app/core/images.py — image validation, canonical JPEG conversion, SHA-256/perceptual fingerprints and watermarking.
- app/core/security.py — PBKDF2 password hash and verification helpers.
- app/core/runtime.py — compatibility facade re-exporting shared helpers to route modules and legacy imports.
- app/api/dependencies.py — current-session validation and office-role checks.
- app/api/routes/auth.py — home/config, login, logout and current-user endpoints.
- app/api/routes/reports.py — report create/search/close, report photos, match lookup, office intake and storage updates.
- app/api/routes/claims.py — claims, private evidence images, decisions, disputes and physical handover.
- app/api/routes/engagement.py — notifications, activity, leaderboard, certificates and office summary.
- app/services/reports.py — report serialisation, location labels and visibility/risk helpers.
- app/services/notifications.py — in-app notifications and possible-match alerts.
- app/services/rewards.py — idempotent contribution points and milestone certificate PDFs.
- app/static/ — frontend HTML, JavaScript and CSS.
- tests/ — matching, rewards and full workflow checks.
- scripts/run-demo.ps1 — local student/office demo launcher.

## Request flow and dependency direction

1. app/main.py creates the FastAPI instance, applies Starlette session middleware, mounts static assets and registers four routers.
2. app/schemas.py validates login, report, claim, evidence, decision, dispute, intake, storage and handover request bodies.
3. The selected route calls shared domain helpers and the SQLite layer.
4. app/core/config.py provides environment-backed settings and privacy/category constants; app/core/database.py handles transactions, migrations and audit writes.
5. app/core/images.py and app/core/security.py handle image/password primitives. app/api/dependencies.py enforces sessions and office-only actions.
6. app/services owns report visibility/serialization, notification side effects and reward/certificate side effects.
7. app/matching.py ranks candidates from available text/category/location/time signals and optional learned-model signals. MiniLM and CLIP vectors are read from and written to the persistent cache using SHA-256 content keys and model/revision/modality namespaces. Candidate ranking batches uncached CLIP photos in groups of 16, then reuses the vectors across candidate comparisons; cache failures degrade to live inference rather than failing matching. Category-specific ranking profiles change the relative contribution of text, image, category, location and time; missing signals are removed and the remaining weights are renormalised.

## Main boundaries

### Database and configuration

The SQLite connection context manager commits on success, rolls back on exceptions, enables foreign keys and always closes the connection. When DATABASE_URL is set, a bounded psycopg pool and a limited SQL compatibility adapter are used instead. Initialisation creates tables/indexes, applies additive migrations, backfills hashes for legacy report images where possible and seeds examples only when DEMO_MODE=true. The adapter is not a replacement for versioned migrations or dialect-specific tests.

### Image and security utilities

Images are limited to supported formats, verified, EXIF-oriented, resized, re-encoded as JPEG and fingerprinted. Re-encoding removes original metadata. Exact SHA-256 plus perceptual similarity checks discourage reuse of report/claim images. Labelled previews discourage casual copying but cannot prevent screenshots.

Password helpers use PBKDF2-HMAC-SHA256 with a random salt and 180,000 iterations. Session middleware uses strict SameSite cookies, an eight-hour lifetime and the SESSION_HTTPS_ONLY option. Unsafe API mutations reject a supplied Origin/Referer whose host differs from the request Host; this is a baseline browser control and still requires reverse-proxy/deployment verification. Responses include baseline anti-sniffing, frame, referrer and permissions headers. Liveness and database-readiness endpoints are available at /health/live and /health/ready.

### Domain services

- reports.py keeps public/student serialisation separate from internal/office serialisation. Tag IDs, storage locations, private owner clues and risk details are only returned internally.
- notifications.py uses unique event keys to de-duplicate notifications, and ranks candidates to notify students of possible matches. A match is a lead, not ownership proof.
- rewards.py awards points only for configured verified events, writes idempotent ledger entries, audits awards and generates threshold certificates.
- matching.py uses a deterministic lexical baseline by default, optional Sentence Transformers/CLIP inference, and category-aware signal weights. Electronics place more weight on visual similarity; identity documents place more weight on text and contextual signals. Weights are renormalised over signals actually available for each pair.

### API route ownership

- auth.py: GET /, GET /api/config, login/logout/me.
- reports.py: report list/search/create/close, report image upload/read, match list, physical intake and storage update.
- claims.py: claim create/list, evidence upload/read/update, dispute, decision and handover.
- engagement.py: notification read/list, activity, leaderboard, certificate download, office dashboard summary.

### Compatibility facade

app/core/runtime.py currently re-exports existing imports so the frontend/API behaviour and older tests remain compatible during the extraction. New functionality should be added to the owning module and imported directly rather than growing this facade further.

## Preserved invariants

- Found items remain outside student search until staff confirm physical receipt and tagging.
- Claim evidence is private to the claimant and office role.
- Private custody/verification information is not returned in public report responses.
- Match suggestions never approve claims; verified physical handover is a separate step.
- Notification and reward event keys prevent duplicate side effects.
- All existing /api/... paths are preserved.

## AI services and limitations

MiniLM report-text embeddings and optional CLIP image/text embeddings are persisted in `ai_embedding_cache`. Text uses SHA-256 of normalized text; images use SHA-256 of the canonical image bytes. Separate model/revision/modality namespaces prevent collisions. The cache retains at most 20,000 recently updated vectors per model namespace. `SEMANTIC_MODEL_REVISION` and `CLIP_MODEL_REVISION` can be incremented to invalidate vectors after a model or tokenizer change. Cache read/write errors are treated as misses, so model inference and lexical fallback remain available. Raw report descriptions and image bytes are not stored in this cache; vectors remain derived data and should be covered by the institution data-retention policy.

Image enrichment is implemented as an opt-in service. The report-photo workflow can request a BLIP caption, derive keywords and visible colour/material/shape terms, and persist them in dedicated AI fields. The fields contribute to matching and keyword search but never overwrite student-authored text. Model output is a suggestion, not verified evidence; model weights are large, so enable it only after deployment memory/latency testing.


## Matching evaluation

`tests/data/matching_benchmark.json` contains 15 manually labelled synthetic retrieval scenarios with one relevant candidate and five distractors per query. `scripts/evaluate_matching.py` reports macro Precision@K, Recall@K, HitRate@K, MRR, category breakdowns, and candidate-pair false-positive diagnostics at a configurable threshold for the lexical baseline and, when available, Sentence Transformers. The threshold is diagnostic only and never authorises ownership or claim approval. These synthetic figures are a development sanity check only; they do not estimate performance on real campus reports. The harness accepts another labelled JSON dataset through `--dataset`; real records must be anonymised, consented and governed by the institution's retention policy.


## AI category suggestion

The authenticated `POST /api/reports/category-suggestion` endpoint accepts only public item descriptors (title, description, brand, colour and visible characteristics). When `USE_SEMANTIC_MODEL=true`, the existing MiniLM model compares the report text with fixed category descriptions. If model loading or inference is unavailable, a deterministic keyword classifier is used. The response contains ranked suggestions and the inference engine; it is not persisted. The report form displays the result and requires an explicit student action to apply it. Low-information descriptions return an uncertain result instead of forcing a category. No private claim evidence is read by this service.
