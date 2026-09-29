"""End-to-end inference for one or more patient captures.

    python inference/run_all.py                 # (re)build the demo datasets: original, set1..3
    python inference/run_all.py NAME  FOLDER     # run one custom capture folder -> results/NAME

Per capture: YOLO (FDI intraoral per view, panoramic, tooth/caries seg per view)
       -> RF-DETR (ICDAS D1-D6 per view) -> DoubleU-Net panoramic caries
       -> fuse across views into web/public/results/<name>/detections.json
       -> per-view result overlays. A datasets.json manifest lists them for the viewer.
"""
import json, shutil, sys, traceback
from pathlib import Path

import cv2

from pipeline import Ctx, OUT_ROOT, PUB_ROOT, ANGLE_LABEL, ctx_from_dir, default_datasets
import run_yolo, run_rfdetr, run_panoramic_seg, run_tooth_seg_panoramic, fuse, render_overlays


def _safe(fn, ctx, name):
    try:
        fn(ctx)
    except Exception as e:
        print(f"[warn] {name} failed for {ctx.name}: {e}")
        traceback.print_exc()


def thumbnail(ctx: Ctx):
    """Small preview for the dataset picker: prefer the front view, else any view/panoramic."""
    src = ctx.angles.get("front") or next(iter(ctx.angles.values()), None) or ctx.panoramic
    if not src:
        return None
    img = cv2.imread(src)
    if img is None:
        return None
    h, w = img.shape[:2]
    tw = 320
    img = cv2.resize(img, (tw, int(h * tw / w)), interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(ctx.pub / "thumb.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return "thumb.jpg"


def process(ctx: Ctx):
    print(f"\n########## {ctx.name}  views={list(ctx.angles)} pano={bool(ctx.panoramic)} ##########")
    _safe(run_yolo.run, ctx, "run_yolo")
    _safe(run_rfdetr.run, ctx, "run_rfdetr")
    _safe(run_panoramic_seg.run, ctx, "run_panoramic_seg")
    _safe(run_tooth_seg_panoramic.run, ctx, "run_tooth_seg_panoramic")
    _safe(fuse.run, ctx, "fuse")
    _safe(render_overlays.run, ctx, "render_overlays")
    if ctx.do_xai:
        try:
            import run_xai
            _safe(run_xai.run, ctx, "run_xai")
        except Exception as e:
            print("[warn] run_xai unavailable:", e)
    thumb = thumbnail(ctx)
    return {
        "id": ctx.name,
        "label": ctx.name.capitalize(),
        "views": [{"key": k, "label": ANGLE_LABEL.get(k, k)} for k in ctx.angles],
        "has_panoramic": bool(ctx.panoramic),
        "detections": f"results/{ctx.name}/detections.json",
        "overlays": f"results/{ctx.name}/overlays/overlays.json",
        "thumb": f"results/{ctx.name}/{thumb}" if thumb else None,
    }


def write_manifest(entries):
    PUB_ROOT.mkdir(parents=True, exist_ok=True)
    json.dump({"datasets": entries}, open(PUB_ROOT / "datasets.json", "w"), indent=2)
    print("\nwrote", PUB_ROOT / "datasets.json", "->", [e["id"] for e in entries])


def mirror_default(default_id="original"):
    """Keep the legacy web/public/detections.json + overlays/ pointing at one dataset so the
    viewer works even before the dataset switcher loads."""
    src_det = PUB_ROOT / default_id / "detections.json"
    if src_det.exists():
        shutil.copy(src_det, PUB_ROOT.parent / "detections.json")
    src_ov = PUB_ROOT / default_id / "overlays"
    dst_ov = PUB_ROOT.parent / "overlays"
    if src_ov.exists():
        dst_ov.mkdir(parents=True, exist_ok=True)
        for f in src_ov.iterdir():
            shutil.copy(f, dst_ov / f.name)


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        # single custom capture: run_all.py NAME FOLDER
        name, folder = sys.argv[1], sys.argv[2]
        ctx = ctx_from_dir(name, folder)
        entry = process(ctx)
        print(json.dumps(entry))
    else:
        entries = []
        for ctx in default_datasets():
            entries.append(process(ctx))
        write_manifest(entries)
        mirror_default("original")
        print("\nDone. Start the viewer with:  cd app && npm run dev")
