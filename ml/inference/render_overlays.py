"""Render per-model detection results onto every captured view for the viewer's result
gallery. Draws from the saved raw JSON (no re-inference needed).

Outputs -> <ctx.pub>/overlays/*.jpg  +  overlays.json (manifest)
"""
import json
from pathlib import Path
import numpy as np
import cv2

from pipeline import Ctx, ANGLE_LABEL, default_datasets
from fuse import interpolate_missing_fdi

# ICDAS severity ramp (BGR), vivid for on-image legibility
GRADE_BGR = {1: (90, 210, 90), 2: (60, 200, 200), 3: (0, 165, 255),
             4: (0, 100, 255), 5: (30, 50, 235), 6: (40, 20, 190)}


def save_web(ov_dir, img, name, max_w=1800, q=92):
    h, w = img.shape[:2]
    if w > max_w:
        img = cv2.resize(img, (max_w, int(h * max_w / w)), interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(ov_dir / name), img, [cv2.IMWRITE_JPEG_QUALITY, q])


def label(img, text, x, y, color, scale=0.6, thick=2):
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thick)
    y = max(y, th + 6)
    cv2.rectangle(img, (x, y - th - 6), (x + tw + 6, y + 2), color, -1)
    cv2.putText(img, text, (x + 3, y - 3), cv2.FONT_HERSHEY_SIMPLEX, scale,
                (255, 255, 255), thick, cv2.LINE_AA)


def draw_boxes(img, dets, color=(90, 210, 90), scale=0.6, thick=2, fmt=None):
    for d in dets:
        x0, y0, x1, y1 = [int(v) for v in d["xyxy"]]
        c = color(d) if callable(color) else color
        cv2.rectangle(img, (x0, y0), (x1, y1), c, thick)
        txt = fmt(d) if fmt else d.get("cls", "")
        label(img, txt, x0, y0, c, scale, max(1, thick - 1))
    return img


def render_view(ov_dir, view, img_path, a, rf_dets, manifest):
    label_v = ANGLE_LABEL.get(view, view)

    # 1. FDI: all real model detections in green; only the robust, view-aware interpolated
    #    teeth in amber ("?"). The interpolation is whitelisted per view so the front/side
    #    photos don't fabricate teeth in quadrants they can't see.
    img = cv2.imread(img_path)
    if img is None:
        return
    best = {}
    for d in a["fdi"]:
        if d["cls"] not in best or d["conf"] > best[d["cls"]]["conf"]:
            best[d["cls"]] = {"box": d["xyxy"], "conf": d["conf"]}
    full = interpolate_missing_fdi(best, a["image_wh"], view=view)
    predicted = {f: v for f, v in full.items() if v["predicted"]}
    n_det, n_pred = len(best), len(predicted)
    for fdi, v in best.items():  # real detections
        draw_boxes(img, [{"xyxy": v["box"], "cls": fdi}], (90, 210, 90), 0.55, 2,
                   fmt=lambda d: d["cls"])
    for fdi, v in predicted.items():  # interpolated
        draw_boxes(img, [{"xyxy": v["box"], "cls": fdi + "?"}], (0, 170, 255), 0.55, 2,
                   fmt=lambda d: d["cls"])
    save_web(ov_dir, img, f"{view}_fdi.jpg")
    manifest.append({"id": f"{view}_fdi", "title": f"FDI · {label_v}",
                     "model": "YOLO26x · imgsz 640 · conf 0.08",
                     "desc": f'{n_det} teeth detected + {n_pred} interpolated (amber “?”)',
                     "src": f"overlays/{view}_fdi.jpg"})

    # 2. Tooth / caries segmentation
    img = cv2.imread(img_path); overlay = img.copy()
    from collections import Counter
    for d in a["seg"]:
        poly = np.array(d.get("polygon", []), np.int32)
        if len(poly) < 3:
            continue
        if d["cls"] == "Tooth":
            cv2.polylines(img, [poly], True, (230, 200, 90), 2, cv2.LINE_AA)
        else:
            cv2.fillPoly(overlay, [poly], (40, 40, 220))
            cv2.polylines(img, [poly], True, (40, 40, 220), 2, cv2.LINE_AA)
    img = cv2.addWeighted(overlay, 0.35, img, 0.65, 0)
    cc = Counter(d["cls"] for d in a["seg"])
    save_web(ov_dir, img, f"{view}_seg.jpg")
    manifest.append({"id": f"{view}_seg", "title": f"Segmentation · {label_v}",
                     "model": "YOLO26x-seg · imgsz 960 · conf 0.25",
                     "desc": f'{cc.get("Tooth",0)} teeth, {cc.get("Caries",0)} caries polygons',
                     "src": f"overlays/{view}_seg.jpg"})

    # 3. RF-DETR ICDAS grade
    if rf_dets:
        img = cv2.imread(img_path)
        draw_boxes(img, rf_dets, color=lambda d: GRADE_BGR.get(int(d["grade"]), (0, 0, 255)),
                   scale=0.55, thick=2, fmt=lambda d: f'{d["cls"]} {d["conf"]:.2f}')
        save_web(ov_dir, img, f"{view}_grade.jpg")
        grades = sorted({int(d["grade"]) for d in rf_dets})
        manifest.append({"id": f"{view}_grade", "title": f"Caries ICDAS · {label_v}",
                         "model": "RF-DETR-2XL · res 880 · conf 0.30",
                         "desc": f'{len(rf_dets)} lesions · grades ' + ", ".join(f"D{g}" for g in grades),
                         "src": f"overlays/{view}_grade.jpg"})


def run(ctx: Ctx):
    ov = ctx.overlays
    yolo = json.load(open(ctx.out / "yolo_raw.json"))
    rf_path = ctx.out / "rfdetr_raw.json"
    rfdetr = json.load(open(rf_path)) if rf_path.exists() else {"angles": {}}
    pc_path = ctx.out / "panoramic_caries.json"
    pano_caries = json.load(open(pc_path)) if pc_path.exists() else None
    manifest = []

    for view, path in ctx.angles.items():
        a = yolo["angles"].get(view)
        if not a:
            continue
        rf_dets = rfdetr.get("angles", {}).get(view, {}).get("dets", [])
        render_view(ov, view, path, a, rf_dets, manifest)

    # panoramic FDI (on the CLAHE image the model saw)
    if ctx.panoramic and "fdi_panoramic" in yolo:
        clahe = ctx.out / "panoramic_clahe.png"
        pano = cv2.imread(str(clahe)) if clahe.exists() else cv2.imread(ctx.panoramic)
        best = {}
        for d in yolo["fdi_panoramic"]["dets"]:
            if d["cls"] not in best or d["conf"] > best[d["cls"]]["conf"]:
                best[d["cls"]] = d
        draw_boxes(pano, list(best.values()), (90, 210, 90), 1.1, 3, fmt=lambda d: f'{d["cls"]}')
        save_web(ov, pano, "panoramic_fdi.jpg", max_w=2200)
        manifest.append({"id": "panoramic_fdi", "title": "FDI · Panoramic",
                         "model": "YOLO26x · CLAHE 2.0/8×8 · imgsz 640 · conf 0.25",
                         "desc": f'{len(best)} teeth numbered on the panoramic',
                         "src": "overlays/panoramic_fdi.jpg"})

    # panoramic caries (DoubleU-Net) — the hidden-lesion evidence
    mask_p = ctx.out / "panoramic_caries_mask.png"
    if ctx.panoramic and pano_caries and mask_p.exists():
        pano = cv2.imread(ctx.panoramic)
        mask = cv2.imread(str(mask_p), cv2.IMREAD_GRAYSCALE)
        if mask is not None and mask.ndim == 3:
            mask = mask[..., 0]
        if mask is not None and mask.shape[:2] != pano.shape[:2]:
            mask = cv2.resize(mask, (pano.shape[1], pano.shape[0]), interpolation=cv2.INTER_NEAREST)
        m2 = mask > 127
        red = np.zeros_like(pano); red[m2] = (40, 40, 220)
        pano = cv2.addWeighted(pano, 1.0, red, 0.55, 0)
        cv2.drawContours(pano, cv2.findContours(m2.astype(np.uint8),
                         cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0], -1, (60, 60, 255), 2)
        flagged = {f: t for f, t in pano_caries.get("teeth", {}).items() if t.get("caries")}
        for fdi, t in flagged.items():
            draw_boxes(pano, [{"xyxy": t["box"], "cls": f'{fdi} · D{t["grade"]}'}],
                       (0, 200, 255), 1.0, 2, fmt=lambda d: d["cls"])
        save_web(ov, pano, "panoramic_caries.jpg", max_w=2200)
        manifest.append({"id": "panoramic_caries", "title": "Panoramic Caries (hidden)",
                         "model": "DoubleU-Net · DC1000 · 384² · thr 0.5",
                         "desc": f'{len(flagged)} teeth with radiographic caries: ' +
                                 ", ".join(f"{f}·D{t['grade']}" for f, t in sorted(flagged.items())),
                         "src": "overlays/panoramic_caries.jpg"})

    # preserve any XAI cards already computed by run_xai (they don't depend on fusion),
    # so a fuse/overlay-only rebuild (refuse_all) doesn't drop the attention maps
    mpath = ov / "overlays.json"
    prior_xai = [c for c in (json.load(open(mpath)) if mpath.exists() else [])
                 if c["id"].startswith("xai_")]
    json.dump(manifest + prior_xai, open(mpath, "w"), indent=2)
    print("wrote", len(manifest), "detection +", len(prior_xai), "xai overlays ->", ov)


if __name__ == "__main__":
    run(default_datasets()[0])
