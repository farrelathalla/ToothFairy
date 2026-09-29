<div align="center">

# 🦷 ToothFairy

**Deteksi karies anak dan rekonstruksi gigi 3D interaktif dari citra intraoral & panoramik.**

Six vision models find and grade every carious lesion, a layered 3D dentition is eroded in
proportion to what was actually detected, and a retrieval-grounded agent writes a per-tooth
ICD-10 diagnosis and a treatment plan a dentist can check line by line.

</div>

---

## What it does

A dentist photographs a child — up to five intraoral views plus one panoramic radiograph — and
fills in a short anamnesa. ToothFairy then:

1. **Numbers every tooth** (FDI) across all views and reconciles them into one chart.
2. **Finds and grades every lesion** on the ICDAS D1–D6 scale, fusing four detectors so a
   grossly destroyed tooth is not under-called by any single one.
3. **Finds hidden lesions** — caries visible only as a radiolucency under intact enamel.
4. **Reconstructs the dentition in 3D**, morphing each tooth to the patient's own proportions
   and root curvature, then eroding it in proportion to the caries actually detected: mild
   lesions stay white, deep ones break through enamel into dentine, severe ones grind the
   crown to a stump with exposed pulp. Any tooth can be sliced open to inspect layer
   involvement.
5. **Writes the clinical documents** — a per-tooth ICD-10 diagnosis correlated with the
   patient's complaint, and a conditional treatment plan — each grounded in a dental
   literature corpus with **machine-verified** citations.

Everything is in Indonesian, mobile-first, and installable as a PWA.

<div align="center">

| | |
|---|---|
| **Vision** | YOLO26x · YOLO26x-seg · RF-DETR-2XL · DoubleU-Net |
| **3D** | Next.js 14 · Three.js · react-three-fiber · runtime carve & morph |
| **API** | Go 1.26 gateway · JWT + RBAC · job queue · SQLite (WAL) |
| **ML service** | Python 3.13 · FastAPI · stateless |
| **Advisory** | GPT-5.6 · BGE-M3 + BM25 + RRF + cross-encoder rerank |

</div>

---

## Architecture at a glance

```
   Next.js PWA  ──HTTPS/JWT──►  Go API gateway  ──internal HTTP──►  Python ML service
   3D viewer                    auth · cases                        vision pipeline
   anamnesa                     uploads · media                     LLM + RAG advisory
   results                      job queue                                   │
        ▲                            │                                      │
        │                       SQLite (WAL)                                │
        └──────────── static results/<case>/detections.json ◄───────────────┘
```

The gateway is not a proxy — it **owns** identity, case records, uploads and scheduling. The ML
service is **stateless** and exposes exactly two operations. That split keeps logins, history
and status polling off the process holding gigabytes of vision weights, and lets the ML side be
scaled or GPU-scheduled independently.

📄 **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — the full design and the reasoning behind
each boundary.

---

## Quick start

### Standalone mode — the web app on its own

ToothFairy is an installable PWA meant for clinic tablets on unreliable connectivity, so it
keeps working when the gateway is unreachable: `web/lib/standalone.js` answers the same API
routes from the browser, backed by local storage and the analysis datasets bundled in
`web/public/results/`.

That makes it also the fastest way to see the product — **one command, no backend at all**:

```bash
cd web
npm install
npm run dev            # http://localhost:3000
```

Sign in with any email and password (standalone mode has no account store), create a case,
upload photos, and the full results view opens: the 3D reconstruction, the detection gallery,
the attention maps, and the diagnosis and treatment documents. Cases you create are kept in
that browser only; **Atur ulang data lokal** under the logo on the sign-in screen clears them.

Set `NEXT_PUBLIC_STANDALONE=0` to always talk to the gateway instead.

### Full stack

Run all three services to exercise real authentication, uploads and inference. **No model
weights and no API key are required** for the demo cases.

### Prerequisites

| | Version | Needed for |
|---|---|---|
| [Node.js](https://nodejs.org) | 20+ | web app |
| [Go](https://go.dev/dl/) | 1.24+ | API gateway |
| [Python](https://www.python.org/downloads/) | 3.11+ | ML service |

### 1 — ML service

```bash
cd ml
pip install -r requirements.txt
cp .env.example .env                    # defaults are fine for the demo

MOCK_INFERENCE=1 python -m uvicorn app.main:app --port 8000
```

`MOCK_INFERENCE=1` skips the heavy vision models and serves the precomputed demo results, so
this starts in seconds. Drop it once you have downloaded the weights.

### 2 — API gateway

```bash
cd gateway
cp .env.example .env                    # defaults are fine for the demo
go run ./cmd/server                     # http://localhost:8081
```

It creates and seeds its database on first boot — demo accounts and four demo cases.

### 3 — Web app

```bash
cd web
npm install
npm run dev                             # http://localhost:3000
```

### 4 — Sign in

| Role | Email | Password |
|---|---|---|
| Dentist | `dokter@toothfairy.id` | `doctor123` |
| Admin | `admin@toothfairy.id` | `admin123` |

> Demo credentials. Change them before any real deployment.

Open any case in the history to see the full result view: the 3D dentition, the per-model
detection gallery, the attention maps, and the diagnosis and treatment cards.

---

## Running a real analysis

The demo path uses precomputed results. To analyse a **new** capture you need the model
weights.

### 1 — Download the weights

They are hosted on Hugging Face under [**`Frallex`**](https://huggingface.co/Frallex), one
repository per model, with the training data in the identically named dataset repository:

| Model | Weights | Dataset |
|---|---|---|
| FDI Intraoral | [`Frallex/FDI_Intraoral`](https://huggingface.co/Frallex/FDI_Intraoral) | [datasets/`FDI_Intraoral`](https://huggingface.co/datasets/Frallex/FDI_Intraoral) |
| FDI Panoramic | [`Frallex/FDI_Panoramic`](https://huggingface.co/Frallex/FDI_Panoramic) | [datasets/`FDI_Panoramic`](https://huggingface.co/datasets/Frallex/FDI_Panoramic) |
| Teeth Segmentation Intraoral | [`Frallex/Teeth_Segmentation_Intraoral`](https://huggingface.co/Frallex/Teeth_Segmentation_Intraoral) | [datasets/`Teeth_Segmentation_Intraoral`](https://huggingface.co/datasets/Frallex/Teeth_Segmentation_Intraoral) |
| Caries Bounding Box | [`Frallex/Caries_Bounding_Box`](https://huggingface.co/Frallex/Caries_Bounding_Box) | [datasets/`Caries_Bounding_Box`](https://huggingface.co/datasets/Frallex/Caries_Bounding_Box) |
| Caries Segmentation Panoramic | [`Frallex/Caries_Segmentation_Panoramic`](https://huggingface.co/Frallex/Caries_Segmentation_Panoramic) | [datasets/`Caries_Segmentation_Panoramic`](https://huggingface.co/datasets/Frallex/Caries_Segmentation_Panoramic) |
| Tooth Segmentation Panoramic | [`Frallex/Teeth_Segmentation_Panoramic`](https://huggingface.co/Frallex/Teeth_Segmentation_Panoramic) | [datasets/`Teeth_Segmentation_Panoramic`](https://huggingface.co/datasets/Frallex/Teeth_Segmentation_Panoramic) |

```bash
pip install -U "huggingface_hub[cli]"
hf download Frallex/FDI_Intraoral model.pt --local-dir "ml/training/FDI Intraoral"
# ... and the other five models
```

**[docs/MODELS_AND_DATASETS.md](docs/MODELS_AND_DATASETS.md)** has the full download commands
and where each file has to land.

### 2 — Install the vision dependencies

```bash
cd ml
pip install torch opencv-python ultralytics "rfdetr[plus]" supervision
```

### 3 — Run the service without the mock

```bash
cd ml
python -m uvicorn app.main:app --port 8000     # MOCK_INFERENCE unset
```

Now **Kasus Baru** in the web app runs the real pipeline: fill in the anamnesa, upload photos,
and watch the real per-stage progress. Expect roughly a minute per view on CPU.

You can also run the pipeline directly, without the services:

```bash
cd ml
python inference/run_all.py                    # rebuild all demo datasets
python inference/run_all.py NAMA /path/to/dir  # analyse one capture folder
```

### 4 — Enable the clinical advisory (optional)

```bash
# ml/.env
OPENAI_API_KEY=sk-...
LLM_ENABLED=1
RAG_ENABLED=1
```

Retrieval downloads its two open-weight models (~4.5 GB) on first use and then runs **locally**;
only the final prompt reaches the model provider. With `LLM_ENABLED=0` the product still works
end to end and produces a deterministic summary instead — no outbound call at all.

---

## Testing

```bash
cd gateway && go test ./...        # gateway: auth, RBAC, uploads, jobs, store
cd ml      && python -m pytest     # ML service: agents, prompts, citations, internal API
cd web     && npm run test:run     # web: API client, forms, result components
cd web     && npm run e2e          # end-to-end: the standalone path, web app only
```

The end-to-end suite drives the real screens through the same `lib/api.js` calls the online
build uses — only the transport differs — so it covers the offline path a clinic tablet
actually takes. No test in any suite makes a network call to a model provider.

Evaluation of the retrieval stack and the clinical agents:

```bash
cd ml
python -m evals.run_evals --retrieval   # ablation over the retrieval pipeline, no API key
python -m evals.run_evals               # + generation metrics (needs a key)
```

Results are written to **[docs/EVAL_REPORT.md](docs/EVAL_REPORT.md)**.

---

## How the clinical write-up is kept honest

Two problems dominate when a language model writes clinical text: it repeats itself, and it
invents sources. Both are addressed structurally rather than by asking nicely.

**Per-tooth detail.** Given only `(tooth, grade)`, a model writes "same as above" for every
tooth of the same grade — a table of `Idem` that reads as if nobody looked. But the detector
knows far more per tooth, so each one is first distilled into a quantitative profile: lesion
extent as a share of the crown, discolouration relative to sound enamel, how many separate
lesions and where in the crown they sit, whether the radiograph corroborates, how many
detectors agreed, and the tooth's anatomical name. Every band is a documented cut-off and unit
tested. With that in the prompt, a specific answer per tooth is the path of least resistance —
and the consistency checker rejects `Idem`-style filler outright.

**Verified citations.** The agent may cite the retrieved passages, but its word is not taken
for it: every claimed quote is checked as a verbatim substring of the document it is attributed
to. Quotes that cannot be found are dropped *along with their marker*, so a fabricated citation
degrades to no citation rather than to a false one. The verified/rejected ratio is reported as
a hallucination metric.

**A deterministic guard.** The final check is not a model call — a guard on a clinical output
must not be able to hallucinate an approval. It verifies that every affected tooth appears in
both documents, that no treatment is planned for a tooth both detectors call absent, that every
ICD-10 code comes from the sanctioned table, that pulp codes appear only on deep lesions, and
that no row repeats another. Defects it can fix are fed back into exactly one retry, telling
the agent *what* to fix.

---

## Safety, privacy and intended use

**ToothFairy is decision support for a qualified dentist. It is not a medical device and it
does not diagnose autonomously.** Every generated document is a draft for a clinician to
verify against an in-person examination.

Patient images **never leave the deployment** — all vision inference is local, and so is
retrieval. Only the anamnesa text and the per-tooth findings reach the model provider, only
when the advisory layer is explicitly enabled.

📄 **[docs/SAFETY_PRIVACY_SECURITY.md](docs/SAFETY_PRIVACY_SECURITY.md)** — intended use and
regulatory position, data minimisation and deletion, hallucination and bias mitigations,
security controls, failure handling, and known limitations.

---

## Repository layout

```
web/        Next.js 14 PWA — anamnesa wizard, 3D viewer, results, advisory cards
gateway/    Go API gateway — auth, cases, uploads, media, job queue
ml/         Python service
  app/        FastAPI internal API + LLM/RAG advisory layer
  inference/  vision pipeline (detection → fusion → overlays → 3D inputs)
  training/   model training notebooks (weights live on Hugging Face)
  evals/      retrieval + generation evaluation harness
assets/
  samples/    demo captures  ·  seed/  demo accounts & cases  ·  3d/  base mesh
  blender/    asset-generation scripts for the layered teeth and gingiva
docs/       architecture · safety & privacy · models & datasets · eval report
```

---

## Configuration

Every service reads its settings from the environment and ships a documented `.env.example`.
The ones that matter most:

| Variable | Service | Default | Notes |
|---|---|---|---|
| `ADDR` | gateway | `:8081` | listen address |
| `JWT_SECRET` | gateway | dev placeholder | **must** be changed; production boot refuses the default |
| `INTERNAL_API_KEY` | both | empty | shared secret for the internal ML API; required in production |
| `ML_BASE_URL` | gateway | `http://localhost:8000` | where the ML service lives |
| `MOCK_INFERENCE` | ml | `0` | `1` serves precomputed demo results |
| `LLM_ENABLED` | ml | `0` | `1` enables the clinical agents |
| `RAG_ENABLED` | ml | `0` | `1` enables literature retrieval |
| `OPENAI_API_KEY` | ml | empty | required when `LLM_ENABLED=1` |
| `NEXT_PUBLIC_API_URL` | web | `http://localhost:8081` | the gateway's public URL |
| `NEXT_PUBLIC_STANDALONE` | web | `1` | `0` forces every request to the gateway |

With `ENV=production` the gateway refuses to start on a development JWT secret or a missing
internal key, so a misconfigured deployment fails loudly rather than quietly serving forgeable
tokens.

---

## License

Released under the [MIT License](LICENSE). The dental literature corpus under
`ml/app/llm/corpus/` remains the property of its respective publishers and is included for
research use only.
