# LostLink — Campus Lost-and-Found Workflow

A campus lost-and-found platform with intelligent item matching and verified physical handover.

[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![MiniLM](https://img.shields.io/badge/MiniLM-L6--v2-FFD21E?logo=huggingface&logoColor=black)](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)
[![CLIP](https://img.shields.io/badge/CLIP-ViT--B%2F32-412991?logo=openai&logoColor=white)](https://huggingface.co/openai/clip-vit-base-patch32)
[![SQLite](https://img.shields.io/badge/SQLite-003B57?logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![Python](https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white)](https://www.python.org/)

<img width="958" height="479" alt="image" src="https://github.com/user-attachments/assets/7ec20fbf-7df0-4c68-9b04-0ba9badf81d5" />


# 🔗 LostLink — Lost & Found Platform

<p align="center">
  <a href="https://lostlink-q8ft.onrender.com/" target="_blank">
    <img src="https://img.shields.io/badge/🚀_LIVE_DEMO-Click_Here_to_Try-2ea44f?style=for-the-badge" alt="Live Demo"/>
  </a>
</p>

<p align="center">
  <b>Find what you've lost. Return what you've found.</b>
</p>

### 🌐 Live Application

**Try LostLink now:** https://lostlink-q8ft.onrender.com/

Explore the platform and experience how LostLink helps connect people with their lost belongings.


LostLink is a web application for managing campus lost property from initial report through verified physical return. Students submit lost or found reports and receive possible-match suggestions. Authorised office staff manage physical intake, item tagging and storage, private ownership-claim review, disputes and recorded handover.

**The central rule is that a match is a lead, not proof of ownership.** A found item becomes visible for student discovery only after authorised staff confirm physical receipt and record custody. Claim approval and physical handover are separate steps; the application requires the exact physical LostLink Tag ID and identity/handover confirmations before recording a return.

> **Project status:** working standalone prototype. It uses SQLite and local image files. It has not yet been validated for production-scale load or connected to an institutional identity provider.

## Contents

- [Problem and goals](#problem-and-goals)
- [Features](#features)
- [End-to-end workflow](#end-to-end-workflow)
- [Architecture](#architecture)
- [Repository structure](#repository-structure)
- [Matching engine](#matching-engine)
- [Security and privacy](#security-and-privacy)
- [HTTP API reference](#http-api-reference)
- [Technology stack](#technology-stack)
- [Local installation](#local-installation)
- [Configuration](#configuration)
- [External database (PostgreSQL)](#external-database-postgresql)
- [Testing and matching evaluation](#testing-and-matching-evaluation)
- [Limitations and production considerations](#limitations-and-production-considerations)
- [Product-readiness checklist](docs/PRODUCT_READINESS.md)

## Problem and goals

Lost-and-found information is often scattered across group chats, notices and informal desks. Descriptions can be incomplete, students may not see a relevant announcement, and a claim or image similarity alone cannot establish ownership. Staff also need to know where a physical item is stored and whether it was actually returned.

LostLink brings the process into one traceable workflow:

1. Capture structured lost and found reports.
2. Keep found-item listings hidden until staff confirm physical receipt.
3. Rank possible matches and explain which recorded signals overlap.
4. Keep claim explanations and evidence private to the claimant and authorised office staff.
5. Track the item's Tag ID, real storage location, claim decision and physical handover.
6. Record audit events and award contribution points only for defined verified actions.

## Features

### Student-facing features

- Create a lost-item report or a found-item report through separate guided paths.
- Record title, description, category, approximate occurrence time and campus location. Brand, primary colour, visible characteristics and a photo can add detail.
- Browse and filter available found items by keywords, category, block, room and date.
- Open item details and suggested-match explanations.
- Receive in-app notifications about report status and possible matches.
- Submit a claim with a private explanation and evidence categories; attach a private supporting image.
- Track claim state, respond when more evidence is requested and request one formal review after a rejection.
- View personal activity, verified contribution points, leaderboard information and milestone certificate PDFs.

### Office-facing features

- Review found-item reports awaiting physical intake.
- Confirm actual receipt of the object before making the report available to students.
- Record the actual room, cabinet, shelf or other storage location; capture private verification information; set value and sensitivity fields; and assign a unique LostLink Tag ID.
- Update a stored item's location and retain the movement in the audit history.
- Review private claim evidence and checklist results; approve, reject, request more evidence or mark a claim disputed.
- Resolve competing claims rather than treating the first submitted claim as automatically valid.
- Retrieve the object from the recorded location, check the exact physical Tag ID and claimant identity, confirm actual handover, and record the return.
- Inspect office summary information and review in-app notifications.

### Recognition and accountability

The prototype records a reward ledger. The configured rules award 10 points when a student-submitted found item is physically received and tagged by office staff, and 5 points when an eligible verified return is recorded. Unique event keys help prevent duplicate awards. Milestone certificates are generated at configured thresholds of 20, 50 and 100 points.

These are prototype recognition features; the generated certificates are not official college credentials.

## End-to-end workflow

    STUDENT REPORTS LOST ITEM ───────────────────────────────┐
                                                            │
    STUDENT REPORTS FOUND ITEM                              │
              │                                             │
              ▼                                             │
    OFFICE CONFIRMS PHYSICAL RECEIPT                        │
              │                                             │
              ▼                                             │
    RECORD PRIVATE DETAILS AND ACTUAL STORAGE LOCATION     │
              │                                             │
              ▼                                             │
    ASSIGN PHYSICAL LOSTLINK TAG ID                         │
              │                                             │
              └───────────────► AVAILABLE FOUND INVENTORY ◄─┘
                                      │
                                      ▼
                           SEARCH AND RANK CANDIDATES
                                      │
                                      ▼
                             STUDENT SUBMITS CLAIM
                                      │
                                      ▼
                        OFFICE REVIEWS EVIDENCE AND IDENTITY
                                      │
                          ┌───────────┴────────────┐
                          │                        │
                          ▼                        ▼
                  MORE EVIDENCE / DISPUTE       APPROVED
                          │                        │
                          └──────► REVIEW          ▼
                                       RETRIEVE PHYSICAL ITEM
                                                  │
                                                  ▼
                                     VERIFY EXACT TAG ID AND IDENTITY
                                                  │
                                                  ▼
                                      CONFIRM ACTUAL HANDOVER
                                                  │
                                                  ▼
                                       AUDIT, STATUS AND NOTIFICATIONS

### Report lifecycle

| Situation | Behaviour |
|---|---|
| Lost report is submitted | Starts as an open search record and may receive possible-match suggestions. |
| Found report is submitted | Starts in an awaiting-intake state and is not visible in the student found-item search. |
| Office confirms intake | Staff record actual storage and private verification details, assign a Tag ID, and make the found item available. |
| Stored item is moved | Office staff update the location; the change is audited. |
| Claim is created | Private evidence is linked to a claim for authorised office review. |
| More evidence is required or a dispute exists | The claim stays in the review process; the item is not automatically released. |
| Claim is approved | It becomes eligible for collection but is not yet marked returned. |
| Physical handover is confirmed | The office checks the physical tag and claimant identity, records handover and marks the item returned. |
| Student closes or withdraws an eligible report | Closure rules apply; a found item cannot be withdrawn by the student after the office has accepted physical custody. |

The database uses explicit report and claim status values to enforce these transitions. The API performs validation and role checks on state-changing operations.

## Architecture

LostLink uses a single FastAPI application composed of route groups, shared infrastructure utilities and domain services.

    Browser: public student experience and office console
        HTML + CSS + vanilla JavaScript
                         │ HTTP / JSON
                         ▼
    FastAPI application (app/main.py)
        ├── Session middleware and role dependencies
        ├── Authentication routes
        ├── Report/search/photo/intake/storage routes
        ├── Claim/evidence/decision/dispute/handover routes
        ├── Notification/activity/reward/certificate routes
        ├── Matching engine
        └── Report, notification and reward services
                         │
             ┌───────────┴───────────┐
             ▼                       ▼
    SQLite database           Local image directory
        ├── Users                  ├── Report images
        ├── Reports                └── Private claim evidence
        ├── Claims
        ├── Notifications
        ├── Storage and Tag IDs
        ├── Handover records
        ├── Reward ledger
        ├── Certificates
        └── Audit events

### Module responsibilities

| Component | Responsibility |
|---|---|
| <code>app/main.py</code> | Creates the FastAPI application, validates the session-secret configuration, adds session middleware, mounts static assets, registers routers and initialises the database. |
| <code>app/api/dependencies.py</code> | Resolves the current session and enforces office-role access where required. |
| <code>app/api/routes/auth.py</code> | Login, logout, current-user and public app configuration endpoints. |
| <code>app/api/routes/reports.py</code> | Report creation/search/closure, report photos, candidate matching, office intake and storage updates. |
| <code>app/api/routes/claims.py</code> | Claim creation/listing, private evidence, office decisions, disputes and physical handover. |
| <code>app/api/routes/engagement.py</code> | Notifications, activity, leaderboard, certificate downloads and office summary. |
| <code>app/core/config.py</code> | Environment configuration, data paths, categories, sensitivity levels and workflow constants. |
| <code>app/core/database.py</code> | SQLite connections, schema creation, additive migrations, indexes, transactions, audit writing and optional demo seeding. |
| <code>app/core/images.py</code> | Image validation/canonicalisation, hashing, perceptual fingerprints and watermarked student previews. |
| <code>app/core/security.py</code> | Password hashing and verification. |
| <code>app/services/auth.py</code> | Persistent login-failure tracking and temporary lockout calculations. |
| <code>app/services/reports.py</code> | Report serialisation, role-aware response filtering and related report helpers. |
| <code>app/services/notifications.py</code> | In-app notifications and possible-match notification logic. |
| <code>app/services/rewards.py</code> | Idempotent verified-contribution points, reward ledger and certificate generation. |
| <code>app/matching.py</code> | Candidate scoring, optional ML model loading, ranking and explanation signals. |
| <code>app/schemas.py</code> | Pydantic request models and field constraints. |
| <code>app/static/</code> | Frontend HTML, CSS and JavaScript. |

More implementation notes are available in [Architecture.md](Architecture.md).

## Repository structure

    DejaVu/
    ├── .env.example
    ├── .github/workflows/lostlink-checks.yml
    ├── Architecture.md
    ├── README.md
    ├── app/
    │   ├── main.py
    │   ├── matching.py
    │   ├── schemas.py
    │   ├── api/
    │   │   ├── dependencies.py
    │   │   └── routes/
    │   │       ├── auth.py
    │   │       ├── reports.py
    │   │       ├── claims.py
    │   │       └── engagement.py
    │   ├── core/
    │   │   ├── config.py
    │   │   ├── database.py
    │   │   ├── images.py
    │   │   ├── security.py
    │   │   └── runtime.py
    │   ├── services/
    │   │   ├── auth.py
    │   │   ├── reports.py
    │   │   ├── notifications.py
    │   │   └── rewards.py
    │   └── static/
    │       ├── index.html
    │       ├── app.js
    │       └── styles.css
    ├── scripts/
    │   ├── run-demo.ps1
    │   └── evaluate_matching.py
    ├── tests/
    │   ├── data/matching_benchmark.json
    │   ├── test_frontend_contract.py
    │   ├── test_matching.py
    │   ├── test_matching_benchmark.py
    │   ├── test_rewards.py
    │   └── test_workflow.py
    ├── requirements.txt
    ├── requirements-dev.txt
    └── requirements-ml.txt

The local runtime creates the <code>data/</code> directory for the SQLite database and uploaded images. This runtime data is ignored by Git.

## Matching engine

LostLink is designed to work without an external AI service. The deterministic lexical baseline is the default; pretrained models are optional and disabled by default.

### Baseline text similarity

The lexical baseline:
1. Converts text to lowercase and tokenises letters/numbers.
2. Removes common stop words.
3. Normalises selected synonyms, for example “backpack” and “rucksack” to “bag”, and “navy” to “blue”.
4. Calculates Jaccard token overlap, sequence similarity using Python's <code>difflib.SequenceMatcher</code>, and overlap on selected distinguishing details such as colours, scratches, stickers, zippers, logos and cases.
5. Combines these parts as: 55% Jaccard overlap, 30% sequence similarity and 15% distinguishing-detail overlap.

This calculation is deterministic and does not require network access or model weights.

### Structured signals and ranking

Candidate comparison may use:
- Description text assembled from title, description, brand, primary colour, visible features and category.
- Category agreement.
- Location agreement using block, floor, room and area.
- Difference between the reported occurrence times.
- Optional image similarity if CLIP is enabled and image files are available.

LostLink now uses category-aware ranking profiles rather than one fixed set of weights. Electronics give more weight to visual similarity; identity documents emphasise text and contextual signals; bags, clothing and accessories use a balanced text/image profile; keys/access cards increase location relevance; stationery gives more weight to text. Missing signals are omitted and the remaining weights are normalised for each candidate pair. These are ranking weights, not calibrated probabilities of ownership. The profiles are initial heuristics and must be tuned against a representative labelled campus dataset before operational use.

The report matching endpoint uses bounded two-tier retrieval: up to 75% of the configured shortlist is drawn from the lost report's category and the remainder from cross-category/relevant-location candidates. The default shortlist is 2,000 records (`MATCHING_CANDIDATE_LIMIT`, configurable from 100 to 10,000), selected through composite indexes and then ranked by the existing category-aware lexical/MiniLM/CLIP pipeline. This removes the old 500-record cutoff without loading the entire report corpus into application memory. It is still a bounded retrieval strategy, not a guarantee of exhaustive full-corpus recall; measure retrieval recall and query latency on an approved campus dataset before increasing the limit.

### Optional pretrained models

| Model | Purpose | Enablement |
|---|---|---|
| <code>sentence-transformers/all-MiniLM-L6-v2</code> | Creates sentence embeddings to compare the semantic similarity of report text. | Install <code>requirements-ml.txt</code> and set <code>USE_SEMANTIC_MODEL=true</code>. |
| <code>openai/clip-vit-base-patch32</code> | Compares two item photos, or compares an available photo with the opposite report's text when only one image is present. | Install ML dependencies and set <code>USE_CLIP_MODEL=true</code>. |
| <code>Salesforce/blip-image-captioning-base</code> | Generates an image caption; deterministic post-processing extracts searchable keywords and visible colour/material/shape terms. | Install <code>requirements-ml.txt</code> and set <code>USE_IMAGE_ENRICHMENT=true</code>. |

Semantic embeddings are compared using cosine similarity. When MiniLM is enabled, LostLink encodes the lost report and the candidate descriptions in one batch for each ranking request. The model-based ranking runs in a worker thread so CPU inference does not block the FastAPI event loop. In-app notification heuristics deliberately use the lexical baseline while the database write transaction is open; the full semantic/visual ranking is shown in the match view. CLIP still evaluates available photos per candidate, so its memory and latency must be measured before enabling it on a constrained host.

If an optional model cannot load or inference fails, the matcher falls back to the deterministic text baseline or omits the unavailable image signal. Optional inference consumes additional memory and CPU/GPU resources; models should not be described as active unless their flags are enabled and loading has been verified.

BLIP image captioning and keyword/attribute extraction are implemented as an optional, opt-in report-photo enrichment path. The caption and extracted terms are stored in dedicated AI fields and contribute to later candidate matching; they never overwrite student-authored descriptions. Treat them as suggestions and verify them against the actual photo. CLIP similarity remains a separate visual comparison model.

### Synthetic retrieval benchmark

The repository includes 15 manually labelled synthetic scenarios. Each scenario contains one relevant candidate and five distractors, for 90 candidate pairs.

A recorded development evaluation produced the following retrieval measurements:

| Metric | Lexical baseline | Sentence Transformers |
|---|---:|---:|
| Top-1 hit rate | 80.0% (12 of 15) | 93.3% (14 of 15) |
| Top-3 hit rate | 100% (15 of 15) | 100% (15 of 15) |
| Mean reciprocal rank | 0.8778 | 0.9667 |

These measurements are a small synthetic development check—not validated real-campus accuracy, a probability that a person owns an item, or a load test. The top-3 metric is already at the benchmark's ceiling. Before operational use, matching should be evaluated on a representative, privacy-reviewed labelled campus dataset with false positives, missed matches and top-k retrieval measured separately.

## Security and privacy

LostLink applies prototype-level controls to keep sensitive information out of public search and maintain a record of office actions.

### Authentication and authorisation
- Passwords are stored as PBKDF2-HMAC-SHA256 hashes with random salts and 180,000 iterations.
- Starlette session middleware signs session cookies, uses strict SameSite settings and an eight-hour maximum age.
- Failed login attempts are tracked by email and client address. Five invalid attempts within the configured window trigger a temporary lockout.
- Office operations are protected by server-side role checks; the frontend role selector is only a convenience for the local demo, not an identity provider.
- Set <code>SESSION_HTTPS_ONLY=true</code> when served over HTTPS. It remains false in the local example so localhost demo cookies work.

### Data minimisation and private fields
- Public/student report serialisation omits private Tag IDs, exact storage locations, private verification details and internal risk fields.
- Claim explanations and evidence are available only to the claimant and authorised office staff.
- Existing image routes require authenticated application access; public image upload and public image retrieval are not enabled yet.
- The legacy authenticated image serializer can watermark previews. Public image access is intentionally withheld until a case-token-scoped private-storage flow is implemented.

### Image processing and duplicate detection
- Uploads are capped at 5 MB and must pass image validation.
- Images are orientation-corrected, resized and re-encoded as canonical JPEGs, removing embedded image metadata.
- Exact SHA-256 hashes and perceptual hashes help identify duplicate or near-duplicate photos.
- Private claim evidence is stored separately from public report metadata and served through authorised endpoints.

### Auditability
Intake, storage changes, claim decisions, handovers and reward events are written into application records. Unique event keys are used to make selected side effects such as notifications and reward awards idempotent.

These are prototype protections. A production system still requires a security review, HTTPS and deployment hardening, request-origin/CSRF review, managed secrets, access-controlled backups, retention policy, monitoring and a documented incident process.

## HTTP API reference

All API paths below are served by FastAPI. Public student routes under `/api/public` require no session; tracking routes require a case-specific secret. Authenticated application routes are restricted to allowlisted office staff in production. Legacy account-owned student routes remain for historical compatibility and are not the public student interface. Request payloads are validated using Pydantic models.

### Authentication and configuration

| Method | Path | Purpose |
|---|---|---|
| GET | <code>/</code> | Serve the application interface. |
| GET | <code>/api/config</code> | Return public configuration including category/location examples and demo settings. |
| POST | <code>/api/login</code> | Authenticate an authorised local office account only. |
| POST | <code>/api/logout</code> | End the current session. |
| GET | <code>/api/me</code> | Return the authenticated office user's public account details. |

### Public student workflow (no login)

| Method | Path | Purpose |
|---|---|---|
| POST | <code>/api/public/reports</code> | Submit a Lost or Found report using roll-number attribution; returns a reference and one-time tracking secret. |
| GET | <code>/api/public/found</code> | Browse Found items only after office-confirmed physical intake. |
| GET | <code>/api/public/track/{reference}</code> | Track exactly one report or claim using its reference, roll number and <code>X-LostLink-Tracking-Secret</code>. |
| GET | <code>/api/public/reports/{reference}/matches</code> | Retrieve the existing bounded AI-ranked match suggestions for one token-authorised Lost report. |
| POST | <code>/api/public/found/{report_id}/claims</code> | Submit a claim with private evidence text. |
| POST | <code>/api/public/claims/{reference}/evidence</code> | Add evidence after an office request. |
| POST | <code>/api/public/cases/{reference}/close</code> | Close an eligible Lost report or withdraw a Found report before intake. |

The roll number is never an authentication credential and is never returned by public serializers. Every report and claim has an independent tracking secret; one case's secret cannot unlock another case. Public reports and claims are stored in the canonical <code>reports</code> and <code>claims</code> tables.

### Reports, photos and matching

| Method | Path | Purpose |
|---|---|---|
| GET | <code>/api/reports</code> | Office-only search/list for the authenticated console with supported filters and keyset pagination (`page_size` 1–100, opaque `cursor`, `next_cursor`, `has_more`). Public students use `GET /api/public/found` and token-scoped tracking instead. |
| POST | <code>/api/reports</code> | Legacy account-owned report creation; public students use `POST /api/public/reports`. |
| PUT | <code>/api/reports/{report_id}</code> | Edit public details while owner/office authorization and report workflow state permit it; every edit is audited. |
| POST | <code>/api/reports/{report_id}/close</code> | Close an eligible owned lost report or withdraw a found report before intake. |
| POST | <code>/api/reports/{report_id}/image</code> | Upload or replace a permitted report image. |
| GET | <code>/api/reports/{report_id}/image</code> | Retrieve an image subject to role, status and category checks. |
| GET | <code>/api/reports/{report_id}/matches</code> | Legacy authenticated matching route. Public students use the token-authorised `/api/public/reports/{reference}/matches` route. |
| POST | <code>/api/reports/{report_id}/intake</code> | Office-only: confirm physical receipt, record storage/verification data and assign the Tag ID. |
| POST | <code>/api/reports/{report_id}/storage</code> | Office-only: update the item's recorded storage location. |

Office claim pagination uses immutable `created_at ASC, id ASC` cursor ordering. The `queue` filter supports `active` (pending, disputed and more-evidence-needed), `handover` (approved for collection), `disputed`, `pending`, and `other`. The default `queue=all` view is chronological and includes a `priority_rank` field for display; it is not a cross-page disputed-first snapshot. Status changes can move a claim between filtered queues, so refresh the relevant queue after a decision. The office console consumes the API cursors with Load more controls. Public found-item browsing uses its separate bounded public endpoint. Office inventory can filter both `available` and `claim_approved` records in the same paginated query.

### Claims, evidence and handover

| Method | Path | Purpose |
|---|---|---|
| POST | <code>/api/claims</code> | Create a claim with a private explanation and evidence categories. |
| GET | <code>/api/claims</code> | Keyset-paginated claims (`page_size`, `cursor`, `next_cursor`, `has_more`). Office staff can select `queue=active`, `handover`, `disputed`, `pending`, or `other`; cursor ordering uses immutable creation time and ID, with `priority_rank` metadata. Production student requests do not use this authenticated route; public students use `/api/public/found/{report_id}/claims` and token-scoped tracking. |
| POST | <code>/api/claims/{claim_id}/evidence</code> | Update claim evidence text. |
| POST | <code>/api/claims/{claim_id}/evidence-image</code> | Upload private supporting evidence image. |
| GET | <code>/api/claims/{claim_id}/evidence-image</code> | Retrieve the evidence image subject to claimant/office access rules. |
| POST | <code>/api/claims/{claim_id}/dispute</code> | Submit an eligible claim review/dispute request. |
| POST | <code>/api/claims/{claim_id}/decision</code> | Office-only: request more evidence, approve, reject or mark disputed, with validation of required verification checks. |
| POST | <code>/api/claims/{claim_id}/handover</code> | Office-only: record physical handover after tag and identity confirmations. |

### Notifications, activity and rewards

| Method | Path | Purpose |
|---|---|---|
| GET | <code>/api/notifications</code> | List recent notifications and unread count for the signed-in user. |
| POST | <code>/api/notifications/{notification_id}/read</code> | Mark one owned notification read. |
| POST | <code>/api/notifications/read-all</code> | Mark the user's notifications read. |
| GET | <code>/api/activity/me</code> | Return the user's activity and verified contribution summary. |
| GET | <code>/api/leaderboard</code> | Return leaderboard information based on verified points. |
| GET | <code>/api/certificates/{certificate_id}/download</code> | Download an eligible milestone certificate PDF. |
| GET | <code>/api/office/summary</code> | Return the office dashboard summary. |

This is a route overview, not a replacement for endpoint schema validation. The authoritative request field limits and allowed values are defined in <code>app/schemas.py</code> and the route handlers.

## Technology stack

| Layer | Technology | Use |
|---|---|---|
| Application server | Python, FastAPI and Uvicorn | API routing and application hosting. |
| Request validation | Pydantic | Request payload validation and field length/range constraints. |
| Browser session | Starlette SessionMiddleware | Signed cookie-based sessions. |
| Database | SQLite and Python <code>sqlite3</code> | Prototype persistence, parameterised queries, foreign keys and transactions. |
| Password primitives | Python <code>hashlib</code> and <code>secrets</code> | PBKDF2 password hashing and constant-time verification comparison. |
| Image utilities | Pillow | Image verification, EXIF correction, resize/re-encoding and fingerprints. |
| PDF certificates | ReportLab | Generate downloadable milestone certificates. |
| Optional semantic model | Sentence Transformers | Text embeddings. |
| Optional visual model | Transformers, PyTorch and CLIP | Image-image or image-text similarity. |
| Frontend | HTML, CSS and vanilla JavaScript | Public student experience and authenticated office console. |
| Testing and CI | Python unittest, Node.js syntax check and GitHub Actions | Workflow, matching, rewards, frontend contract and import checks. |

## Prerequisites

Install these tools before setting up LostLink:

- **Python 3.11** (the version used by the project's CI checks).
- **Git** to clone the repository.
- **Node.js** (optional, only needed for the JavaScript syntax check).
- Windows 10/11 with PowerShell, or macOS with Terminal.

Check your Python version:

- Windows PowerShell: `py -3.11 --version`
- macOS Terminal: `python3.11 --version`

If Python 3.11 is not installed, install it from [python.org](https://www.python.org/downloads/). On Windows, enable the Python Launcher during installation. On macOS, make sure the `python3.11` command is available.

## Local installation

These instructions run LostLink locally in demo mode. They use SQLite and local uploads; no Supabase account, cloud VM or external database is required.

### 1. Clone the repository

Open PowerShell (Windows) or Terminal (macOS), then run:

```bash
git clone https://github.com/tanmayjain9059/DejaVu.git
cd DejaVu
```

If you have already cloned the repository, open a terminal in the repository folder and pull the latest changes from the branch you want to test.

### 2. Windows 10/11 — PowerShell

Run each command from the repository root.

**Create and activate the virtual environment:**

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell blocks virtual-environment activation, allow it for the current terminal session only, then activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

**Create your local environment file:**

```powershell
if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
}
```

If `.env` already exists, keep it; do not overwrite your local settings.

**Set a unique session secret:**

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Copy the generated value. Open `.env` in Notepad, replace the placeholder value on the `SESSION_SECRET=` line, and save the file. Do not add the generated secret to Git or share it.

**Start LostLink:**

```powershell
.\scripts\run-demo.ps1
```

The launcher checks the virtual environment and configuration, performs an application import check, creates the local data directories and starts Uvicorn. It opens the browser at [http://127.0.0.1:8000](http://127.0.0.1:8000). Keep PowerShell open while testing. Press **Ctrl+C** in that terminal to stop the server.

If port 8000 is already in use, stop the other LostLink/Uvicorn process before starting the demo again.

### 3. macOS — Terminal (zsh)

Run these commands from the repository root.

**Create and activate the virtual environment:**

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

**Create your local environment file:**

```bash
[ -f .env ] || cp .env.example .env
```

If `.env` already exists, keep it; do not overwrite your local settings.

**Generate a unique session secret:**

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Open the environment file:

```bash
nano .env
```

Replace the placeholder value on the `SESSION_SECRET=` line with the generated value. Save with **Ctrl+O**, press **Enter**, then exit with **Ctrl+X**. Do not commit or share this secret.

**Start LostLink:**

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser. Keep Terminal open while testing. Press **Ctrl+C** to stop the server.

### 4. Use the local demo

When `DEMO_MODE=true`, LostLink creates sample records and one local office demonstration account:

| Role | Email | Password |
|---|---|---|
| Office staff | `office@lostlink.local` | `office123` |

Students do not sign in. Open the landing page and use the public Lost/Found, Browse and Track actions. The office demo account is for local testing only; do not use it for a public deployment or expose the local development server to the internet.

By default, local data is stored in:

- SQLite database: `data/lostlink.db`
- Uploaded images and private evidence: `data/uploads/`

The `data/` directory and local `.env` file are excluded from Git.

### 5. Run the automated tests (Windows and macOS)

With the virtual environment activated, install the development dependencies:

```bash
python -m pip install -r requirements-dev.txt
```

Run the test suite from the repository root:

```bash
python -m compileall -q app tests
python -m unittest discover -s tests -v
```

If Node.js is installed, also check the frontend JavaScript syntax:

```bash
node --check app/static/app.js
```

The automated tests cover application workflows, matching, rewards and frontend contracts. Optional AI models are not required for the default local demo or baseline test suite.

### Troubleshooting

| Problem | What to do |
|---|---|
| `py` is not recognised (Windows) | Re-run the Python installer and enable the Python Launcher, or use the full Python 3.11 installation path. |
| `python3.11` is not found (macOS) | Install Python 3.11 from [python.org](https://www.python.org/downloads/) and reopen Terminal. |
| PowerShell says script execution is disabled | Run the process-scoped execution-policy command in the Windows instructions, then activate again. |
| `No module named ...` | Activate `.venv` and run `python -m pip install -r requirements.txt` again. |
| `SESSION_SECRET` placeholder/configuration error | Generate a new secret and replace the placeholder in the local `.env` file. |
| Port 8000 is already in use | Stop the previous server with Ctrl+C or stop the process using port 8000, then restart LostLink. |
| Browser cannot connect | Confirm Uvicorn is still running in the terminal and open `http://127.0.0.1:8000`. |

## Configuration

Values are loaded from environment variables and the local <code>.env</code> file.

| Variable | Purpose | Example/default behaviour |
|---|---|---|
| <code>DEMO_MODE</code> | Seed sample records and an office-only demo account. | Student demo credentials are not created; set <code>false</code> outside local demonstrations. |
| <code>SESSION_SECRET</code> | Secret used to sign session cookies. | Required; startup rejects an empty/placeholder secret and secrets shorter than 32 characters. Use a unique random secret. |
| <code>SESSION_HTTPS_ONLY</code> | Restrict session cookies to HTTPS. | <code>false</code> for localhost; set <code>true</code> for HTTPS deployment. |
| <code>DATABASE_PATH</code> | SQLite database file path. | Defaults to <code>data/lostlink.db</code> when <code>DATABASE_URL</code> is unset. |
| <code>DATABASE_URL</code> | Optional managed PostgreSQL connection URL. | Set a provider-issued <code>postgresql://</code> URL to use PostgreSQL; unset means SQLite. |
| <code>DATABASE_POOL_MAX_SIZE</code> | Maximum number of pooled PostgreSQL connections. | Optional; defaults to <code>5</code>, accepted range <code>1-20</code>. |
| <code>ALLOWED_HOSTS</code> | Comma-separated trusted HTTP hostnames. | Production Compose requires an explicit canonical hostname allowlist. |
| <code>REQUIRE_REQUEST_ORIGIN</code> | Require Origin or Referer for state-changing API requests. | Enabled in production Compose; keep disabled only for local non-browser tooling if needed. |
| <code>UPLOAD_DIR</code> | Directory for uploaded report images and private claim evidence. | Defaults to <code>data/uploads</code>. |
| <code>UPLOAD_STORAGE_BACKEND</code> | Private upload backend: <code>local</code> or <code>s3</code>. | Defaults to <code>local</code>; S3 requires a private bucket and credentials. |
| <code>S3_BUCKET</code>, <code>S3_PREFIX</code>, <code>S3_REGION</code>, <code>S3_ENDPOINT_URL</code> | S3-compatible private bucket and endpoint configuration. | Required bucket when S3 backend is selected; endpoint is optional for AWS. Store access credentials as deployment secrets. |
| <code>MATCHING_CANDIDATE_LIMIT</code> | Maximum bounded candidate shortlist for matching. | Defaults to <code>2000</code>; accepted range <code>100-10000</code>. |
| <code>USE_SEMANTIC_MODEL</code> | Enable semantic text embeddings and MiniLM category suggestions. | <code>false</code> unless dependencies/model are installed and explicitly enabled. |
| <code>SEMANTIC_MODEL</code> | Sentence Transformers model identifier. | <code>sentence-transformers/all-MiniLM-L6-v2</code>. |
| <code>SEMANTIC_MODEL_REVISION</code> | Explicit cache namespace revision; increment after changing model weights/tokenisation. | <code>default</code>. |
| <code>USE_CLIP_MODEL</code> | Enable CLIP-based image/image-text similarity. | <code>false</code> unless dependencies/model are installed and explicitly enabled. |
| <code>USE_IMAGE_ENRICHMENT</code> | Enable BLIP image captioning and report-photo keyword/attribute suggestions. | <code>false</code>; opt in after installing ML dependencies and assessing memory/latency. |
| <code>IMAGE_CAPTION_MODEL</code> | Hugging Face image-to-text model identifier. | <code>Salesforce/blip-image-captioning-base</code>. |
| <code>CLIP_MODEL</code> | CLIP model identifier. | <code>openai/clip-vit-base-patch32</code>. |

Keep secrets out of source control. The committed <code>.env.example</code> intentionally contains a placeholder and is not ready to use unchanged.


### External database (PostgreSQL)

LostLink can use a managed PostgreSQL database through <code>DATABASE_URL</code>. Leave that variable unset to continue using the local SQLite database. The application chooses PostgreSQL when a <code>postgresql://</code> or <code>postgres://</code> URL is provided.

1. Create a PostgreSQL database with a managed provider such as Neon, Supabase, or Render Postgres.
2. Add the provider's connection URL as the <code>DATABASE_URL</code> environment variable in the app host. Use the provider's TLS-enabled URL (usually includes <code>sslmode=require</code>) and store it as a secret; never commit real credentials.
3. Keep <code>SESSION_SECRET</code> unique and set <code>SESSION_HTTPS_ONLY=true</code> on HTTPS deployments.
4. Deploy with the standard start command: <code>uvicorn app.main:app --host 0.0.0.0 --port $PORT</code>.

The <code>psycopg</code> driver and its pool extra are installed from <code>requirements.txt</code>. LostLink reuses a bounded PostgreSQL connection pool (default maximum 5 connections, configurable with <code>DATABASE_POOL_MAX_SIZE</code>) and closes it during application shutdown. At startup LostLink creates missing tables and applies its existing additive schema updates. Use a new, dedicated database first, back it up before testing a populated database, and verify the workflow after connecting. This connection setting does not migrate existing SQLite records automatically. SQLite remains the default for local development.

**Important:** moving database records to PostgreSQL does not move image files. Report photos and private claim evidence still use <code>UPLOAD_DIR</code>; on ephemeral hosting those files can disappear on restart/redeploy. Before relying on uploads, configure persistent storage or a private object-storage service and test access controls. Do not use real student data for a public demo.

## Testing and matching evaluation

Install development dependencies:

       python -m pip install -r requirements-dev.txt

Run the automated checks from the repository root:

       python -m compileall -q app tests
       node --check app/static/app.js
       python -m unittest discover -s tests -v

The automated suite covers workflow behaviour, matching (including semantic embedding-cache hits and misses, and CLIP cache helpers), rewards and frontend selector/navigation contracts. GitHub Actions runs Python compilation, JavaScript syntax validation, the unit/workflow tests and application import. A separate optional job attempts semantic-model evaluation; it is non-blocking because model downloads can fail in automated environments.

Run the v1 labelled retrieval evaluation (baseline and optional MiniLM):

       python scripts/evaluate_matching.py

Choose metrics and save a JSON report:

       python scripts/evaluate_matching.py --ks 1,3,5 --score-threshold 0.72 --output reports/matching-evaluation.json

To require the actual Sentence Transformers model, install the optional model requirements:

       python -m pip install -r requirements-ml.txt
       python scripts/evaluate_matching.py --require-semantic-model

The default benchmark is <code>tests/data/matching_benchmark_v1.json</code>: 100 deterministic synthetic queries balanced across 10 categories, including multi-positive and no-match cases. The harness reports macro Precision@K, Recall@K (over queries with at least one relevant candidate), HitRate@K, MRR, category breakdowns, no-match rejection, and candidate-pair false-positive diagnostics. The configurable threshold is diagnostic only, never an ownership or claim-approval rule. These synthetic measurements are not campus or deployment accuracy. You can provide another labelled JSON file with <code>--dataset path/to/data.json</code>; keep it anonymised, consented and institutionally approved.

## Limitations and production considerations

Students use the public workflow documented in [Public student workflow](docs/PUBLIC_STUDENT_WORKFLOW.md). Public image/evidence upload is intentionally disabled until token-scoped access to private object storage is implemented.

The optional category-suggestion service analyses item names, descriptions and visible characteristics and returns advisory candidates. It is not currently exposed in the public student form. MiniLM inference shares the existing `USE_SEMANTIC_MODEL` setting; without it, a deterministic keyword fallback is used.

The current application is not a production deployment and has not been assigned a validated user-capacity or throughput claim.

- **Persistence:** SQLite remains the local default; a managed PostgreSQL database is available through <code>DATABASE_URL</code>. Production use still requires database backups, reviewed migrations, connection-capacity planning, query plans, transaction boundaries and uniqueness constraints.
- **File storage:** local filesystem storage remains the default. An S3-compatible private object-storage adapter is available through `UPLOAD_STORAGE_BACKEND=s3`; report photos and claim evidence are read only through authenticated API routes, never public object URLs. Set bucket public access blocking and encryption policies at the provider, then use `scripts/migrate_uploads_to_s3.py` (dry-run by default, `--apply` to copy) before switching a populated deployment. Keep local source files until bucket integrity and coordinated backup/restore have been independently verified. Local backup scripts do not back up S3 objects; enable provider versioning/replication or an approved separate backup process.
- **Matching scale:** retrieval ranks a bounded, indexed shortlist (default 2,000, configurable up to 10,000) rather than scanning the entire corpus in application memory. Same-category candidates receive 75% of the shortlist and cross-category/location candidates receive the remainder. This improves coverage beyond 500 records but does not establish exhaustive recall; tune shortlist composition and capacity from measured campus data. MiniLM text vectors are cached by content hash and model revision (20,000 most recently updated vectors per model). CLIP image and text vectors are cached separately by content hash and `CLIP_MODEL_REVISION` (20,000 vectors per model/modality namespace). Candidate ranking batches uncached CLIP photos in groups of 16 to bound inference memory.
- **AI dependency:** optional model loading and image inference need memory/CPU/GPU planning. The default lexical mode should remain an explicit fallback.
- **Student access:** students do not create accounts or sign in. A roll number is private attribution for a report/claim and must be checked against a physical college ID by office staff. It is not authentication. Supabase Auth is restricted to the exact campus-office allowlist; automated roster validation is not implemented.
- **Security operations:** production requires HTTPS, secure secret management, a session/CSRF review, tested backups, data retention and deletion policy, monitoring, incident handling and a formal security review.
- **Data governance:** private evidence and custody information need an institution-approved retention/access policy. Demonstration data should not be real student data.
- **Matching validation:** test on a labelled, representative dataset and measure false matches and missed matches before using the system operationally.
- **Physical custody:** the database does not use sensors to determine where an object is. Staff must physically store the item and update its recorded location.
- **AI category suggestions:** report text can be classified with MiniLM when enabled, with a deterministic keyword fallback. Suggestions are advisory and students confirm the final category.
- **Image enrichment:** BLIP image captioning and keyword generation are implemented as an opt-in feature; model quality and resource use still require campus-data evaluation.

## Related documentation

- [Architecture.md](Architecture.md) — module boundaries, request flow and implementation invariants.
- [Matching evaluation dataset guide](docs/MATCHING_EVALUATION_DATASET.md) — benchmark schema, metric definitions and governance for future real-data evaluation.

### Run PostgreSQL locally with Docker Compose

For local development without creating a hosted database, see [Local PostgreSQL setup](docs/LOCAL_POSTGRESQL.md). From the repository root, run `docker compose up -d postgres`, set the documented local `DATABASE_URL` in your untracked `.env`, then start LostLink normally. The Compose database listens only on localhost and stores data in a named Docker volume. The example password is development-only; do not expose this configuration to the public internet.

### Final split deployment (Supabase + Vercel + Render)

- [Supabase deployment runbook](docs/SUPABASE_DEPLOYMENT.md) — office-only Supabase Auth, PostgreSQL, private S3-compatible Storage, Vercel static frontend and Render FastAPI API.
- [Public student workflow contract](docs/PUBLIC_STUDENT_WORKFLOW.md) — no-login student reporting, token-scoped tracking, canonical report/claim integration and office verification.
- `vercel.json` and `scripts/build_vercel_frontend.py` configure the independent static frontend build. Set `BACKEND_ORIGIN` in Vercel.
- `render.yaml` defines the FastAPI service. Configure Supabase database, Auth, private Storage credentials and exact Vercel CORS origin in Render.
- Supabase Auth is enabled with `AUTH_PROVIDER=supabase` for office staff only. Every accepted account must match the exact backend `OFFICE_USER_EMAILS` allowlist; student signup and student authentication are disabled.

### Production deployment and database operations

- [Production deployment runbook](docs/PRODUCTION_DEPLOYMENT.md) — non-root container, managed PostgreSQL, canonical host allowlist, HTTPS proxy, persistent private uploads, and pre-launch checks.
- [Private object storage operations](docs/OBJECT_STORAGE.md) — S3-compatible bucket configuration, dry-run-first upload migration, access controls and recovery.
- [Database operations](docs/DATABASE_OPERATIONS.md) — explicit SQLite-to-PostgreSQL dry-run/migration, encrypted PostgreSQL backups, and guarded restore drills.
- [Retention policy template](docs/RETENTION_POLICY_TEMPLATE.md) — institution approval is required before automated deletion can be enabled.
- [Production Compose file](compose.production.yml) — binds the app only to localhost for a TLS reverse proxy; requires real `DATABASE_URL`, `SESSION_SECRET`, and `ALLOWED_HOSTS` environment values.
- The public-first landing page keeps students outside the authenticated office console; Lost/Found report actions open dedicated destination views.

