# LostLink AI launch checklist

This guide describes the AI configuration for the split deployment: Vercel serves
the frontend and the FastAPI service on Render owns inference, matching and the
private embedding cache. Keep all model credentials and storage credentials on
the backend; the browser must call the backend API and must never load model
weights directly.

## AI features and current implementation

| Capability | Implementation | Runtime control | Launch policy |
|---|---|---|---|
| Category suggestions | MiniLM semantic prototypes with deterministic keyword fallback | `USE_SEMANTIC_MODEL` | Available to signed-in and anonymous public report forms; user confirms the category |
| Text matching | MiniLM sentence embeddings with lexical fallback | `USE_SEMANTIC_MODEL` | Recommended first learned model to enable after resource testing |
| Image matching | CLIP image/image and image/text similarity | `USE_CLIP_MODEL` | Enable only after memory and latency tests on the selected Render instance |
| Photo captions and keywords | BLIP image-to-text enrichment | `USE_IMAGE_ENRICHMENT` | Keep off initially; optional, expensive, and not required for core matching |
| Structured matching | Category, campus location and time signals | Always available | Used alongside text/image signals when values exist |

AI output is discovery assistance only. It must not approve claims, verify identity,
decide ownership, or replace physical intake and handover checks. Private claim
evidence, private verification details and office storage locations are excluded
from general candidate matching.

## Render backend build and environment

The default Docker image is intentionally lightweight. To install the optional
model dependencies, configure the Render Docker build argument:

```text
INSTALL_ML=true
```

Install the ML dependency set from `requirements-ml.txt`. Do not expose model
configuration or private storage credentials in Vercel browser variables.

Start with this conservative backend configuration:

```dotenv
USE_SEMANTIC_MODEL=true
SEMANTIC_MODEL=sentence-transformers/all-MiniLM-L6-v2
SEMANTIC_MODEL_REVISION=main
USE_CLIP_MODEL=false
CLIP_MODEL=openai/clip-vit-base-patch32
CLIP_MODEL_REVISION=main
USE_IMAGE_ENRICHMENT=false
IMAGE_CAPTION_MODEL=Salesforce/blip-image-captioning-base
IMAGE_CAPTION_MODEL_REVISION=main
TOKENIZERS_PARALLELISM=false
```

The service downloads model weights on first use. The `main` revision is a safe initial default; before a production freeze, replace each revision with the verified immutable Hugging Face commit SHA for that exact model and keep it in the deployment configuration. Configure a persistent Render
disk/cache at `/model-cache` and set `HF_HOME=/model-cache` so restarts do not
re-download weights. If the selected Render plan cannot accommodate PyTorch and
MiniLM memory/latency, keep semantic inference disabled and retain the lexical
fallback until capacity is upgraded. Do not turn on CLIP or BLIP just because the
dependencies are installed.

## Verification sequence

1. Build the backend image with `INSTALL_ML=true`.
2. Install/start the backend with the environment above and wait for the first
   MiniLM model load to finish.
3. Run `python scripts/smoke_test_matching_models.py` only when both semantic
   and CLIP models are enabled; it checks inference, not accuracy.
4. Sign in as office staff and call `GET /api/office/ai-status`. Confirm the
   text model reaches `ready`; confirm image matching and image enrichment
   report their configured state.
5. Test the anonymous public category helper with Lost and Found details. Verify
   that suggestions do not change the selected category until the user selects
   an alternative.
6. Create labelled lost/found pairs with consented, non-identifying descriptions
   and photos. Test same-item matches, hard negatives, different categories,
   missing photos, no-match cases, and changed dates/locations.
7. Run `python scripts/evaluate_matching.py --dataset path/to/approved-campus-labels.json`
   and retain Precision@K, Recall@K, HitRate@K, MRR, false-positive diagnostics,
   p50/p95 latency, model revision and resource use.
8. Enable CLIP only after the image-labelled evaluation and concurrency/memory
   checks pass. Enable BLIP separately only if captions demonstrably improve
   retrieval without exposing sensitive image content.

## Evidence and limitations

The checked-in 100-query benchmark is synthetic development data. It is useful
for regression tests but is not CVR campus ground truth. No campus accuracy
claim, calibrated score threshold, or production false-positive rate can be
reported until an approved, independently labelled campus evaluation set exists.

The office diagnostics endpoint reports whether models are disabled, not loaded,
ready or unavailable. A successful endpoint response does not by itself prove
the model is loaded; inspect the state after exercising the relevant inference
path. If a model fails, lexical/structured matching remains available and image
signals are omitted. Never represent a fallback result as learned-model output.
