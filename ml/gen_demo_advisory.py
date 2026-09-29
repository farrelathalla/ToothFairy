"""Regenerate the committed advisory markdown for the demo cases.

    cd ml && python gen_demo_advisory.py [case-id ...]

The output lands in `assets/seed/advisory/`, which the gateway loads at seed time. Committing
it is what lets a fresh clone show complete demo cases with **no API key and no model
weights** — the database itself is never committed, so seeding is the only place these can be
restored from. Existing files are skipped unless `--force` is passed, so a run interrupted
part-way never re-pays for work already done.
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from app.config import REPO_ROOT, settings  # noqa: E402
from app.llm import agents, graph, openai_client, toothprofile  # noqa: E402

SEED = REPO_ROOT / "assets" / "seed"
OUT = SEED / "advisory"


def main(argv: list[str]) -> int:
    force = "--force" in argv
    wanted = {a for a in argv if not a.startswith("--")}

    if not openai_client.is_enabled():
        print("LLM disabled — set OPENAI_API_KEY and LLM_ENABLED=1")
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    specs = json.loads((SEED / "demo_cases.json").read_text(encoding="utf-8"))["cases"]

    for spec in specs:
        if wanted and spec["id"] not in wanted:
            continue
        target = OUT / f"{spec['id']}-diagnosis.md"
        if target.exists() and not force:
            print(f"- {spec['id']}: already generated, skipped")
            continue

        detections_path = settings.results_dir / spec["dataset"] / "detections.json"
        if not detections_path.exists():
            print(f"! {spec['id']}: no detections for {spec['dataset']}, skipped")
            continue

        state = {
            "patient_name": spec["patient_name"],
            "anamnesa": spec["anamnesa"],
            "detections": json.loads(detections_path.read_text(encoding="utf-8")),
        }
        affected = len(toothprofile.profiles(state["detections"]))
        print(f"- {spec['id']} ({spec['dataset']}, {affected} affected teeth) ...", flush=True)

        started = time.time()
        out = graph.run_graph(state)

        for kind, field in (("diagnosis", "diagnosis_md"),
                            ("recommendation", "recommendation_md"),
                            ("sanity", "sanity_md")):
            (OUT / f"{spec['id']}-{kind}.md").write_text(out[field], encoding="utf-8")

        print(f"  done in {time.time() - started:.0f}s · "
              f"passages {len(out.get('rag') or [])}/{len(out.get('rag_treatment') or [])} · "
              f"citations {out.get('diagnosis_citation_stats')} · "
              f"sanity_ok={out.get('sanity_ok')} {out.get('sanity_feedback') or ''}", flush=True)
        for key in ("diagnosis_error", "recommendation_error"):
            if out.get(key):
                print(f"  ! {key}: {out[key]}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
