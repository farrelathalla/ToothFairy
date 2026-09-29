"""Run the Ultralytics YOLO models on every provided view and dump raw detections.

Models (per the provided notebooks):
  - FDI Intraoral        : YOLO26x detect, classes = FDI codes (11..48)   -> tooth boxes
  - FDI Panoramic        : YOLO26x detect, classes = 32 FDI codes 11..48  -> tooth boxes
  - Teeth Seg Intraoral  : YOLO26x-seg,   classes = [Caries,Cavity,Crack,Tooth] polygons

The three INTRAORAL models run on EACH captured view (front/side/up/bottom) — the same
tooth may appear in several views and fuse.py keeps the strongest evidence. The panoramic
models run once on the panoramic.

Output: <ctx.out>/yolo_raw.json
  { "angles": { "<view>": {image_wh, fdi:[...], seg:[...]}, ... },
    "fdi_panoramic": {image_wh, dets:[...]} }   # fdi_panoramic omitted if no panoramic
"""
import json
from pathlib import Path
import numpy as np
import cv2
from ultralytics import YOLO

from pipeline import Ctx, TOOLS, default_datasets

# The FDI-Panoramic model was trained on CLAHE-enhanced radiographs (clip 2.0, 8x8),
# baked offline. Its notebook is explicit: "any new image must get the same CLAHE
# before" inference. We replicate it exactly here.
CLAHE_CLIP = 2.0
CLAHE_GRID = 8


def clahe_panoramic(path):
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    clahe = cv2.createCLAHE(clipLimit=CLAHE_CLIP, tileGridSize=(CLAHE_GRID, CLAHE_GRID))
    enh = clahe.apply(img)
    return cv2.cvtColor(enh, cv2.COLOR_GRAY2BGR)  # 3-channel for YOLO


def boxes_from(res):
    out = []
    names = res.names
    b = res.boxes
    if b is None:
        return out
    xyxy = b.xyxy.cpu().numpy()
    cls = b.cls.cpu().numpy().astype(int)
    conf = b.conf.cpu().numpy()
    for i in range(len(cls)):
        out.append({
            "cls": names[int(cls[i])],
            "conf": round(float(conf[i]), 4),
            "xyxy": [round(float(v), 2) for v in xyxy[i]],
        })
    return out


def polys_from(res):
    out = []
    names = res.names
    if res.masks is None or res.boxes is None:
        return out
    cls = res.boxes.cls.cpu().numpy().astype(int)
    conf = res.boxes.conf.cpu().numpy()
    xyxy = res.boxes.xyxy.cpu().numpy()
    polys = res.masks.xy  # list of (N,2) arrays in pixel coords
    for i in range(len(cls)):
        p = polys[i]
        out.append({
            "cls": names[int(cls[i])],
            "conf": round(float(conf[i]), 4),
            "xyxy": [round(float(v), 2) for v in xyxy[i]],
            "polygon": [[round(float(x), 1), round(float(y), 1)] for x, y in p],
        })
    return out


def run(ctx: Ctx):
    result = {"angles": {}}

    # load the intraoral models once, reuse across all views
    m_fdi = YOLO(str(TOOLS / "FDI Intraoral" / "model.pt"))
    m_seg = YOLO(str(TOOLS / "Teeth Segmentation Intraoral" / "model.pt"))

    from collections import Counter
    for view, path in ctx.angles.items():
        if not Path(path).exists():
            print(f"[warn] {view}: {path} missing, skipping"); continue
        # low conf: heavily decayed teeth score low but we still want their FDI slot so the
        # RF-DETR grade / caries polygon can attach. Duplicate FDIs are de-duped in fuse.py.
        rf = m_fdi.predict(path, imgsz=640, conf=0.08, verbose=False)[0]
        rs = m_seg.predict(path, imgsz=960, conf=0.25, verbose=False)[0]
        result["angles"][view] = {
            "image_wh": [rf.orig_shape[1], rf.orig_shape[0]],
            "fdi": boxes_from(rf),
            "seg": polys_from(rs),
        }
        print(f"  {view:11s}: {len(result['angles'][view]['fdi']):2d} teeth, "
              f"seg {dict(Counter(d['cls'] for d in result['angles'][view]['seg']))}")

    # ---- FDI panoramic (CLAHE-preprocessed to match training) ----
    if ctx.panoramic and Path(ctx.panoramic).exists():
        m_pan = YOLO(str(TOOLS / "FDI Panoramic" / "model.pt"))
        pano = clahe_panoramic(ctx.panoramic)
        cv2.imwrite(str(ctx.out / "panoramic_clahe.png"), pano)  # for the overlay renderer
        r = m_pan.predict(pano, imgsz=640, conf=0.25, verbose=False)[0]
        result["fdi_panoramic"] = {"image_wh": [r.orig_shape[1], r.orig_shape[0]],
                                   "dets": boxes_from(r)}
        print(f"  panoramic  : {len(result['fdi_panoramic']['dets'])} teeth numbered")

    with open(ctx.out / "yolo_raw.json", "w") as f:
        json.dump(result, f, indent=2)
    print("wrote", ctx.out / "yolo_raw.json")


if __name__ == "__main__":
    # backward-compatible: run the original single-view patient
    run(default_datasets()[0])
