"""Run the RF-DETR-2XL caries ICDAS model (D1-D6 bounding boxes) on every intraoral view.

Mirrors the 'Caries Bounding Box' notebook: RFDETR2XLarge(resolution=880, num_classes=7),
classes D1..D6 (id 1..6; id 0 is the COCO super-placeholder). Runs on each captured view
so fuse.py can attach an ICDAS floor grade per FDI. Writes <ctx.out>/rfdetr_raw.json:
  { "angles": { "<view>": {image_wh, dets:[{cls,grade,conf,xyxy}]}, ... } }

Skips gracefully if the rfdetr package is not installed.
"""
import json
from pathlib import Path

from pipeline import Ctx, TOOLS, default_datasets

CKPT = TOOLS / "Caries Bounding Box" / "model.pth"
CLASSES = ["D1", "D2", "D3", "D4", "D5", "D6"]  # category ids 1..6
CONF = 0.30  # ~ best-F1 operating point from the notebook


def _load_model():
    from rfdetr import RFDETR2XLarge
    try:
        model = RFDETR2XLarge(resolution=880, num_classes=7, pretrain_weights=str(CKPT))
    except TypeError:
        model = RFDETR2XLarge(resolution=880, num_classes=7)
        model.model.model.load_state_dict(__import__("torch").load(CKPT, map_location="cpu"), strict=False)
    # the notebook optimizes the model before inference — replicate for exact parity
    try:
        model.optimize_for_inference()
    except Exception as e:
        print("optimize_for_inference skipped:", e)
    return model


def _predict(model, path):
    from PIL import Image
    img = Image.open(path).convert("RGB")
    det = model.predict(img, threshold=CONF)
    dets = []
    for box, cid, conf in zip(det.xyxy, det.class_id, det.confidence):
        idx = int(cid) - 1  # id 1..6 -> D1..D6
        name = CLASSES[idx] if 0 <= idx < len(CLASSES) else f"id{int(cid)}"
        dets.append({"cls": name, "grade": idx + 1, "conf": round(float(conf), 4),
                     "xyxy": [round(float(v), 2) for v in box]})
    return list(img.size), dets


def run(ctx: Ctx):
    try:
        model = _load_model()
    except Exception as e:
        print("rfdetr not available, skipping:", e)
        return
    out = {"angles": {}}
    for view, path in ctx.angles.items():
        if not Path(path).exists():
            continue
        wh, dets = _predict(model, path)
        out["angles"][view] = {"image_wh": wh, "dets": dets}
        grades = ", ".join(f"D{g}" for g in sorted({d["grade"] for d in dets})) or "none"
        print(f"  {view:11s}: {len(dets)} caries boxes [{grades}]")
    json.dump(out, open(ctx.out / "rfdetr_raw.json", "w"), indent=2)
    print("wrote", ctx.out / "rfdetr_raw.json")


if __name__ == "__main__":
    run(default_datasets()[0])
