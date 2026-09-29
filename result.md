# Every step, in seconds (first successful end-to-end run)

Case `case-20260827-194926-994b1b` — 5 intraoral views + 1 panoramic, LLM + RAG on,
`RAG_RERANK=0`, `LLM_EFFORT=medium`.

## ML startup (one-time)

| Step | Time |
| --- | --- |
| load:fdi_intraoral | 0.46 s |
| load:teeth_seg_intraoral | 0.34 s |
| load:fdi_panoramic | 0.33 s |
| load:tooth_seg_panoramic | 0.22 s |
| load:rfdetr | 52.87 s |
| load:doubleunet | 1.34 s |

## Analyze — `pipeline:total: 28.17 s`

| Step | Time | Notes |
| --- | --- | --- |
| run_yolo | 8.47 s | seg-intraoral dominates: bottom 2.97 s + 4× ~0.64 s; fdi-panoramic 0.91 s |
| run_rfdetr | 4.01 s | first forward (bottom) 3.21 s cold, then ~0.20 s each |
| run_panoramic_seg | 0.66 s | |
| run_tooth_seg_panoramic | 1.77 s | |
| fuse | 0.20 s | |
| render_overlays | 0.42 s | |
| run_xai | 12.13 s | now 17 real CAMs (was 6, 11 silently failing) — every forward actually runs |
| thumbnail | 0.02 s | |
| free_vram | 0.50 s | |

## Advisory — `advisory:total: 106.94 s`

| Step | Time |
| --- | --- |
| rag_diagnosis | 1.29 s |
| rag_treatment | 0.43 s |
| clinical (LLM) | 105.20 s |
| sanity | 0.001 s (passed first try, no retry) |
| graph:total | 106.92 s |

## Gateway job total: 135.24 s

`= analyze 28 s + advisory 107 s + overhead`

## Where the time actually goes now

`clinical` (the LLM call) is **78 %** of the whole job. That's `gpt-5.6-sol` at
`effort=medium` with `LLM_MAX_TOKENS=12000`. To make it faster, lower `LLM_MAX_TOKENS`
(e.g. 8000) or set `LLM_EFFORT=low` — those bite `clinical` directly.

`run_xai` at 12 s is the other lever: it's doing 3× the real work it used to (11 CAM
forwards that used to fail instantly now actually run). Could batch, or drop the per-view
grade CAMs.

`load:rfdetr` at 52.87 s is startup-only (one-time per ML process), not per case.
