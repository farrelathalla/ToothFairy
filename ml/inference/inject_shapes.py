"""Fast path: compute per-tooth SHAPE (root curvature + proportions) from each demo patient's
panoramic and merge it into the already-committed detections.json — WITHOUT re-running the heavy
intraoral/RF-DETR pipeline. Runs only the two panoramic YOLO models (FDI + tooth-seg).

    python inference/inject_shapes.py            # original + set1..3

Idempotent: re-running just refreshes each tooth's `shape` field.
"""
import json
from pathlib import Path

from pipeline import PUB_ROOT, default_datasets
import run_tooth_seg_panoramic as rts


def main():
    from ultralytics import YOLO
    seg_model = YOLO(str(rts.SEG_MODEL))
    for ctx in default_datasets():
        det_path = PUB_ROOT / ctx.name / "detections.json"
        if not det_path.exists():
            print(f"[skip] {ctx.name}: no detections.json"); continue
        if not ctx.panoramic or not Path(ctx.panoramic).exists():
            print(f"[skip] {ctx.name}: no panoramic"); continue
        try:
            fdi_boxes = rts._fdi_boxes_from_yolo(ctx.out) or rts._fdi_boxes_direct(ctx.panoramic)
            shapes = rts.compute_shapes(ctx.panoramic, fdi_boxes, seg_model=seg_model)
        except Exception as e:
            print(f"[warn] {ctx.name}: shape compute failed: {e}"); continue

        det = json.load(open(det_path))
        n = 0
        for fdi, sh in shapes.items():
            if fdi in det["teeth"]:
                det["teeth"][fdi]["shape"] = sh; n += 1
        det.setdefault("meta", {})["has_tooth_shapes"] = True
        det["meta"].setdefault("models", {})["tooth_shape"] = rts.SEG_MODEL.parent.name + " (YOLO26x-seg)"
        json.dump(det, open(det_path, "w"), indent=2)
        # mirror the default patient to the legacy path the viewer loads first
        if ctx.name == "original":
            legacy = PUB_ROOT.parent / "detections.json"
            if legacy.exists():
                json.dump(det, open(legacy, "w"), indent=2)
        print(f"[ok] {ctx.name}: injected shape into {n} teeth -> {det_path}")


if __name__ == "__main__":
    main()
