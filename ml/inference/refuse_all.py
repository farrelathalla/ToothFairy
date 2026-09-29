"""Re-run ONLY fusion + overlay rendering for the demo datasets (no model inference).

Use after tweaking fuse.py / render_overlays.py — it re-reads the cached yolo_raw / rfdetr_raw
/ panoramic_caries JSON in each dataset's out/ dir, so it's fast. Rewrites detections.json,
overlays, thumbnails and the datasets.json manifest.
"""
import json
import fuse, render_overlays, run_all
from pipeline import default_datasets, ANGLE_LABEL, PUB_ROOT

if __name__ == "__main__":
    entries = []
    for ctx in default_datasets():
        if not (ctx.out / "yolo_raw.json").exists():
            print(f"skip {ctx.name}: no cached yolo_raw.json (run run_all first)"); continue
        print(f"\n=== re-fuse {ctx.name} ===")
        fuse.run(ctx)
        render_overlays.run(ctx)
        thumb = run_all.thumbnail(ctx)
        entries.append({
            "id": ctx.name, "label": ctx.name.capitalize(),
            "views": [{"key": k, "label": ANGLE_LABEL.get(k, k)} for k in ctx.angles],
            "has_panoramic": bool(ctx.panoramic),
            "detections": f"results/{ctx.name}/detections.json",
            "overlays": f"results/{ctx.name}/overlays/overlays.json",
            "thumb": f"results/{ctx.name}/{thumb}" if thumb else None,
        })
    json.dump({"datasets": entries}, open(PUB_ROOT / "datasets.json", "w"), indent=2)
    run_all.mirror_default("original")
    print("\nrewrote datasets.json ->", [e["id"] for e in entries])
