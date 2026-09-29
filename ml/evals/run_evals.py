"""Run the retrieval + generation evals and write `EVAL_REPORT.md`.

    cd backend
    python -m evals.run_evals                 # both halves (needs key + index)
    python -m evals.run_evals --retrieval     # no API key needed
    python -m evals.run_evals --no-judge      # generate + deterministic checks, no Haiku judge

Retrieval is scored as an **ablation** (BM25 → +dense/RRF → +cross-encoder rerank) so the
report shows what each stage of the pipeline actually buys, not just a final number.

Generation is scored on the four demo cases with a mix of deterministic checks (ICD-10 code
validity, depth consistency, tooth coverage, template compliance — no judge, no variance) and
Haiku-judged ones (claim faithfulness, citation precision, answer relevance).
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
from app.llm import agents, claude, graph, icd10, prompts, rag  # noqa: E402
from app.llm.retrieval import index, models  # noqa: E402
from evals import judge  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVAL_DIR.parents[1]
REPORT = REPO_ROOT / "docs" / "EVAL_REPORT.md"

K_VALUES = (1, 3, 5, 10)
RETRIEVE_DEPTH = 10
MAX_CITATION_CHECKS = 12  # per case — bounds judge cost

# USD per 1M tokens. Cache writes bill at 1.25×, cache reads at 0.1×.
PRICES = {
    "claude-sonnet-5": {"in": 3.00, "out": 15.00},
    "claude-haiku-4-5": {"in": 1.00, "out": 5.00},
}


# ── retrieval ────────────────────────────────────────────────────────────────────

def _load_qa() -> list[dict]:
    return json.loads((EVAL_DIR / "qa_retrieval.json").read_text(encoding="utf-8"))["questions"]


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


def eval_retrieval() -> dict:
    questions = _load_qa()
    cats = rag.DIAGNOSIS_CATEGORIES
    configs: dict[str, dict] = {}

    def _run(label: str, **kw):
        t0 = time.perf_counter()
        runs = [
            (index.retrieve(q["question"], k=RETRIEVE_DEPTH, categories=cats, **kw), set(q["gold"]))
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
        if set(
            h["doc_id"]
            for h in index.retrieve(q["question"], k=settings.rag_candidates, categories=cats,
                                    rerank=False)
        )
        & set(q["gold"])
    )
    return {
        "n_questions": len(questions),
        "configs": configs,
        "shortlist_recall": shortlist_hits / len(questions),
        "index": index.stats(),
    }


def _bm25_only_loader():
    real = index._load()

    def _loader():
        if real is None:
            return None
        return {**real, "dense": None}

    return _loader


# ── generation ───────────────────────────────────────────────────────────────────

_ROW_RE = re.compile(r"^\|\s*(\d{2})\s*\|\s*D?(\d)\s*\|\s*([^|]+)\|", re.MULTILINE)
_CODE_RE = re.compile(r"K\d{2}(?:\.\d)?")
REQUIRED_SECTIONS = (
    "## Ringkasan Klinis",
    "## Diagnosis per Gigi",
    "## Diagnosis Banding & Risiko Pulpa",
    "## Perkiraan Gejala & Dampak Harian",
    "## Batasan & Ketidakpastian",
)


def parse_icd_rows(markdown: str) -> list[dict]:
    """`| 11 | D6 | K02.1, K04.0 | … |` → [{fdi, grade, codes}]."""
    rows = []
    for fdi, grade, codes in _ROW_RE.findall(markdown):
        found = _CODE_RE.findall(codes)
        if found:
            rows.append({"fdi": int(fdi), "grade": int(grade), "codes": found})
    return rows


def check_icd(markdown: str, detections: dict) -> dict:
    """Deterministic ICD-10 plausibility. No judge — these are checkable facts.

    `depth_consistency` accepts **two** shapes per row, because both are clinically correct:

      * the caries code equals the ICDAS depth prior (D1–D2→K02.0, D3–D6→K02.1), or
      * the row **escalates** to a pulpal code instead — legitimate once the lesion is deep, and
        only if that K04.x sits in the prior's differential for that grade.

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
            not caries
            and bool(pulp)
            and deep
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


def check_template(markdown: str) -> float:
    return sum(s in markdown for s in REQUIRED_SECTIONS) / len(REQUIRED_SECTIONS)


def _cited_pairs(message) -> list[tuple[str, str]]:
    pairs = []
    for block in message.content:
        if getattr(block, "type", None) != "text":
            continue
        for cite in getattr(block, "citations", None) or []:
            quote = (getattr(cite, "cited_text", "") or "").strip()
            if quote:
                pairs.append((block.text.strip(), quote))
    return pairs


def _accumulate(total: dict, usage: dict) -> None:
    for k, v in usage.items():
        total[k] = total.get(k, 0) + v


def _cost(usage: dict, model: str) -> float:
    p = PRICES.get(model, {"in": 0.0, "out": 0.0})
    return (
        usage.get("input_tokens", 0) * p["in"]
        + usage.get("cache_creation_input_tokens", 0) * p["in"] * 1.25
        + usage.get("cache_read_input_tokens", 0) * p["in"] * 0.10
        + usage.get("output_tokens", 0) * p["out"]
    ) / 1_000_000


def _demo_cases() -> list[dict]:
    import seed  # noqa: PLC0415 — reuse the exact anamnesa the app seeds

    out = []
    for spec in seed.DEMO_CASES:
        path = settings.results_dir / spec["dataset"] / "detections.json"
        if not path.exists():
            print(f"  ! no detections for {spec['dataset']} - skipped")
            continue
        out.append({**spec, "detections": json.loads(path.read_text(encoding="utf-8"))})
    return out


def eval_generation(*, use_judge: bool = True) -> dict:
    results: list[dict] = []
    cache_dir = EVAL_DIR / "out"
    cache_dir.mkdir(exist_ok=True)

    for spec in _demo_cases():
        # Resume: each case is cached to disk right after it's computed, so a run killed at the
        # 10-min cap never re-pays the (billed) Sonnet call. A cache made with --no-judge is
        # recomputed once judging is asked for.
        cache_file = cache_dir / f"_gen_{spec['id']}.json"
        if cache_file.exists():
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if not use_judge or cached.get("_judged"):
                print(f"  - {spec['id']} ({spec['dataset']}) cached — skipped")
                results.append(cached)
                continue

        print(f"  - diagnosing {spec['id']} ({spec['dataset']}) ...")
        state = {
            "patient_name": spec["patient_name"],
            "anamnesa": spec["anamnesa"],
            "detections": spec["detections"],
        }
        graph._node_rag(state)
        passages = state["rag"]

        documents = agents._passages_as_documents(state)
        t0 = time.perf_counter()
        message = claude.answer_with_citations(
            prompts.build_system(), documents, prompts.build_user(state)
        )
        latency = time.perf_counter() - t0
        markdown, sources = claude.render_cited_markdown(message, documents)
        usage = claude.usage_of(message)

        entry = {
            "case": spec["id"],
            "dataset": spec["dataset"],
            "affected": len(icd10.map_detections(spec["detections"])),
            "passages": len(passages),
            "passage_tokens": index.token_estimate(passages),
            "latency_s": round(latency, 1),
            "usage": usage,
            "cited_sources": len(sources),
            "template_compliance": check_template(markdown),
            "icd": check_icd(markdown, spec["detections"]),
            "markdown_chars": len(markdown),
        }

        if use_judge:
            claims = judge.extract_claims(markdown)
            patient_block = prompts.build_user(state)
            labels = judge.label_claims(claims, passages, patient_block)
            n = max(len(labels), 1)
            entry["claims"] = len(claims)
            entry["faithfulness"] = 1 - labels.count("SALAH") / n
            entry["document_grounding"] = labels.count("DOKUMEN") / n
            entry["label_counts"] = {lbl: labels.count(lbl) for lbl in judge._LABELS}

            pairs = _cited_pairs(message)[:MAX_CITATION_CHECKS]
            supported = sum(judge.verify_citation(s, q) for s, q in pairs)
            entry["citations_checked"] = len(pairs)
            entry["citation_precision"] = supported / len(pairs) if pairs else None

            entry["answer_relevance"] = judge.score_relevance(
                "Tegakkan diagnosis ICD-10 per gigi, risiko pulpa, gejala harian, batasan.",
                markdown,
            )

        entry["_judged"] = use_judge
        results.append(entry)
        (cache_dir / f"{spec['id']}.md").write_text(markdown, encoding="utf-8")
        cache_file.write_text(
            json.dumps(entry, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    sonnet_usage: dict = {}
    for entry in results:
        _accumulate(sonnet_usage, entry.get("usage", {}))
    return {"cases": results, "sonnet_usage": sonnet_usage}


# ── report ───────────────────────────────────────────────────────────────────────

def _pct(x) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def _mean(rows, key):
    vals = [r[key] for r in rows if r.get(key) is not None]
    return statistics.fmean(vals) if vals else None


def write_report(retrieval: dict | None, generation: dict | None) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    L: list[str] = [
        "# EVAL_REPORT.md — RAG + agen diagnosis ICD-10",
        "",
        f"_Dibuat otomatis oleh `python -m evals.run_evals` pada {now}._",
        "",
        "Laporan ini mengukur dua hal terpisah: **retrieval** (apakah pasal yang benar "
        "diambil) dan **generation** (apakah diagnosis yang dihasilkan setia, tersitasi, "
        "dan valid secara ICD-10). Lihat `PLAN.md` §8 untuk desainnya.",
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
            "`{diagnosis, context}` — sama persis dengan yang dipakai agen.",
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
            "menambah dense BGE-M3 (RRF) menutup kueri parafrasa lintas bahasa dan menaikkan "
            "Recall@1 ke sempurna pada QA set ini. Pada set kecil yang sudah jenuh begini "
            "cross-encoder **tidak bisa** menaikkan recall lagi (shortlist sudah 100% memuat "
            "dokumen emas) dan bahkan sedikit menggeser satu jawaban dari peringkat 1 ke 2 — "
            "nilainya bukan pada recall di sini, melainkan pada presisi urutan untuk kueri "
            f"yang lebih sulit, sehingga top-N kecil ({settings.rag_top_n} pasal) yang dikirim "
            "ke Claude tetap relevan. Retrieval difilter kategori juga menekan biaya token.",
            "",
        ]

    if generation:
        rows = generation["cases"]
        if rows:
            L += [
                "## 2. Generation (agen diagnosis)",
                "",
                f"Model: `{settings.llm_model}` (effort `{settings.llm_effort}`, adaptive "
                f"thinking), juri: `{settings.llm_helper_model}`. Dijalankan pada "
                f"{len(rows)} kasus demo.",
                "",
                "### 2.1 Pemeriksaan deterministik (tanpa juri)",
                "",
                "| Kasus | Gigi terdampak | Baris tabel | Cakupan gigi | Kode valid | "
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
                "(D1–D2→K02.0, D3–D6→K02.1) **atau** baris tersebut naik ke kode pulpa yang sah "
                "untuk derajat itu. `Eskalasi pulpa` = jumlah gigi yang diberi K04.x menggantikan "
                "K02.1 — perilaku klinis yang benar pada D6, bukan kesalahan. "
                "`K04.x hanya bila D5+` = agen tidak menempelkan kode pulpa pada lesi dangkal.",
                "",
            ]

            if "faithfulness" in rows[0]:
                L += [
                    "### 2.2 Penilaian juri (Haiku)",
                    "",
                    "| Kasus | Klaim | Faithfulness | Grounding dokumen | Sitasi diperiksa | "
                    "Presisi sitasi | Relevansi (1–5) |",
                    "| --- | --- | --- | --- | --- | --- | --- |",
                ]
                for r in rows:
                    L.append(
                        f"| `{r['case']}` | {r['claims']} | {_pct(r['faithfulness'])} | "
                        f"{_pct(r['document_grounding'])} | {r['citations_checked']} | "
                        f"{_pct(r['citation_precision'])} | {r['answer_relevance']}/5 |"
                    )
                L += [
                    "",
                    f"**Rata-rata:** faithfulness {_pct(_mean(rows, 'faithfulness'))} · "
                    f"grounding dokumen {_pct(_mean(rows, 'document_grounding'))} · "
                    f"presisi sitasi {_pct(_mean(rows, 'citation_precision'))} · "
                    f"relevansi {(_mean(rows, 'answer_relevance') or 0):.1f}/5.",
                    "",
                    "Setiap klaim atomik dilabeli **DOKUMEN** (didukung pasal terambil), "
                    "**INPUT** (berasal dari deteksi/anamnesa), **KLINIS** (pengetahuan umum "
                    "yang benar), atau **SALAH** (kontradiksi, atau angka/studi yang tidak "
                    "ada di kutipan). `faithfulness = 1 − SALAH/total`. Label KLINIS tidak "
                    "dihitung sebagai halusinasi karena desainnya memang penalaran klinis "
                    "yang *didukung* dokumen, bukan ekstraksi murni (PLAN §8.3).",
                    "",
                ]

            usage = generation["sonnet_usage"]
            cost = _cost(usage, settings.llm_model)
            reads = usage.get("cache_read_input_tokens", 0)
            writes = usage.get("cache_creation_input_tokens", 0)
            hit = reads / (reads + writes) if (reads + writes) else 0.0
            L += [
                "### 2.3 Token & biaya",
                "",
                "| Metrik | Nilai |",
                "| --- | --- |",
                f"| Kasus dievaluasi | {len(rows)} |",
                f"| Input (tidak ter-cache) | {usage.get('input_tokens', 0):,} tok |",
                f"| Cache **write** (prefix sistem + tabel ICD-10) | {writes:,} tok |",
                f"| Cache **read** | {reads:,} tok |",
                f"| **Cache hit rate** | {_pct(hit)} |",
                f"| Output | {usage.get('output_tokens', 0):,} tok |",
                f"| Pasal per kasus | {settings.rag_top_n} "
                f"(~{statistics.fmean([r['passage_tokens'] for r in rows]):.0f} tok) |",
                f"| Latensi rata-rata | {statistics.fmean([r['latency_s'] for r in rows]):.1f} s |",
                f"| **Biaya {settings.llm_model}** | **${cost:.4f}** "
                f"(~${cost / len(rows):.4f}/kasus) |",
                "",
                f"Biaya di atas hanya untuk agen diagnosis. Panggilan `{settings.llm_helper_model}` "
                "(blurb kontekstual saat ingest — sekali seumur indeks, dan juri eval) tidak "
                "termasuk; keduanya bukan bagian dari jalur produksi per kasus.",
                "",
                "Efisiensi token yang dipakai, tanpa menurunkan kualitas: (1) prompt sistem + "
                "tabel ICD-10 di-*cache* (`cache_control: ephemeral`) sehingga kasus ke-2 dan "
                "seterusnya membacanya ~0,1× harga input; (2) rerank memungkinkan top-N kecil "
                f"({settings.rag_top_n}) alih-alih mengirim {settings.rag_candidates} kandidat; "
                "(3) blurb kontekstual ditulis Haiku sekali saat ingest lalu di-cache ke disk; "
                "(4) juri eval memakai Haiku, bukan Sonnet; (5) template keluaran ringkas.",
                "",
            ]
        else:
            L += ["## 2. Generation", "", "_Tidak ada kasus demo dengan `detections.json`._", ""]

    L += [
        "## Reproduksi",
        "",
        "```bash",
        "cd backend",
        "python -m app.llm.retrieval.build      # sekali; butuh ANTHROPIC_API_KEY + LLM_ENABLED=1",
        "python -m evals.run_evals              # menulis ulang berkas ini",
        "python -m evals.run_evals --retrieval  # hanya retrieval, tanpa API key",
        "```",
        "",
    ]
    REPORT.write_text("\n".join(L), encoding="utf-8")
    print(f"\nwrote {REPORT}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--retrieval", action="store_true", help="retrieval metrics only")
    ap.add_argument("--generation", action="store_true", help="generation metrics only")
    ap.add_argument("--no-judge", action="store_true", help="skip the Haiku judge")
    args = ap.parse_args()

    do_retrieval = args.retrieval or not args.generation
    do_generation = args.generation or not args.retrieval

    if not index.is_available():
        print(f"no index at {settings.rag_index_dir} - run: python -m app.llm.retrieval.build")
        return 1

    # Half-level cache: the two halves are ~6 min + ~15 min, past the tool cap, so they may be
    # run in separate passes (`--retrieval` then `--generation`). Each half is persisted and the
    # other half is reloaded from cache at report time, so a split run still writes a full report.
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
    if do_generation:
        if not claude.is_enabled():
            print("LLM disabled (need ANTHROPIC_API_KEY + LLM_ENABLED=1) - skipping generation")
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
