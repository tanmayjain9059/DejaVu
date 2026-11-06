# LostLink AI matching baseline

This document describes the current demonstrable AI matching path. The scores are
candidate-ranking signals, not calibrated probabilities and never proof of
ownership. Office staff remain responsible for claim verification and physical
handover.

## Models and responsibilities

- **MiniLM** (`sentence-transformers/all-MiniLM-L6-v2`) compares the meaning of
  public lost/found descriptions and item characteristics.
- **CLIP** (`openai/clip-vit-base-patch32`) compares two available photos, or
  compares one available photo with the other report's public description.
- **Structured signals** compare category, reported campus location and time.
- **Lexical fallback** keeps matching available if MiniLM is disabled, cannot be
  downloaded, or fails during inference. CLIP is an independent optional signal;
  its failure does not disable text matching.

Private claim evidence, private item details and office storage locations must
not be passed into general candidate matching.

## Local demonstration

Use Python 3.11 or 3.12 and a machine with enough memory for PyTorch and the
pretrained models.

1. Install the normal application dependencies:

   ```bash
   python -m pip install -r requirements-dev.txt
   ```

2. Install the optional model dependencies:

   ```bash
   python -m pip install -r requirements-ml.txt
   ```

3. In the local `.env`, enable the two models:

   ```dotenv
   USE_SEMANTIC_MODEL=true
   SEMANTIC_MODEL=sentence-transformers/all-MiniLM-L6-v2
   USE_CLIP_MODEL=true
   CLIP_MODEL=openai/clip-vit-base-patch32
   ```

4. Start the application normally. Models load lazily on the first matching
   request. The first load may download pretrained weights and therefore needs
   network access. Later starts can reuse the Hugging Face model cache.

5. Sign in as an office user and inspect:

   ```http
   GET /api/office/ai-status
   ```

   The response reports whether each model is disabled, not yet loaded, loading,
   ready or unavailable. It deliberately omits exception messages and local
   filesystem paths. Trigger a lost-report match request to load the models,
   then check the status again. Internal match results include the engine name
   and individual signal scores.

## Container demonstration

The normal production image remains lightweight by default. To include optional
AI dependencies in the image, build with:

```bash
INSTALL_ML=true docker compose -f compose.production.yml build
```

Set `USE_SEMANTIC_MODEL=true` and/or `USE_CLIP_MODEL=true` in the deployment
environment to activate the relevant model. Compose mounts a persistent
`/model-cache` volume so pretrained weights do not need to be downloaded on
every container recreation. The first model load still requires outbound access
to the model registry unless the cache is pre-populated.

For a CPU-only demonstration, expect first-load latency and slower image
inference. Do not enable both models on a small production instance without
measuring its memory and response-time headroom. Keep the models disabled on
deployments that have not installed the optional dependencies.

## Current guarantees and limitations

- Lazy model construction is protected against concurrent first requests.
- A failed MiniLM load or inference falls back to lexical similarity.
- A failed CLIP load removes only the image signal; other matching signals remain.
- The office-only diagnostics endpoint exposes safe model state, not raw errors.
- The current benchmark is synthetic and small. It demonstrates repeatability,
  not real campus accuracy.
- Model scores and thresholds have not been calibrated against labelled campus
  data. Do not describe `strong`, `possible` or `limited` as probabilities.
- Matching does not decide claim ownership. Staff must follow the existing
  verification checklist and physical handover workflow.

## Baseline evaluation before a campus pilot

Run:

```bash
python -m unittest discover -s tests -v
python scripts/evaluate_matching.py
```

Record the exact model configuration used for each evaluation. Compare the
lexical baseline and MiniLM on the same labelled cases. CLIP and combined
ranking need their own labelled image cases before making accuracy claims.
