"""Fuse every view's model output into one per-FDI damage map -> <ctx.pub>/detections.json

Multi-angle logic
  1. Each intraoral VIEW is graded independently (grade_angle): its own FDI boxes (+ geometric
     interpolation for missed teeth) receive the caries polygons / RF-DETR boxes found in that
     view, and colours/darkness are sampled from that view's own pixels.
  2. merge_angles() combines the views onto the same FDI teeth — a tooth seen from several
     angles keeps its STRONGEST evidence (max severity); the winning view supplies the carve
     lesions + sampled colours so the 3D stays coherent. Any subset of views works.
  3. The panoramic (DoubleU-Net) adds HIDDEN lesions: a tooth healthy in every intraoral view
     but flagged on the X-ray is carved internally under intact enamel. A tooth already seen
     intraorally that the film reads DEEPER is carved to the deeper grade (external).
  4. Teeth in NO uploaded view stay healthy (severity 0) unless the panoramic flags them
     (single-side rule, CLAUDE.md §4).
"""
import json
from pathlib import Path
import numpy as np
import cv2

from pipeline import Ctx, default_datasets, view_allows

ALL_FDI = [str(q * 10 + t) for q in range(1, 5) for t in range(1, 9)]


def iou(a, b):
    ax0, ay0, ax1, ay1 = a; bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    iw, ih = max(0, ix1 - ix0), max(0, iy1 - iy0)
    inter = iw * ih
    ua = (ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - inter
    return inter / ua if ua > 0 else 0.0


def contains(box, cx, cy):
    return box[0] <= cx <= box[2] and box[1] <= cy <= box[3]


def overlap_frac(inner, outer):
    """fraction of `inner` box area covered by intersection with `outer`."""
    ix0, iy0 = max(inner[0], outer[0]), max(inner[1], outer[1])
    ix1, iy1 = min(inner[2], outer[2]), min(inner[3], outer[3])
    iw, ih = max(0, ix1 - ix0), max(0, iy1 - iy0)
    ia = (inner[2] - inner[0]) * (inner[3] - inner[1])
    return (iw * ih) / ia if ia > 0 else 0.0


def assign_tooth(lesion_box, tooth_boxes):
    """Return fdi of the best-matching tooth (max overlap of lesion by tooth), or None."""
    best, best_f = None, 0.15
    cx = (lesion_box[0] + lesion_box[2]) / 2
    cy = (lesion_box[1] + lesion_box[3]) / 2
    for fdi, tb in tooth_boxes.items():
        f = overlap_frac(lesion_box, tb)
        if f > best_f:
            best, best_f = fdi, f
    if best is None:  # fallback to centre containment
        for fdi, tb in tooth_boxes.items():
            if contains(tb, cx, cy):
                return fdi
    return best


def poly_mask(shape, polys):
    m = np.zeros(shape[:2], np.uint8)
    for p in polys:
        if p and len(p) >= 3:
            cv2.fillPoly(m, [np.array(p, np.int32).reshape(-1, 1, 2)], 255)
    return m


def bgr_to_hex(bgr):
    r, g, b = (int(np.clip(round(v), 0, 255)) for v in (bgr[2], bgr[1], bgr[0]))
    return f"#{r:02x}{g:02x}{b:02x}"


def robust_grade(area_ratio, rel_dark):
    """ICDAS D1..D6 from exposure-invariant evidence (see CLAUDE.md §4)."""
    score = min(1.0, 0.50 * min(1.0, area_ratio / 0.40) + 0.60 * rel_dark)
    if rel_dark > 0.70:
        score = max(score, 0.92)
    elif rel_dark > 0.55:
        score = max(score, 0.74)
    elif rel_dark > 0.40:
        score = max(score, 0.55)
    return int(max(1, min(6, round(1 + score * 5))))


def interpolate_missing_fdi(intra_boxes, img_wh, view=None, max_extrap=1, min_det=3):
    """Predict boxes for teeth the FDI model missed, from the arch geometry (CLAUDE.md §4).

    Robust to the multi-arch views (front/side) where the FDI model mislabels teeth across
    quadrants:
      * Only teeth this VIEW should show are considered (source teeth are whitelisted, and only
        whitelisted positions are ever predicted) — the front photo never fabricates molars, a
        side never fabricates the opposite arch, etc.
      * A quadrant needs >= `min_det` detected teeth before we trust its arch enough to fill.
      * INTERNAL gaps only by default: a missing position needs a detected neighbour on BOTH
        sides (a genuine gap in the run). Extrapolation past the ends is capped at `max_extrap`
        positions AND needs two detected teeth on that side to define the slope — so a noisy
        pair can't extrapolate a whole garbage arch.
    """
    from collections import defaultdict
    W, H = img_wh
    src = {f: v for f, v in intra_boxes.items() if view_allows(view, f)}
    out = {f: {"box": v["box"], "conf": v["conf"], "predicted": False} for f, v in src.items()}

    def csz(b):
        return [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2, b[2] - b[0], b[3] - b[1]]

    byq = defaultdict(dict)
    for f, v in src.items():
        byq[int(f) // 10][int(f) % 10] = csz(v["box"])

    for q, centers in byq.items():
        det = sorted(centers)
        if len(det) < min_det:
            continue  # too few teeth to trust the arch fit -> don't fabricate
        for p in range(1, 9):
            if p in centers or not view_allows(view, q * 10 + p):
                continue
            below = [d for d in det if d < p]
            above = [d for d in det if d > p]
            if below and above:                     # genuine internal gap
                a, b = max(below), min(above)
            elif below and (p - det[-1]) <= max_extrap and len(below) >= 2:
                a, b = below[-2], below[-1]          # extrapolate up off the last two
            elif above and (det[0] - p) <= max_extrap and len(above) >= 2:
                a, b = above[0], above[1]            # extrapolate down off the first two
            else:
                continue
            t = (p - a) / (b - a)
            cx, cy, w, h = [centers[a][k] + (centers[b][k] - centers[a][k]) * t for k in range(4)]
            w, h = max(w, 12), max(h, 12)
            x0, y0 = max(0, cx - w / 2), max(0, cy - h / 2)
            x1, y1 = min(W, cx + w / 2), min(H, cy + h / 2)
            if x1 - x0 >= 6 and y1 - y0 >= 6:
                out[str(q * 10 + p)] = {"box": [x0, y0, x1, y1], "conf": 0.0, "predicted": True}
    return out


def blank_tooth(fdi):
    return {"fdi": int(fdi), "present": True, "missing": False, "severity": 0, "rf_grade": 0,
            "img_grade": 0, "grade_source": None, "caries_ratio": 0.0,
            "lesions": [], "sources": [], "fdi_predicted": False,
            "hidden": False, "pano_grade": 0, "pano_ratio": 0.0,
            "decay_color": None, "enamel_color": None,
            "rel_dark": 0.0, "lesion_lum": 0.0, "notes": ""}


def grade_angle(img_path, fdi_dets, seg_dets, rf_dets, img_wh, view=None):
    """Grade ONE view. Returns {fdi: evidence} for teeth with caries/RF-DETR evidence, plus
    the set of FDI codes truly detected (not interpolated) in this view. Evidence carries the
    lesions (UV in this view's tooth box), sampled colours and darkness for the 3D.

    Only teeth this view is anatomically supposed to show (view_allows) can receive evidence,
    so cross-quadrant FDI mislabelling on the front/side photos can't invent lesions."""
    from collections import defaultdict
    img = cv2.imread(img_path)
    if img is None:
        return {}, set()
    H, W = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # best FDI box per code + interpolate the ones the model missed
    intra_boxes = {}
    for d in fdi_dets:
        if d["cls"] not in intra_boxes or d["conf"] > intra_boxes[d["cls"]]["conf"]:
            intra_boxes[d["cls"]] = {"box": d["xyxy"], "conf": d["conf"]}
    detected = {f for f in intra_boxes if view_allows(view, f)}
    # view-aware interpolation already returns only teeth this view should show
    full_fdi = interpolate_missing_fdi(intra_boxes, img_wh, view=view)
    intra_tb = {k: v["box"] for k, v in full_fdi.items()}

    # group Tooth + caries polygons per FDI
    tooth_seg, caries_seg = defaultdict(list), defaultdict(list)
    for d in seg_dets:
        if not d.get("polygon"):
            continue
        fdi = assign_tooth(d["xyxy"], intra_tb)
        if fdi is None:
            continue
        (tooth_seg if d["cls"] == "Tooth" else caries_seg)[fdi].append(d)

    # HEALTHY-ENAMEL reference from the Tooth masks (excludes gums)
    tooth_all = poly_mask(img.shape, [d["polygon"] for ps in tooth_seg.values() for d in ps])
    tpx = gray[tooth_all > 0]
    if tpx.size > 100:
        enamel_ref = float(np.percentile(tpx, 80))
        bright = (tooth_all > 0) & (gray >= enamel_ref)
        enamel_ref_bgr = img[bright].reshape(-1, 3).mean(axis=0) if bright.any() else np.array([205, 215, 225])
    else:
        enamel_ref, enamel_ref_bgr = 190.0, np.array([205, 215, 225])

    def rel_darkness(lum):
        return float(np.clip((enamel_ref - lum) / max(enamel_ref, 1.0), 0.0, 1.0))

    ev = {}
    for fdi, cpolys in caries_seg.items():
        tb = intra_tb[fdi]
        if tooth_seg[fdi]:
            tooth_mask = poly_mask(img.shape, [d["polygon"] for d in tooth_seg[fdi]])
        else:
            tooth_mask = np.zeros((H, W), np.uint8)
            cv2.rectangle(tooth_mask, (int(tb[0]), int(tb[1])), (int(tb[2]), int(tb[3])), 255, -1)
        caries_mask = poly_mask(img.shape, [d["polygon"] for d in cpolys])
        caries_in = (caries_mask > 0) & (tooth_mask > 0)
        enamel_in = (tooth_mask > 0) & ~(caries_mask > 0)
        tooth_px = max(1, int((tooth_mask > 0).sum()))
        area_ratio = float(caries_in.sum()) / tooth_px
        if not caries_in.any():
            continue
        lesion_lum = float(np.median(gray[caries_in]))
        rel_dark = rel_darkness(lesion_lum)
        g = robust_grade(area_ratio, rel_dark)

        decay_bgr = img[caries_in].reshape(-1, 3).mean(axis=0) * 0.82
        if enamel_in.sum() > 60 and float(np.median(gray[enamel_in])) > 0.5 * enamel_ref:
            enamel_bgr = img[enamel_in].reshape(-1, 3).mean(axis=0)
        else:
            enamel_bgr = enamel_ref_bgr

        bw, bh = tb[2] - tb[0], tb[3] - tb[1]
        lesions = []
        for d in cpolys:
            m = (poly_mask(img.shape, [d["polygon"]]) > 0) & (tooth_mask > 0)
            if not m.any():
                continue
            ys, xs = np.where(m)
            cx, cy = xs.mean(), ys.mean()
            r = float(np.clip((m.sum() / tooth_px) ** 0.5, 0.05, 1.0))
            l_lum = float(np.median(gray[m]))
            lesions.append({
                "u": round(float(np.clip((cx - tb[0]) / (bw + 1e-6), 0, 1)), 3),
                "v": round(float(np.clip((cy - tb[1]) / (bh + 1e-6), 0, 1)), 3),
                "r": round(r, 3), "type": d["cls"],
                "grade": robust_grade(m.sum() / tooth_px, rel_darkness(l_lum)),
                "lum": round(l_lum, 1), "conf": d["conf"]})
        ev[fdi] = {"img_grade": g, "rf_grade": 0, "caries_ratio": round(min(1.0, area_ratio), 3),
                   "decay_color": bgr_to_hex(decay_bgr), "enamel_color": bgr_to_hex(enamel_bgr),
                   "rel_dark": round(rel_dark, 2), "lesion_lum": round(lesion_lum, 1),
                   "lesions": lesions, "sources": ["seg"]}

    # RF-DETR ICDAS grade (a floor); may raise a tooth already flagged by seg, or add a new one
    for d in rf_dets:
        fdi = assign_tooth(d["xyxy"], intra_tb)
        if fdi is None:
            continue
        e = ev.setdefault(fdi, {"img_grade": 0, "rf_grade": 0, "caries_ratio": 0.0,
                                "decay_color": None, "enamel_color": None,
                                "rel_dark": 0.0, "lesion_lum": 0.0, "lesions": [], "sources": []})
        e["rf_grade"] = max(e["rf_grade"], int(d["grade"]))
        if "rfdetr" not in e["sources"]:
            e["sources"].append("rfdetr")

    for e in ev.values():
        e["severity"] = max(e["rf_grade"], e["img_grade"])
    return ev, detected


def merge_angles(angle_ev):
    """Merge per-view evidence onto ALL_FDI. A tooth keeps its strongest-severity view for the
    carve lesions/colours; grades and sources accumulate. Returns (teeth, detected, predicted)."""
    teeth = {f: blank_tooth(f) for f in ALL_FDI}
    detected = set()
    for view, (ev, det) in angle_ev.items():
        detected |= det
        for fdi, e in ev.items():
            if fdi not in teeth:
                continue
            t = teeth[fdi]
            t["rf_grade"] = max(t["rf_grade"], e.get("rf_grade", 0))
            t["img_grade"] = max(t["img_grade"], e.get("img_grade", 0))
            for s in e.get("sources", []):
                if s not in t["sources"]:
                    t["sources"].append(s)
            # the strongest view supplies the concrete carve (lesions + sampled colours)
            if e.get("severity", 0) >= t.get("_win", -1):
                t["_win"] = e.get("severity", 0)
                if e.get("lesions"):
                    t["lesions"] = e["lesions"]
                if e.get("decay_color"):
                    t["decay_color"] = e["decay_color"]; t["enamel_color"] = e["enamel_color"]
                t["caries_ratio"] = max(t["caries_ratio"], e.get("caries_ratio", 0.0))
                t["rel_dark"] = max(t["rel_dark"], e.get("rel_dark", 0.0))
                t["lesion_lum"] = e.get("lesion_lum", t["lesion_lum"])
    for f, t in teeth.items():
        t.pop("_win", None)
        t["fdi_predicted"] = (f not in detected) and (max(t["rf_grade"], t["img_grade"]) > 0)
    predicted = {f for f, t in teeth.items() if t["fdi_predicted"]}
    return teeth, detected, predicted


def flag_missing_teeth(teeth, intra_detected, pano_detected, has_panoramic):
    """Gigi ompong (missing tooth). A tooth is declared MISSING only when BOTH detectors
    agree it isn't there: it is absent from every intraoral FDI detection AND from the
    panoramic FDI chart. The panoramic is the full-mouth reference, so this call is only
    made when a panoramic was uploaded — without it we can't tell "missing" from "not in
    view" (the single-side rule keeps those teeth healthy instead).

    A tooth carrying real caries evidence (severity > 0) is never removed — detected decay
    beats an interpolated/absent FDI box. Missing teeth are dropped from the 3D model.
    Returns the sorted list of missing FDI codes."""
    if not has_panoramic:
        return []
    missing = []
    for f, t in teeth.items():
        if t["severity"] > 0:
            continue                          # has decay evidence -> the tooth is there
        if f in intra_detected or f in pano_detected:
            continue                          # at least one detector saw it -> present
        t["present"] = False
        t["missing"] = True
        t["notes"] = "gigi ompong — tidak terdeteksi pada intraoral maupun panoramik (dihilangkan dari model 3D)"
        missing.append(f)
    return sorted(missing, key=int)


def apply_panoramic(teeth, pano_caries):
    """Resolve final severity and fold in the panoramic (hidden / deeper) lesions."""
    pano_uv = {}
    if pano_caries:
        for fdi, info in pano_caries.get("teeth", {}).items():
            if fdi in teeth and info.get("caries"):
                teeth[fdi]["pano_grade"] = int(info.get("grade", 3))
                teeth[fdi]["pano_ratio"] = round(float(info.get("ratio", 0.0)), 4)
                pano_uv[fdi] = info.get("uv")

    for f, t in teeth.items():
        combined = max(t["rf_grade"], t["img_grade"])
        has_pano = t["pano_grade"] > 0
        if combined > 0:
            src = "rfdetr+seg" if (t["rf_grade"] and t["img_grade"]) else ("rfdetr" if t["rf_grade"] else "seg")
            if has_pano and "panoramic" not in t["sources"]:
                t["sources"].append("panoramic")
            if has_pano and t["pano_grade"] > combined:
                t["severity"] = t["pano_grade"]
                t["grade_source"] = src + "+panoramic"
                t["notes"] = (f"surface lesion (D{combined}) that the panoramic X-ray shows is "
                              f"deeper (D{t['pano_grade']}) — damaged outside and inside")
            else:
                t["severity"] = combined
                t["grade_source"] = src
                if has_pano:
                    t["notes"] = "also confirmed on panoramic (X-ray)"
        elif has_pano:
            t["severity"] = t["pano_grade"]
            t["grade_source"] = "panoramic"
            t["hidden"] = True
            t["caries_ratio"] = max(t["caries_ratio"], t["pano_ratio"])
            if "panoramic" not in t["sources"]:
                t["sources"].append("panoramic")
            t["notes"] = "hidden internal lesion — seen on the panoramic X-ray, not on the surface"
            uv = pano_uv.get(f) or [0.5, 0.5]
            t["lesions"] = [{"u": uv[0], "v": uv[1], "r": 0.5, "type": "Caries",
                             "grade": t["pano_grade"], "lum": 0, "conf": 0.0}]
        if t["lesions"]:
            top = max(t["lesions"], key=lambda l: l["grade"])
            top["grade"] = max(top["grade"], t["severity"])


def run(ctx: Ctx):
    yolo = json.load(open(ctx.out / "yolo_raw.json"))
    rf_path = ctx.out / "rfdetr_raw.json"
    rfdetr = json.load(open(rf_path)) if rf_path.exists() else {"angles": {}}
    pc_path = ctx.out / "panoramic_caries.json"
    pano_caries = json.load(open(pc_path)) if pc_path.exists() else None
    ts_path = ctx.out / "tooth_shapes.json"
    tooth_shapes = json.load(open(ts_path)) if ts_path.exists() else None

    angle_ev, first_wh = {}, [640, 640]
    for view, path in ctx.angles.items():
        a = yolo["angles"].get(view)
        if not a:
            continue
        first_wh = a["image_wh"]
        rf_dets = rfdetr.get("angles", {}).get(view, {}).get("dets", [])
        angle_ev[view] = grade_angle(path, a["fdi"], a["seg"], rf_dets, a["image_wh"], view=view)

    teeth, detected, predicted = merge_angles(angle_ev)
    apply_panoramic(teeth, pano_caries)

    # Gigi ompong: a tooth missing from BOTH the intraoral detections and the panoramic FDI
    # chart is absent -> removed from the 3D (CLAUDE.md §4). Needs the panoramic to be sure.
    pano_detected = {d["cls"] for d in yolo.get("fdi_panoramic", {}).get("dets", [])}
    missing = flag_missing_teeth(teeth, detected, pano_detected, bool(ctx.panoramic))

    # per-patient tooth SHAPE from the panoramic tooth-seg (root curvature + proportions).
    # The 3D viewer morphs each generic layered tooth to this before carving (app/lib/damage.js).
    if tooth_shapes:
        for fdi, sh in tooth_shapes.get("teeth", {}).items():
            if fdi in teeth:
                teeth[fdi]["shape"] = sh

    has_rf = any(rfdetr.get("angles", {}).get(v, {}).get("dets") for v in ctx.angles)
    detections = {
        "meta": {
            "patient": ctx.name,
            "views": list(ctx.angles.keys()),
            "has_panoramic": bool(ctx.panoramic),
            "severity_scale": "0 = healthy, 1-6 = ICDAS D1-D6",
            "grade_authority": "Per view: severity = max(RF-DETR ICDAS grade, segmentation "
                               "estimate). Across views the strongest evidence per FDI wins. "
                               "Decay/enamel colours sampled from the actual photo pixels.",
            "models": {
                "fdi_intraoral": "YOLO26x (+ geometric interpolation for missed teeth)",
                "fdi_panoramic": "YOLO26x (CLAHE 2.0/8x8)" if ctx.panoramic else "not run",
                "seg_intraoral": "YOLO26x-seg [Caries,Cavity,Crack,Tooth]",
                "caries_grade": "RF-DETR-2XL D1-D6 @ res 880" if has_rf else "image-estimate (RF-DETR unavailable)",
                "panoramic_caries": "DoubleU-Net" if pano_caries else "not run",
            },
            "intraoral_wh": first_wh,
            "predicted_fdi": sorted(predicted, key=int),
            "hidden_fdi": sorted((f for f, t in teeth.items() if t["hidden"]), key=int),
            "missing_fdi": missing,
            "note": "Teeth not visible in any uploaded view are taken as healthy unless the "
                    "panoramic flags a lesion. Panoramic-only lesions are 'hidden' internal "
                    "caries — the 3D keeps the enamel intact and carves inside.",
        },
        "teeth": teeth,
    }
    json.dump(detections, open(ctx.pub / "detections.json", "w"), indent=2)

    print("wrote", ctx.pub / "detections.json")
    print("views:", list(ctx.angles.keys()), "| predicted:", sorted(predicted, key=int) or "none",
          "| hidden:", sorted((f for f, t in teeth.items() if t["hidden"]), key=int) or "none",
          "| missing:", missing or "none")
    for f, t in sorted(teeth.items(), key=lambda kv: -kv[1]["severity"]):
        if t["severity"] > 0:
            tags = []
            if t["fdi_predicted"]: tags.append("FDI predicted")
            if t["hidden"]: tags.append("HIDDEN/internal")
            tag = ("  [" + ", ".join(tags) + "]") if tags else ""
            print(f"  {f}: D{t['severity']:<2} {str(t['grade_source']):<14} "
                  f"rf=D{t['rf_grade']} img=D{t['img_grade']} pano=D{t['pano_grade']} "
                  f"ratio={t['caries_ratio']:.2f}{tag}")
    return detections


if __name__ == "__main__":
    run(default_datasets()[0])
