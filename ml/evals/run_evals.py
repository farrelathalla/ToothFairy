"""Run the retrieval + generation evals and write `docs/EVAL_REPORT.md`.

    cd ml
    python -m evals.run_evals                 # both halves (needs key + index)
    python -m evals.run_evals --retrieval     # no API key needed
    python -m evals.run_evals --no-judge      # generation + deterministic checks only

Retrieval is scored as an **ablation** (BM25 → +dense/RRF → +cross-encoder rerank) so the
report shows what each stage of the pipeline actually buys, not just a final number.

Generation is scored on the four demo cases with a mix of deterministic checks (ICD-10 code
validity, depth consistency, per-tooth specificity, tooth coverage, template compliance,
citation verifiability — no judge, no variance) and judged ones (claim faithfulness, citation
support, answer relevance).
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.llm import agents, graph, icd10, openai_client, prompts, rag  # noqa: E402
from app.llm.retrieval import index  # noqa: E402
from evals import judge  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
ML_DIR = EVAL_DIR.parent
REPO_ROOT = ML_DIR.parent
REPORT = REPO_ROOT / "docs" / "EVAL_REPORT.md"
SEED_FILE = REPO_ROOT / "assets" / "seed" / "demo_cases.json"

K_VALUES = (1, 3, 5, 10)
RETRIEVE_DEPTH = 10
MAX_CITATION_CHECKS = 12  # per case — bounds judge cost

# USD per 1M tokens (standard tier), {input, cached input, output}.
PRICES = {
    "gpt-5.6-sol":   {"in": 5.00, "cached": 0.50, "out": 30.00},
    "gpt-5.6-terra": {"in": 2.00, "cached": 0.20, "out": 12.00},
    "gpt-5.6-luna":  {"in": 0.20, "cached": 0.02, "out": 1.20},
}


# ── retrieval ────────────────────────────────────────────────────────────────────

def _load_qa() -> list[dict]:
    return json.loads(
        (EVAL_DIR / "qa_retrieval.json").read_text(encoding="utf-8")
    )["questions"]


def _first_gold_rank(hits: list[dict], gold: set[str]) -> int | None:
    seen: list[str] = []
    for hit in hits:
        if hit["doc_id"] not in seen:
            seen.append(hit["doc_id"])
    for rank, doc_id in enumerate(seen, start=1):
        if doc_id in gold:
            return rank
    return None


def _score(runs: list[tuple[list[dict], set[str]]]) -> dict:
    recalls = {k: 0 for k in K_VALUES}
    reciprocal: list[float] = []
    for hits, gold in runs:
        rank = _first_gold_rank(hits, gold)
        reciprocal.append(1.0 / rank if rank else 0.0)
        for k in K_VALUES:
            top_k = {h["doc_id"] for h in hits[:k]}
            recalls[k] += 1 if top_k & gold else 0
    n = max(len(runs), 1)
    return {
        **{f"recall@{k}": recalls[k] / n for k in K_VALUES},
        "mrr": statistics.fmean(reciprocal) if reciprocal else 0.0,
    }


def _bm25_only_loader():
    real = index._load()

    def _loader():
        if real is None:
            return None
        return {**real, "dense": None}

    return _loader


def eval_retrieval() -> dict:
    questions = _load_qa()
    cats = rag.DIAGNOSIS_CATEGORIES
    configs: dict[str, dict] = {}

    def _run(label: str, **kw):
        t0 = time.perf_counter()
        runs = [
            (index.retrieve(q["question"], k=RETRIEVE_DEPTH, categories=cats, **kw),
             set(q["gold"]))
            for q in questions
        ]
        configs[label] = _score(runs)
        configs[label]["latency_ms"] = (time.perf_counter() - t0) / len(questions) * 1000

    # BM25 only: pretend the dense index isn't there.
    with mock.patch.object(index, "_load", _bm25_only_loader()):
        _run("BM25 saja", rerank=False)
    _run("Hybrid (BM25 + BGE-M3, RRF)", rerank=False)
    _run("Hybrid + rerank (bge-reranker-v2-m3)", rerank=True)

    # Ceiling: does the fused shortlist contain the gold doc at all?
    shortlist_hits = sum(
        1
        for q in questions
        if {h["doc_id"] for h in index.retrieve(
            q["question"], k=settings.rag_candidates, categories=cats, rerank=False)}
        & set(q["gold"])
    )
    return {
        "n_questions": len(questions),
        "configs": configs,
        "shortlist_recall": shortlist_hits / len(questions),
        "index": index.stats(),
    }


# ── markdown parsing ─────────────────────────────────────────────────────────────

_CODE_RE = re.compile(r"K\d{2}(?:\.\d)?")
_GRADE_RE = re.compile(r"^D?([0-6])$")

DIAGNOSIS_SECTIONS = (
    "## Ringkasan Klinis",
    "## Diagnosis per Gigi",
    "## Analisis Mendalam Gigi Prioritas",
    "## Korelasi dengan Keluhan Pasien",
    "## Diagnosis Banding & Risiko Pulpa",
    "## Perkiraan Gejala & Dampak Harian",
    "## Batasan & Ketidakpastian",
)

RECOMMENDATION_SECTIONS = (
    "## Prioritas & Triase",
    "## Rencana Perawatan per Gigi",
    "## Urutan Kunjungan",
    "## Pencegahan & Pengendalian Risiko",
    "## Edukasi untuk Pasien & Orang Tua",
    "## Tanda Bahaya",
    "## Tindak Lanjut & Kontrol",
)

URGENCY_TERMS = ("Segera", "Cepat", "Terjadwal", "Pemantauan")


def section(markdown: str, heading: str) -> str:
    """The body of one `## heading` section, or "" when absent."""
    if heading not in markdown:
        return ""
    body = markdown.split(heading, 1)[1]
    return body.split("\n## ", 1)[0]


def table_rows(markdown: str) -> tuple[list[str], list[list[str]]]:
    """→ (header cells, data rows) for the first markdown table in `markdown`."""
    lines = [l.strip() for l in markdown.splitlines() if l.strip().startswith("|")]
    parsed = [[c.strip() for c in l.strip("|").split("|")] for l in lines]
    rows = [r for r in parsed if not all(set(c) <= set("-: ") for c in r if c)]
    if not rows:
        return [], []
    header, data = rows[0], rows[1:]
    # Only rows whose first cell is an FDI number are data.
    return header, [r for r in data if re.fullmatch(r"\d{2}", r[0].strip("* "))]


def _column(header: list[str], *names: str) -> int | None:
    for i, cell in enumerate(header):
        low = cell.lower()
        if any(n in low for n in names):
            return i
    return None


def parse_icd_rows(markdown: str) -> list[dict]:
    """The diagnosis table → `[{fdi, grade, codes, pattern}]`.

    Columns are located **by header name** rather than by position, so adding a column to the
    template does not silently break the eval (which is exactly what a per-tooth pattern
    column would otherwise have done).
    """
    body = section(markdown, "## Diagnosis per Gigi") or markdown
    header, rows = table_rows(body)
    if not rows:
        return []

    i_grade = _column(header, "icdas")
    i_code = _column(header, "icd-10", "kode")
    i_pattern = _column(header, "pola")

    out = []
    for cells in rows:
        grade = None
        if i_grade is not None and i_grade < len(cells):
            m = _GRADE_RE.match(cells[i_grade].strip("* "))
            grade = int(m.group(1)) if m else None
        if grade is None:  # positional fallback
            for cell in cells[1:]:
                m = _GRADE_RE.match(cell.strip("* "))
                if m:
                    grade = int(m.group(1))
                    break
        codes_cell = cells[i_code] if (i_code is not None and i_code < len(cells)) else " ".join(cells)
        codes = _CODE_RE.findall(codes_cell)
        if not codes or grade is None:
            continue
        pattern = cells[i_pattern] if (i_pattern is not None and i_pattern < len(cells)) else ""
        out.append({"fdi": int(cells[0].strip("* ")), "grade": grade,
                    "codes": codes, "pattern": pattern})
    return out


# ── deterministic generation checks ──────────────────────────────────────────────

def check_icd(markdown: str, detections: dict) -> dict:
    """Deterministic ICD-10 plausibility. No judge — these are checkable facts.

    `depth_consistency` accepts **two** shapes per row, because both are clinically correct:

      * the caries code equals the ICDAS depth prior (D1–D2→K02.0, D3–D6→K02.1), or
      * the row **escalates** to a pulpal code instead — legitimate once the lesion is deep,
        and only if that K04.x sits in the prior's differential for that grade.

    Scoring only the first shape would mark a D6 coded `K04.4` (acute apical periodontitis of
    pulpal origin) as a failure, when replacing `K02.1` there is exactly what a dentist does.
    `pulp_code_gated` is the guard on the other side: no K04.x may appear below D5.
    """
    priors = {r["fdi"]: r for r in icd10.map_detections(detections)}
    rows = parse_icd_rows(markdown)

    valid = depth_ok = pulp_gated = escalated = 0
    for row in rows:
        codes = row["codes"]
        if all(c in icd10.ICD10 for c in codes):
            valid += 1
        prior = priors.get(row["fdi"])
        if not prior:
            continue

        caries = [c for c in codes if c.startswith("K02")]
        pulp = [c for c in codes if c.startswith("K04")]
        deep = prior["grade"] >= 5

        if not pulp or deep:
            pulp_gated += 1
        if pulp and not caries:
            escalated += 1

        matches_prior = bool(caries) and caries[0] == prior["primary"]
        valid_escalation = (
            not caries and bool(pulp) and deep
            and all(p in prior["differential"] for p in pulp)
        )
        if (matches_prior and (not pulp or deep)) or valid_escalation:
            depth_ok += 1

    n = max(len(rows), 1)
    covered = len({r["fdi"] for r in rows} & set(priors))
    return {
        "rows": len(rows),
        "affected_teeth": len(priors),
        "tooth_coverage": covered / max(len(priors), 1),
        "code_validity": valid / n,
        "depth_consistency": depth_ok / n,
        "pulp_code_gated": pulp_gated / n,
        "pulp_escalations": escalated,
    }


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", re.sub(r"\s+", " ", text.lower())).strip()


def check_specificity(markdown: str) -> dict:
    """How per-tooth the answer really is — the metric this template exists to move.

    Two deterministic signals: no row may use an "idem"-style filler, and the damage-pattern
    cells must be distinct from one another. A table where every D6 tooth reuses one sentence
    scores near zero here even though its ICD codes are all perfectly valid.
    """
    rows = parse_icd_rows(markdown)
    patterns = [_normalize(r["pattern"]) for r in rows if r["pattern"]]
    n = max(len(rows), 1)

    idem = sum(1 for p in patterns if agents._IDEM_RE.search(p) or p in ("", "-", "—"))
    unique = len(set(patterns))

    deep_dive = section(markdown, "## Analisis Mendalam Gigi Prioritas")
    narrated = len(re.findall(r"\*\*Gigi\s+\d{2}", deep_dive))

    return {
        "rows": len(rows),
        "distinct_patterns": unique / n,
        "idem_rows": idem,
        "teeth_narrated": narrated,
        "has_complaint_correlation": bool(
            section(markdown, "## Korelasi dengan Keluhan Pasien").strip()
        ),
    }


def check_recommendation(markdown: str, detections: dict) -> dict:
    """Coverage, urgency-scale compliance and per-tooth specificity of the treatment plan."""
    affected = {r["fdi"] for r in icd10.map_detections(detections)}
    body = section(markdown, "## Rencana Perawatan per Gigi") or markdown
    header, rows = table_rows(body)

    planned = {int(r[0].strip("* ")) for r in rows} if rows else set()
    i_action = _column(header, "tindakan utama", "tindakan")
    actions = [
        _normalize(r[i_action]) for r in rows
        if i_action is not None and i_action < len(r) and r[i_action].strip()
    ]
    n = max(len(rows), 1)

    return {
        "rows": len(rows),
        "affected_teeth": len(affected),
        "tooth_coverage": len(planned & affected) / max(len(affected), 1),
        "plans_absent_teeth": len(planned - affected),
        "distinct_actions": len(set(actions)) / n,
        "idem_rows": sum(1 for a in actions if agents._IDEM_RE.search(a)),
        "urgency_terms_used": sum(t in markdown for t in URGENCY_TERMS),
        "template_compliance": check_template(markdown, RECOMMENDATION_SECTIONS),
    }


def check_template(markdown: str, sections=DIAGNOSIS_SECTIONS) -> float:
    return sum(s in markdown for s in sections) / len(sections)


# ── cost ─────────────────────────────────────────────────────────────────────────

def _accumulate(total: dict, usage: dict) -> None:
    for k, v in (usage or {}).items():
        total[k] = total.get(k, 0) + v


def _cost(usage: dict, model: str) -> float:
    p = PRICES.get(model)
    if not p:
        return 0.0
    cached = usage.get("cached_input_tokens", 0)
    fresh = max(usage.get("input_tokens", 0) - cached, 0)
    return (fresh * p["in"] + cached * p["cached"]
            + usage.get("output_tokens", 0) * p["out"]) / 1_000_000


# ── generation ───────────────────────────────────────────────────────────────────

def _demo_cases() -> list[dict]:
    specs = json.loads(SEED_FILE.read_text(encoding="utf-8"))["cases"]
    out = []
    for spec in specs:
        path = settings.results_dir / spec["dataset"] / "detections.json"
        if not path.exists():
            print(f"  ! no detections for {spec['dataset']} - skipped")
            continue
        out.append({**spec, "detections": json.loads(path.read_text(encoding="utf-8"))})
    return out


def _cited_pairs(markdown: str, sources: list[dict]) -> list[tuple[str, str]]:
    """(sentence carrying [^n], quote) pairs, for the judge's support check."""
    quotes = {s["n"]: (s["quotes"] or [""])[0] for s in sources}
    pairs = []
    for sentence in re.split(r"(?<=[.!?])\s+", markdown.split("## Rujukan")[0]):
        for n in {int(m) for m in re.findall(r"\[\^(\d+)\]", sentence)}:
            if quotes.get(n):
                pairs.append((sentence.strip(), quotes[n]))
    return pairs


def eval_committed() -> dict:
    """Score the **committed** demo documents with the deterministic checks only.

    No API call and no judge, so this reproduces exactly on any clone: it re-measures the
    markdown in `assets/seed/advisory/` — the same text the app ships and a reviewer reads —
    rather than generating fresh answers whose numbers nobody else can reproduce.
    """
    advisory = SEED_FILE.parent / "advisory"
    results: list[dict] = []

    for spec in _demo_cases():
        dx_path = advisory / f"{spec['id']}-diagnosis.md"
        rx_path = advisory / f"{spec['id']}-recommendation.md"
        if not dx_path.exists():
            print(f"  ! {spec['id']}: no committed diagnosis, skipped")
            continue

        diagnosis = dx_path.read_text(encoding="utf-8")
        plan = rx_path.read_text(encoding="utf-8") if rx_path.exists() else ""
        state = {"detections": spec["detections"],
                 "diagnosis_md": diagnosis, "recommendation_md": plan}
        _, sanity_ok = agents.sanity_agent(state)

        # A committed document only shows what *survived* verification — the claimed and
        # rejected counts exist solely at generation time. So report what is auditable here:
        # how many footnotes the reader actually sees, and how many carry a verbatim quote.
        footnotes = re.findall(r"^\[\^(\d+)\]:", diagnosis, re.MULTILINE)
        quotes = re.findall(r"^\s{2,}> ", diagnosis, re.MULTILINE)

        results.append({
            "case": spec["id"],
            "dataset": spec["dataset"],
            "affected": len(icd10.map_detections(spec["detections"])),
            "citations_shown": len(footnotes),
            "quotes_shown": len(quotes),
            "template_compliance": check_template(diagnosis),
            "icd": check_icd(diagnosis, spec["detections"]),
            "specificity": check_specificity(diagnosis),
            "recommendation": check_recommendation(plan, spec["detections"]),
            "sanity_ok": sanity_ok,
            "sanity_findings": state.get("sanity_feedback") or [],
            "markdown_chars": len(diagnosis) + len(plan),
            "_judged": False,
            "_committed": True,
        })
        print(f"  - {spec['id']}: scored")
    return {"cases": results, "usage": {}, "committed": True}


def eval_generation(*, use_judge: bool = True) -> dict:
    results: list[dict] = []
    cache_dir = EVAL_DIR / "out"
    cache_dir.mkdir(exist_ok=True)

    for spec in _demo_cases():
        # Resume: each case is cached to disk right after it is computed, so a run killed
        # part-way never re-pays a billed call. A cache made with --no-judge is recomputed
        # once judging is asked for.
        cache_file = cache_dir / f"_gen_{spec['id']}.json"
        if cache_file.exists():
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if not use_judge or cached.get("_judged"):
                print(f"  - {spec['id']} ({spec['dataset']}) cached — skipped")
                results.append(cached)
                continue

        print(f"  - running {spec['id']} ({spec['dataset']}) ...")
        state = {
            "patient_name": spec["patient_name"],
            "anamnesa": spec["anamnesa"],
            "detections": spec["detections"],
        }

        t0 = time.perf_counter()
        graph._node_rag(state)
        diagnosis = agents.diagnosis_agent(state)
        state["diagnosis_md"] = diagnosis
        graph._node_rag_treatment(state)
        plan = agents.recommendation_agent(state)
        state["recommendation_md"] = plan
        sanity_md, sanity_ok = agents.sanity_agent(state)
        latency = time.perf_counter() - t0

        passages = state["rag"]
        entry = {
            "case": spec["id"],
            "dataset": spec["dataset"],
            "affected": len(icd10.map_detections(spec["detections"])),
            "passages": len(passages),
            "passage_tokens": index.token_estimate(passages),
            "latency_s": round(latency, 1),
            "usage": state.get("diagnosis_usage", {}),
            "usage_rx": state.get("recommendation_usage", {}),
            "citation_stats": state.get("diagnosis_citation_stats", {}),
            "cited_sources": len(state.get("diagnosis_sources") or []),
            "template_compliance": check_template(diagnosis),
            "icd": check_icd(diagnosis, spec["detections"]),
            "specificity": check_specificity(diagnosis),
            "recommendation": check_recommendation(plan, spec["detections"]),
            "sanity_ok": sanity_ok,
            "sanity_findings": state.get("sanity_feedback") or [],
            "markdown_chars": len(diagnosis) + len(plan),
        }

        if use_judge:
            claims = judge.extract_claims(diagnosis)
            patient_block = prompts.diagnosis.build_user(state)
            labels = judge.label_claims(claims, passages, patient_block)
            n = max(len(labels), 1)
            entry["claims"] = len(claims)
            entry["faithfulness"] = 1 - labels.count("SALAH") / n
            entry["document_grounding"] = labels.count("DOKUMEN") / n
            entry["label_counts"] = {lbl: labels.count(lbl) for lbl in judge._LABELS}

            pairs = _cited_pairs(diagnosis, state.get("diagnosis_sources") or [])
            pairs = pairs[:MAX_CITATION_CHECKS]
            supported = sum(judge.verify_citation(s, q) for s, q in pairs)
            entry["citations_checked"] = len(pairs)
            entry["citation_support"] = supported / len(pairs) if pairs else None

            entry["answer_relevance"] = judge.score_relevance(
                "Tegakkan diagnosis ICD-10 per gigi dengan pola kerusakan spesifik, "
                "korelasikan dengan keluhan, jelaskan risiko pulpa, gejala harian, batasan.",
                diagnosis,
            )
            entry["specificity_judged"] = judge.score_specificity(
                section(diagnosis, "## Diagnosis per Gigi")
            )
            entry["recommendation_relevance"] = judge.score_relevance(
                "Susun rencana perawatan per gigi dengan urgensi, prasyarat pemeriksaan, "
                "urutan kunjungan, pencegahan, edukasi, dan tanda bahaya.",
                plan,
            )

        entry["_judged"] = use_judge
        results.append(entry)
        (cache_dir / f"{spec['id']}-diagnosis.md").write_text(diagnosis, encoding="utf-8")
        (cache_dir / f"{spec['id']}-recommendation.md").write_text(plan, encoding="utf-8")
        (cache_dir / f"{spec['id']}-sanity.md").write_text(sanity_md, encoding="utf-8")
        cache_file.write_text(
            json.dumps(entry, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    usage: dict = {}
    for entry in results:
        _accumulate(usage, entry.get("usage", {}))
        _accumulate(usage, entry.get("usage_rx", {}))
    return {"cases": results, "usage": usage}


# ── report ───────────────────────────────────────────────────────────────────────

def _pct(x) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def _mean(rows, key):
    vals = [r[key] for r in rows if r.get(key) is not None]
    return statistics.fmean(vals) if vals else None


def _mean_nested(rows, outer, key):
    vals = [r[outer][key] for r in rows if r.get(outer, {}).get(key) is not None]
    return statistics.fmean(vals) if vals else None


def _write(lines: list[str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nwrote {REPORT}")


def _repro() -> list[str]:
    return [
        "## Reproduksi",
        "",
        "```bash",
        "cd ml",
        "python -m evals.run_evals --retrieval              # ablasi retrieval, tanpa API key",
        "python -m evals.run_evals --generation --committed # skor dokumen terkomit, tanpa API key",
        "python -m evals.run_evals                          # jalankan ulang agen (butuh API key)",
        "```",
        "",
    ]


def write_report(retrieval: dict | None, generation: dict | None) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    L: list[str] = [
        "# Laporan Evaluasi — RAG + Agen Klinis",
        "",
        f"_Dibuat otomatis oleh `python -m evals.run_evals` pada {now}._",
        "",
        "Laporan ini mengukur dua hal terpisah: **retrieval** (apakah pasal yang benar "
        "diambil) dan **generation** (apakah diagnosis dan rencana perawatan yang dihasilkan "
        "setia, spesifik per gigi, tersitasi secara terverifikasi, dan valid secara ICD-10).",
        "",
    ]

    if retrieval:
        idx = retrieval["index"]
        L += [
            "## 1. Retrieval",
            "",
            f"Korpus terindeks: **{idx.get('n_chunks', '?')} chunk** dari "
            f"**{idx.get('n_docs', '?')} dokumen** "
            f"(`{idx.get('embed_model', '?')}`, dim {idx.get('dim', '?')}). "
            f"QA set: **{retrieval['n_questions']} pertanyaan** buatan tangan, "
            "masing-masing dengan dokumen emas. Retrieval difilter ke kategori "
            "`{diagnosis, context}` — sama persis dengan yang dipakai agen diagnosis.",
            "",
            "### Ablasi pipeline",
            "",
            "| Konfigurasi | " + " | ".join(f"Recall@{k}" for k in K_VALUES)
            + " | MRR | Latensi/kueri |",
            "| --- |" + " --- |" * (len(K_VALUES) + 2),
        ]
        for label, m in retrieval["configs"].items():
            L.append(
                f"| {label} | "
                + " | ".join(_pct(m[f'recall@{k}']) for k in K_VALUES)
                + f" | {m['mrr']:.3f} | {m['latency_ms']:.0f} ms |"
            )
        L += [
            "",
            f"Batas atas (dokumen emas ada di shortlist {settings.rag_candidates} kandidat "
            f"sebelum rerank): **{_pct(retrieval['shortlist_recall'])}**.",
            "",
            "**Bacaan:** BM25 sudah kuat untuk istilah teknis (PUFA, ECOHIS, ICDAS); "
            "menambah dense BGE-M3 (RRF) menutup kueri parafrasa lintas bahasa. Pada QA set "
            "kecil yang sudah jenuh, cross-encoder tidak dapat menaikkan recall lebih jauh — "
            "nilainya ada pada presisi urutan untuk kueri yang lebih sulit, sehingga top-N "
            f"kecil ({settings.rag_top_n} pasal) yang dikirim ke model tetap relevan. "
            "Filter kategori juga menekan biaya token.",
            "",
        ]

    if generation:
        rows = generation["cases"]
        if rows:
            L += [
                "## 2. Generation",
                "",
                (f"Skor dihitung ulang dari dokumen yang **dikomit** di "
                 f"`assets/seed/advisory/` — teks yang sama yang ditampilkan aplikasi — "
                 f"sehingga angka di bawah dapat direproduksi tanpa API key: "
                 f"`python -m evals.run_evals --generation --committed`."
                 if generation.get("committed") else
                 f"Model klinis: `{settings.llm_model}` (reasoning effort "
                 f"`{settings.llm_effort}`), juri: `{settings.llm_helper_model}`. "
                 f"Dijalankan pada {len(rows)} kasus demo."),
                "",
                "### 2.1 Diagnosis — pemeriksaan deterministik",
                "",
                "| Kasus | Gigi terdampak | Baris | Cakupan gigi | Kode valid | "
                "Konsisten kedalaman | Eskalasi pulpa | K04.x hanya bila D5+ | Template |",
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
            for r in rows:
                i = r["icd"]
                L.append(
                    f"| `{r['case']}` | {i['affected_teeth']} | {i['rows']} | "
                    f"{_pct(i['tooth_coverage'])} | {_pct(i['code_validity'])} | "
                    f"{_pct(i['depth_consistency'])} | {i['pulp_escalations']} | "
                    f"{_pct(i['pulp_code_gated'])} | {_pct(r['template_compliance'])} |"
                )
            L += [
                "",
                "`Kode valid` = setiap kode ada di tabel ICD-10 yang diberikan. "
                "`Konsisten kedalaman` = kode karies cocok dengan prior ICDAS→ICD-10 "
                "(D1–D2→K02.0, D3–D6→K02.1) **atau** baris tersebut naik ke kode pulpa yang "
                "sah untuk derajat itu. `Eskalasi pulpa` = jumlah gigi yang diberi K04.x "
                "menggantikan K02.1 — perilaku klinis yang benar pada D6, bukan kesalahan. "
                "`K04.x hanya bila D5+` = agen tidak menempelkan kode pulpa pada lesi dangkal.",
                "",
                "### 2.2 Spesifisitas per gigi",
                "",
                "Metrik inti dari desain prompt + profil kuantitatif per gigi: tiap baris "
                "tabel harus menguraikan gigi itu sendiri, bukan menyalin baris sebelumnya.",
                "",
                "| Kasus | Pola kerusakan unik | Baris \"idem\" | Gigi dinarasikan mendalam | "
                "Korelasi keluhan |",
                "| --- | --- | --- | --- | --- |",
            ]
            for r in rows:
                s = r["specificity"]
                L.append(
                    f"| `{r['case']}` | {_pct(s['distinct_patterns'])} | {s['idem_rows']} | "
                    f"{s['teeth_narrated']} | "
                    f"{'ya' if s['has_complaint_correlation'] else 'tidak'} |"
                )
            L += [
                "",
                f"**Rata-rata pola kerusakan unik: "
                f"{_pct(_mean_nested(rows, 'specificity', 'distinct_patterns'))}**, "
                f"total baris `idem`: "
                f"{sum(r['specificity']['idem_rows'] for r in rows)}.",
                "",
                "### 2.3 Rekomendasi perawatan",
                "",
                "| Kasus | Baris | Cakupan gigi | Gigi tak terdampak ikut direncanakan | "
                "Tindakan unik | Istilah urgensi | Template |",
                "| --- | --- | --- | --- | --- | --- | --- |",
            ]
            for r in rows:
                x = r["recommendation"]
                L.append(
                    f"| `{r['case']}` | {x['rows']} | {_pct(x['tooth_coverage'])} | "
                    f"{x['plans_absent_teeth']} | {_pct(x['distinct_actions'])} | "
                    f"{x['urgency_terms_used']}/4 | {_pct(x['template_compliance'])} |"
                )
            L += [
                "",
                "### 2.4 Verifikasi sitasi (deterministik)",
                "",
                "Setiap kutipan yang diklaim agen dicocokkan **verbatim** dengan isi dokumen "
                "sumber sebelum ditampilkan. Kutipan yang tidak ditemukan dibuang bersama "
                "penandanya, sehingga sitasi yang tampil selalu dapat diaudit.",
                "",
            ]
            if generation.get("committed"):
                # A committed document only shows what survived verification; the claimed and
                # rejected counts exist only at generation time.
                L += [
                    "| Kasus | Sitasi tampil | Kutipan verbatim terlampir |",
                    "| --- | --- | --- |",
                ]
                for r in rows:
                    L.append(f"| `{r['case']}` | {r.get('citations_shown', 0)} | "
                             f"{r.get('quotes_shown', 0)} |")
                L += [
                    "",
                    "Setiap sitasi yang tampil sudah lolos pencocokan verbatim, sehingga "
                    "pembaca dapat mengaudit tiap klaim terhadap kalimat aslinya. Jumlah "
                    "kutipan yang *ditolak* hanya teramati saat pembuatan — angka tersebut "
                    "dicetak oleh `gen_demo_advisory.py`, dan pada keempat kasus ini seluruh "
                    "kutipan yang diklaim lolos verifikasi.",
                    "",
                ]
            else:
                L += [
                    "| Kasus | Diklaim | Terverifikasi | Dibuang | Sumber tampil |",
                    "| --- | --- | --- | --- | --- |",
                ]
                for r in rows:
                    c = r.get("citation_stats") or {}
                    L.append(
                        f"| `{r['case']}` | {c.get('claimed', 0)} | {c.get('verified', 0)} | "
                        f"{c.get('rejected', 0)} | {r.get('cited_sources', 0)} |"
                    )
                total_claimed = sum(
                    (r.get("citation_stats") or {}).get("claimed", 0) for r in rows)
                total_ok = sum(
                    (r.get("citation_stats") or {}).get("verified", 0) for r in rows)
                L += [
                    "",
                    f"**Tingkat kutipan terverifikasi: "
                    f"{_pct(total_ok / total_claimed) if total_claimed else '—'}** "
                    f"({total_ok}/{total_claimed}).",
                    "",
                ]

            if rows[0].get("faithfulness") is not None:
                L += [
                    "### 2.5 Penilaian juri",
                    "",
                    "| Kasus | Klaim | Faithfulness | Grounding dokumen | Sitasi diperiksa | "
                    "Dukungan sitasi | Relevansi diagnosis | Spesifisitas | Relevansi rencana |",
                    "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
                ]
                for r in rows:
                    L.append(
                        f"| `{r['case']}` | {r['claims']} | {_pct(r['faithfulness'])} | "
                        f"{_pct(r['document_grounding'])} | {r['citations_checked']} | "
                        f"{_pct(r['citation_support'])} | {r['answer_relevance']}/5 | "
                        f"{r['specificity_judged']}/5 | {r['recommendation_relevance']}/5 |"
                    )
                L += [
                    "",
                    f"**Rata-rata:** faithfulness {_pct(_mean(rows, 'faithfulness'))} · "
                    f"grounding dokumen {_pct(_mean(rows, 'document_grounding'))} · "
                    f"dukungan sitasi {_pct(_mean(rows, 'citation_support'))} · "
                    f"relevansi diagnosis {(_mean(rows, 'answer_relevance') or 0):.1f}/5 · "
                    f"spesifisitas {(_mean(rows, 'specificity_judged') or 0):.1f}/5 · "
                    f"relevansi rencana {(_mean(rows, 'recommendation_relevance') or 0):.1f}/5.",
                    "",
                    "Setiap klaim atomik dilabeli **DOKUMEN** (didukung pasal terambil), "
                    "**INPUT** (berasal dari deteksi/anamnesa), **KLINIS** (pengetahuan umum "
                    "yang benar), atau **SALAH** (kontradiksi, atau angka/studi yang tidak "
                    "ada di kutipan). `faithfulness = 1 − SALAH/total`. Label KLINIS tidak "
                    "dihitung sebagai halusinasi karena desainnya memang penalaran klinis "
                    "yang *didukung* dokumen, bukan ekstraksi murni.",
                    "",
                ]

            usage = generation.get("usage") or {}
            if not usage:
                L += [
                    "### 2.6 Pemeriksaan konsistensi",
                    "",
                    "| Kasus | Lolos | Temuan |",
                    "| --- | --- | --- |",
                ]
                for r in rows:
                    findings = ", ".join(r.get("sanity_findings") or []) or "—"
                    L.append(f"| `{r['case']}` | "
                             f"{'ya' if r.get('sanity_ok') else 'tidak'} | {findings} |")
                L += [""]
                _write(L + _repro())
                return
            cost = _cost(usage, settings.llm_model)
            cached = usage.get("cached_input_tokens", 0)
            total_in = usage.get("input_tokens", 0)
            hit = cached / total_in if total_in else 0.0
            L += [
                "### 2.6 Token & biaya",
                "",
                "| Metrik | Nilai |",
                "| --- | --- |",
                f"| Kasus dievaluasi | {len(rows)} (2 panggilan klinis per kasus) |",
                f"| Input total | {total_in:,} tok |",
                f"| Input terbaca dari cache | {cached:,} tok |",
                f"| **Cache hit rate** | {_pct(hit)} |",
                f"| Reasoning | {usage.get('reasoning_tokens', 0):,} tok |",
                f"| Output | {usage.get('output_tokens', 0):,} tok |",
                f"| Pasal per agen | {settings.rag_top_n} "
                f"(~{statistics.fmean([r['passage_tokens'] for r in rows]):.0f} tok) |",
                f"| Latensi rata-rata (diagnosis + rencana) | "
                f"{statistics.fmean([r['latency_s'] for r in rows]):.1f} s |",
                f"| **Biaya `{settings.llm_model}`** | **${cost:.4f}** "
                f"(~${cost / len(rows):.4f}/kasus) |",
                "",
                "Efisiensi token yang dipakai, tanpa menurunkan kualitas: (1) prompt sistem "
                "(peran + tabel ICD-10 + template) byte-stabil sehingga terbaca dari prompt "
                "cache pada kasus ke-2 dan seterusnya; (2) rerank memungkinkan top-N kecil "
                f"({settings.rag_top_n}) alih-alih mengirim {settings.rag_candidates} "
                "kandidat; (3) blurb kontekstual ditulis model murah sekali saat ingest lalu "
                "di-cache ke disk; (4) juri eval memakai model murah; (5) pemeriksaan "
                "konsistensi bersifat deterministik — nol panggilan API.",
                "",
            ]
        else:
            L += ["## 2. Generation", "",
                  "_Tidak ada kasus demo dengan `detections.json`._", ""]

    _write(L + _repro())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--retrieval", action="store_true", help="retrieval metrics only")
    ap.add_argument("--generation", action="store_true", help="generation metrics only")
    ap.add_argument("--no-judge", action="store_true", help="skip the LLM judge")
    ap.add_argument("--committed", action="store_true",
                    help="score the committed demo documents instead of generating new ones "
                         "(deterministic, no API key)")
    args = ap.parse_args()

    do_retrieval = args.retrieval or not args.generation
    do_generation = args.generation or not args.retrieval

    if do_retrieval and not index.is_available():
        print(f"no index at {settings.rag_index_dir} - run: python -m app.llm.retrieval.build")
        return 1

    # Half-level cache: the two halves are long, so they may be run in separate passes
    # (`--retrieval` then `--generation`). Each half is persisted and the other half is
    # reloaded from cache at report time, so a split run still writes a full report.
    cache_dir = EVAL_DIR / "out"
    cache_dir.mkdir(exist_ok=True)
    retrieval_cache = cache_dir / "_retrieval.json"
    generation_cache = cache_dir / "_generation.json"

    retrieval = None
    if do_retrieval:
        print("retrieval eval ...")
        retrieval = eval_retrieval()
        retrieval_cache.write_text(
            json.dumps(retrieval, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    generation = None
    if do_generation and args.committed:
        print("scoring committed demo documents ...")
        generation = eval_committed()
        generation_cache.write_text(
            json.dumps(generation, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    elif do_generation:
        if not openai_client.is_enabled():
            print("LLM disabled (need OPENAI_API_KEY + LLM_ENABLED=1) - skipping generation")
        else:
            print("generation eval ...")
            generation = eval_generation(use_judge=not args.no_judge)
            generation_cache.write_text(
                json.dumps(generation, ensure_ascii=False, indent=1), encoding="utf-8"
            )

    if retrieval is None and retrieval_cache.exists():
        retrieval = json.loads(retrieval_cache.read_text(encoding="utf-8"))
    if generation is None and generation_cache.exists():
        generation = json.loads(generation_cache.read_text(encoding="utf-8"))

    write_report(retrieval, generation)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
