# Models and datasets

Model weights and training datasets are **not** committed to this repository, since they are
large binaries and version control is the wrong place for them. They are hosted on Hugging Face
and linked below.

Everything else needed to run the product **is** in the repository, including the retrieval
index, the 3D assets, the demo captures and the precomputed results for the demo cases. A fresh
clone runs the full user journey without downloading a single weight, and the weights are only
needed to analyse a _new_ capture.

---

## 1. Vision models

Each model has its own repository containing the weights and a model card.

| #   | Model                         | Task                                                  | Architecture | Hugging Face                                                                                            |
| --- | ----------------------------- | ----------------------------------------------------- | ------------ | ------------------------------------------------------------------------------------------------------- |
| 1   | FDI Intraoral                 | Tooth numbering on intraoral photos (32 FDI classes)  | YOLO26x      | [`Frallex/FDI_Intraoral`](https://huggingface.co/Frallex/FDI_Intraoral)                                 |
| 2   | FDI Panoramic                 | Tooth numbering on panoramic radiographs              | YOLO26x      | [`Frallex/FDI_Panoramic`](https://huggingface.co/Frallex/FDI_Panoramic)                                 |
| 3   | Teeth Segmentation Intraoral  | Instance polygons for Caries / Cavity / Crack / Tooth | YOLO26x-seg  | [`Frallex/Teeth_Segmentation_Intraoral`](https://huggingface.co/Frallex/Teeth_Segmentation_Intraoral)   |
| 4   | Caries Bounding Box           | ICDAS D1-D6 severity grading                          | RF-DETR-2XL  | [`Frallex/Caries_Bounding_Box`](https://huggingface.co/Frallex/Caries_Bounding_Box)                     |
| 5   | Caries Segmentation Panoramic | Radiographic (hidden) caries mask                     | DoubleU-Net  | [`Frallex/Caries_Segmentation_Panoramic`](https://huggingface.co/Frallex/Caries_Segmentation_Panoramic) |
| 6   | Tooth Segmentation Panoramic  | Per-tooth silhouettes for 3D shape & root curvature   | YOLO26x-seg  | [`Frallex/Teeth_Segmentation_Panoramic`](https://huggingface.co/Frallex/Teeth_Segmentation_Panoramic)   |

### Where the files go

The pipeline loads the weights from `ml/training/`. The per-model folders are already in the
repository, empty, and each download simply lands in its own. The weights themselves are never
committed:

```
ml/training/
├── FDI Intraoral/model.pt
├── FDI Panoramic/model.pt
├── Teeth Segmentation Intraoral/model.pt
├── Caries Bounding Box/model.pth
├── Caries Segmentation Panoramic/model.pth
└── Tooth Segmentation Panoramic/model.pt
```

Download them all with the Hugging Face CLI:

```bash
pip install -U "huggingface_hub[cli]"

hf download Frallex/FDI_Intraoral                  model.pt  --local-dir "ml/training/FDI Intraoral"
hf download Frallex/FDI_Panoramic                  model.pt  --local-dir "ml/training/FDI Panoramic"
hf download Frallex/Teeth_Segmentation_Intraoral   model.pt  --local-dir "ml/training/Teeth Segmentation Intraoral"
hf download Frallex/Caries_Bounding_Box            model.pth --local-dir "ml/training/Caries Bounding Box"
hf download Frallex/Caries_Segmentation_Panoramic  model.pth --local-dir "ml/training/Caries Segmentation Panoramic"
hf download Frallex/Teeth_Segmentation_Panoramic   model.pt  --local-dir "ml/training/Tooth Segmentation Panoramic"
```

Without the weights the ML service still runs. Set `MOCK_INFERENCE=1` and it serves the
precomputed demo results instead.

---

## 2. Training datasets

| Dataset                                    | Used by | Hugging Face                                                                                                     |
| ------------------------------------------ | ------- | ---------------------------------------------------------------------------------------------------------------- |
| Intraoral FDI numbering                    | model 1 | [`Frallex/FDI_Intraoral`](https://huggingface.co/datasets/Frallex/FDI_Intraoral)                                 |
| Panoramic FDI numbering                    | model 2 | [`Frallex/FDI_Panoramic`](https://huggingface.co/datasets/Frallex/FDI_Panoramic)                                 |
| Intraoral caries/cavity/crack segmentation | model 3 | [`Frallex/Teeth_Segmentation_Intraoral`](https://huggingface.co/datasets/Frallex/Teeth_Segmentation_Intraoral)   |
| ICDAS-graded caries bounding boxes         | model 4 | [`Frallex/Caries_Bounding_Box`](https://huggingface.co/datasets/Frallex/Caries_Bounding_Box)                     |
| Panoramic caries segmentation              | model 5 | [`Frallex/Caries_Segmentation_Panoramic`](https://huggingface.co/datasets/Frallex/Caries_Segmentation_Panoramic) |
| Panoramic tooth instance segmentation      | model 6 | [`Frallex/Teeth_Segmentation_Panoramic`](https://huggingface.co/datasets/Frallex/Teeth_Segmentation_Panoramic)   |

Each dataset repository shares its name with the model trained on it, so `Frallex/<name>` under
`/datasets/` is the training data for `Frallex/<name>` under `/models/`. Download one with:

```bash
hf download --repo-type dataset Frallex/FDI_Intraoral --local-dir "data/FDI Intraoral"
```

---

## 3. Retrieval models

The advisory layer's retrieval stack uses open-weight models downloaded from Hugging Face on
first use and cached locally. They are **not** vendored.

| Role                   | Model                                                                       |
| ---------------------- | --------------------------------------------------------------------------- |
| Dense embeddings       | [`BAAI/bge-m3`](https://huggingface.co/BAAI/bge-m3)                         |
| Cross-encoder reranker | [`BAAI/bge-reranker-v2-m3`](https://huggingface.co/BAAI/bge-reranker-v2-m3) |

Both run **locally**, which is why no patient-derived query text leaves the deployment during
retrieval. Together they are roughly 4.5 GB on first download.

The built index (`ml/app/llm/corpus/index/`) **is committed**, so a clone can retrieve without
re-ingesting the corpus. Only a corpus change requires a rebuild:

```bash
cd ml
python -m app.llm.retrieval.build          # needs OPENAI_API_KEY + LLM_ENABLED=1
```

---

## 4. Language model

The clinical agents call the OpenAI API. Nothing is downloaded or self-hosted.

| Role                                | Default                  | Configured by        |
| ----------------------------------- | ------------------------ | -------------------- |
| Diagnosis & recommendation agents   | `gpt-5.6-sol`            | `LLM_MODEL`          |
| Chunk contextualisation, eval judge | `gpt-5.6-luna`           | `LLM_HELPER_MODEL`   |
| Input moderation (optional)         | `omni-moderation-latest` | `MODERATION_ENABLED` |

`OPENAI_BASE_URL` points the client at a compatible or regional endpoint where data residency
requires it.

---

## 5. 3D assets

Committed to the repository (a few MB, and the product is unusable without them):

| Asset                                                 | Path                                     |
| ----------------------------------------------------- | ---------------------------------------- |
| Base dentition mesh (32 teeth)                        | `assets/3d/teeth.glb`                    |
| Layered dentition (enamel / dentine / pulp per tooth) | `web/public/teeth_layered.glb`           |
| Per-tooth meshes for the cross-section examiner       | `web/public/teeth_layer/tooth_<fdi>.glb` |
| Gingiva                                               | `web/public/gums.glb`                    |

The layered and gingival assets are generated from the base mesh by the scripts in
`assets/blender/`, and they are committed so the app runs without Blender.

---

## 6. Sample data

`assets/samples/` contains four demo captures used by the shipped demo cases and by the
evaluation harness:

| Capture                           | Contents                               | Severity |
| --------------------------------- | -------------------------------------- | -------- |
| `intraoral.jpg` + `panoramic.png` | single upper-occlusal view + panoramic | rampant  |
| `set1/`                           | five intraoral views + panoramic       | mild     |
| `set2/`                           | five intraoral views + panoramic       | moderate |
| `set3/`                           | five intraoral views + panoramic       | severe   |

Their precomputed results are committed under `web/public/results/`, which is what lets a fresh
clone show complete cases (3D reconstruction, overlays, explainability maps and the advisory
documents) without any model weights or API key.
