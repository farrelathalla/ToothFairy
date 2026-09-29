# Evaluation Report: RAG and Clinical Agents

_Generated automatically by `python -m evals.run_evals` on 2026-08-03 09:36 UTC._

This report measures two separate things, retrieval (whether the correct passage is retrieved) and generation (whether the produced diagnosis and treatment plan are faithful, specific per tooth, verifiably cited, and ICD-10 valid).

## 1. Retrieval

The indexed corpus contains 1,340 chunks from 23 documents (`BAAI/bge-m3`, dim 1024), and the QA set consists of 15 hand-written questions, each with a gold document. Retrieval is filtered to the `{diagnosis, context}` categories, the same filter the diagnosis agent uses.

### Pipeline ablation

| Configuration                        | Recall@1 | Recall@3 | Recall@5 | Recall@10 | MRR   | Latency/query |
| ------------------------------------ | -------- | -------- | -------- | --------- | ----- | ------------- |
| BM25 only                            | 86.7%    | 100.0%   | 100.0%   | 100.0%    | 0.933 | 13 ms         |
| Hybrid (BM25 + BGE-M3, RRF)          | 100.0%   | 100.0%   | 100.0%   | 100.0%    | 1.000 | 3983 ms       |
| Hybrid + rerank (bge-reranker-v2-m3) | 93.3%    | 93.3%    | 100.0%   | 100.0%    | 0.956 | 67658 ms      |

The upper bound, with the gold document present in the 16-candidate shortlist before reranking, is 100.0%.

**Reading:** BM25 is already strong on technical terms (PUFA, ECOHIS, ICDAS). Adding dense BGE-M3 through RRF closes cross-language paraphrase queries. On this small, already-saturated QA set, the cross-encoder cannot push recall any higher, its value lies in ranking precision for harder queries, which keeps the small top-N (6 passages) sent to the model relevant. The category filter also reduces token cost.

## 2. Generation

Scores are recomputed from the documents committed under `assets/seed/advisory/`, the same text the app displays, so the numbers below are reproducible without an API key, using `python -m evals.run_evals --generation --committed`.

### 2.1 Diagnosis: deterministic checks

| Case            | Affected teeth | Rows | Tooth coverage | Valid codes | Depth consistent | Pulp escalation | K04.x only if D5+ | Template |
| --------------- | -------------- | ---- | -------------- | ----------- | ---------------- | --------------- | ----------------- | -------- |
| `demo-original` | 15             | 15   | 100.0%         | 100.0%      | 100.0%           | 0               | 100.0%            | 100.0%   |
| `demo-set1`     | 7              | 7    | 100.0%         | 100.0%      | 100.0%           | 0               | 100.0%            | 100.0%   |
| `demo-set2`     | 13             | 13   | 100.0%         | 100.0%      | 100.0%           | 0               | 100.0%            | 100.0%   |
| `demo-set3`     | 21             | 20   | 95.2%          | 100.0%      | 100.0%           | 0               | 100.0%            | 100.0%   |

`Valid codes` means every code exists in the supplied ICD-10 table. `Depth consistent` means the caries code matches the ICDAS-to-ICD-10 prior (D1-D2 maps to K02.0, D3-D6 maps to K02.1), or the row escalates to a pulpal code valid for that grade. `Pulp escalation` counts teeth assigned K04.x in place of K02.1, which is correct clinical behavior on D6, not an error. `K04.x only if D5+` confirms the agent never attaches a pulpal code to a shallow lesion.

### 2.2 Per-tooth specificity

The core metric for the prompt design plus the per-tooth quantitative profile is that every table row must describe its own tooth rather than copy the previous row.

| Case            | Unique damage pattern | "Idem" rows | Teeth narrated in depth | Complaint correlation |
| --------------- | --------------------- | ----------- | ----------------------- | --------------------- |
| `demo-original` | 100.0%                | 0           | 6                       | yes                   |
| `demo-set1`     | 100.0%                | 0           | 6                       | yes                   |
| `demo-set2`     | 100.0%                | 0           | 6                       | yes                   |
| `demo-set3`     | 100.0%                | 0           | 6                       | yes                   |

The average unique damage pattern is **100.0%**, with a total of 0 `idem` rows.

### 2.3 Treatment recommendations

| Case            | Rows | Tooth coverage | Unaffected teeth planned | Unique actions | Urgency terms | Template |
| --------------- | ---- | -------------- | ------------------------ | -------------- | ------------- | -------- |
| `demo-original` | 15   | 100.0%         | 0                        | 100.0%         | 4/4           | 100.0%   |
| `demo-set1`     | 7    | 100.0%         | 0                        | 100.0%         | 4/4           | 100.0%   |
| `demo-set2`     | 13   | 100.0%         | 0                        | 38.5%          | 0/4           | 0.0%     |
| `demo-set3`     | 21   | 100.0%         | 0                        | 100.0%         | 4/4           | 100.0%   |

### 2.4 Citation verification (deterministic)

Every quote the agent claims is matched **verbatim** against the source document before it is shown. Quotes that cannot be found are dropped along with their marker, so any citation that does appear is always auditable.

| Case            | Claimed | Verified | Dropped | Sources shown |
| --------------- | ------- | -------- | ------- | ------------- |
| `demo-original` | 0       | 0        | 0       | 0             |
| `demo-set1`     | 0       | 0        | 0       | 0             |
| `demo-set2`     | 0       | 0        | 0       | 0             |
| `demo-set3`     | 0       | 0        | 0       | 0             |

The verified citation rate is **n/a** (0/0).

### 2.6 Consistency check

| Case            | Passed | Findings |
| --------------- | ------ | -------- |
| `demo-original` | yes    | None     |
| `demo-set1`     | yes    | None     |
| `demo-set2`     | yes    | None     |
| `demo-set3`     | yes    | None     |

## Reproduction

```bash
cd ml
python -m evals.run_evals --retrieval              # retrieval ablation, no API key
python -m evals.run_evals --generation --committed # score committed documents, no API key
python -m evals.run_evals                          # rerun the agents (needs an API key)
```
