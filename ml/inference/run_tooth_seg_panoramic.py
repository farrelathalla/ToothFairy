"""Per-tooth SHAPE from the panoramic tooth-segmentation model (root curvature + proportions).

    python inference/run_tooth_seg_panoramic.py            # debug dump on the original patient

Model: `ml/training/Tooth Segmentation Panoramic/model.pt` — YOLO26x-seg trained SINGLE-CLASS ("tooth")
on the STS24 2D panoramic set (see its notebook). It emits ONE polygon per tooth = the real tooth
silhouette (crown + root) as seen edge-on in the panoramic, which unrolls the dental arch so the
image X axis is arc-length (mesiodistal) for EVERY tooth. That silhouette carries exactly what the
dentist asked us to reproduce in 3D:

  * the tooth's real length and mesio-distal width profile (crown vs root proportions), and
  * **lengkung akar** — the per-tooth ROOT CURVATURE: how the root's centreline deviates
    sideways from the crown down to the apex (e.g. lower premolars/molars curving distally).

The single-class model has no numbering, so each polygon is assigned an FDI code by the
FDI-panoramic YOLO boxes (best box→polygon overlap). For each FDI we then extract an
orientation-canonical, UNIT-FREE shape descriptor (see `shape_descriptor`): everything is
normalized by the tooth's own height H or by the arch median, so it maps cleanly onto ANY 3D
tooth model at runtime regardless of pixel scale. `app/lib/damage.js::applyShapeLayered` bends +
scales the generic layered tooth to match it before carving (nesting of enamel/dentine/pulp is
preserved because all three layers are morphed from ONE common frame).

Output: inference/out/<name>/tooth_shapes.json
  { "meta": {...}, "teeth": { "<fdi>": { H, Wmax, aspect, lenRel, widRel,
                                          prof:[...K], axis:[...K] } } }
`prof[k]`  = mesio-distal width / H at band k (crown→apex), smoothed.
`axis[k]`  = root centreline lateral offset (x/H) at band k (crown→apex), signed toward
             +panoramic-x ≈ patient-LEFT along the arch, smoothed (cubic through the crown).
"""
import json
from pathlib import Path
import numpy as np
import cv2

from pipeline import Ctx, TOOLS, default_datasets

SEG_MODEL = TOOLS / "Tooth Segmentation Panoramic" / "model.pt"
FDI_MODEL = TOOLS / "FDI Panoramic" / "model.pt"
IMGSZ = 960          # the seg notebook trains/infers at imgsz 960
SEG_CONF = 0.30      # recovers all 32 teeth cleanly on the demo panoramics
K = 12               # crown→apex profile samples
MAX_OFFSET = 0.34    # clamp |root centreline offset| (fraction of tooth height) — sanity bound
CLAHE_CLIP, CLAHE_GRID = 2.0, 8   # FDI-panoramic model needs CLAHE (matches run_yolo)


def _clahe(path):
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    enh = cv2.createCLAHE(clipLimit=CLAHE_CLIP, tileGridSize=(CLAHE_GRID, CLAHE_GRID)).apply(img)
    return cv2.cvtColor(enh, cv2.COLOR_GRAY2BGR)


def _bbox(p):
    p = np.asarray(p, float)
    return [p[:, 0].min(), p[:, 1].min(), p[:, 0].max(), p[:, 1].max()]


def _overlap_frac(inner, outer):
    ix0, iy0 = max(inner[0], outer[0]), max(inner[1], outer[1])
    ix1, iy1 = min(inner[2], outer[2]), min(inner[3], outer[3])
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    ia = (inner[2] - inner[0]) * (inner[3] - inner[1])
    return (iw * ih) / ia if ia > 0 else 0.0


def _fit_cubic_through_origin(s, y, w=None):
    """Least-squares y ≈ a·s + b·s² + c·s³ (no constant ⇒ y(0)=0), evaluated back on s.
    A smooth curve anchored at the crown removes cusp/apex-tip jitter and keeps the root
    curvature (which is physically smooth). Optional per-sample weights `w`."""
    s = np.asarray(s, float)
    A = np.stack([s, s * s, s * s * s], axis=1)
    if w is not None:
        wr = np.sqrt(np.clip(w, 1e-6, None))[:, None]
        coef, *_ = np.linalg.lstsq(A * wr, y * wr[:, 0], rcond=None)
    else:
        coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    return A @ coef


def _smooth(y, passes=2):
    y = np.asarray(y, float).copy()
    for _ in range(passes):
        y = np.convolve(np.pad(y, 1, mode="edge"), [0.25, 0.5, 0.25], "valid")
    return y


def shape_descriptor(fdi, poly):
    """One tooth polygon → orientation-canonical, unit-free shape descriptor (crown→apex).

    Panoramic geometry: image Y is vertical (occlusal↔apical), image X is arc-length along the
    unrolled arch (mesio-distal). Upper teeth (q1/q2) have the crown at LARGER y (toward the
    occlusal midline), lower teeth (q3/q4) at SMALLER y — so we flip the band order per arch to
    always run crown→apex."""
    p = np.asarray(poly, float)
    x, y = p[:, 0], p[:, 1]
    ymin, ymax = float(y.min()), float(y.max())
    H = max(ymax - ymin, 1.0)
    upper = (int(fdi) // 10) in (1, 2)

    edges = np.linspace(ymin, ymax, K + 1)
    cen = np.full(K, np.nan)
    wid = np.full(K, np.nan)
    for k in range(K):
        m = (y >= edges[k]) & (y <= edges[k + 1])
        if m.sum() >= 3:
            lo, hi = np.percentile(x[m], [5, 95])   # robust silhouette edges in this band
            cen[k] = 0.5 * (lo + hi)                 # centreline = midpoint of the width
            wid[k] = hi - lo
    order = np.arange(K - 1, -1, -1) if upper else np.arange(K)  # crown→apex
    cen, wid = cen[order], wid[order]

    idx = np.arange(K)
    for arr in (cen, wid):
        good = ~np.isnan(arr)
        if good.sum() >= 2:
            arr[:] = np.interp(idx, idx[good], arr[good])
        else:
            arr[:] = 0.0

    Wmax = float(np.nanmax(wid)) if np.isfinite(wid).any() else 1.0
    # width profile (fraction of H), lightly smoothed
    prof = _smooth(np.clip(wid / H, 0.0, None), passes=1)

    # root centreline offset from the crown, normalized by H, in +panoramic-x (≈ patient-left).
    # Down-weight the top ~20% (crown cusps are wide + noisy) so the fit follows the ROOT.
    off_raw = (cen - cen[0]) / H
    s = idx / (K - 1)
    w = np.where(s < 0.2, 0.35, 1.0)
    axis = _fit_cubic_through_origin(s, off_raw, w)
    axis = np.clip(axis, -MAX_OFFSET, MAX_OFFSET)
    axis[0] = 0.0  # exactly anchored at the crown

    return {
        "H": round(H, 1), "Wmax": round(Wmax, 1), "aspect": round(H / max(Wmax, 1.0), 3),
        "prof": [round(float(v), 4) for v in prof],
        "axis": [round(float(v), 4) for v in axis],
    }


def compute_shapes(pano_path, fdi_boxes, seg_model=None):
    """Run the tooth-seg model on `pano_path`, assign polygons to `fdi_boxes` and build the
    per-FDI descriptor. `fdi_boxes` = {fdi: [x0,y0,x1,y1]} from the FDI-panoramic YOLO. Returns
    {fdi: descriptor} plus per-arch relative length/width (lenRel/widRel) folded in."""
    from ultralytics import YOLO
    model = seg_model or YOLO(str(SEG_MODEL))
    res = model.predict(str(pano_path), imgsz=IMGSZ, conf=SEG_CONF, verbose=False, retina_masks=True)[0]
    polys = list(res.masks.xy) if res.masks is not None else []

    # best polygon per FDI (max overlap of polygon bbox by the tooth box)
    best = {}
    for poly in polys:
        if len(poly) < 3:
            continue
        bb = _bbox(poly)
        pick, pf = None, 0.15
        for fdi, box in fdi_boxes.items():
            f = _overlap_frac(bb, box)
            if f > pf:
                pick, pf = fdi, f
        if pick is not None and (pick not in best or pf > best[pick][1]):
            best[pick] = (poly, pf)

    teeth = {fdi: shape_descriptor(fdi, poly) for fdi, (poly, _) in best.items()}

    # per-arch relative size so the runtime morph is comparable to the generic model's own
    # relative sizes (both unit-free): lenRel = H / arch-median-H, widRel = Wmax / arch-median-W.
    for arch in ((1, 2), (3, 4)):
        codes = [f for f in teeth if int(f) // 10 in arch]
        if not codes:
            continue
        medH = float(np.median([teeth[f]["H"] for f in codes]))
        medW = float(np.median([teeth[f]["Wmax"] for f in codes]))
        for f in codes:
            teeth[f]["lenRel"] = round(teeth[f]["H"] / max(medH, 1.0), 3)
            teeth[f]["widRel"] = round(teeth[f]["Wmax"] / max(medW, 1.0), 3)
    return teeth


def _fdi_boxes_from_yolo(out_dir):
    """Best FDI-panoramic box per code from run_yolo's yolo_raw.json, if present."""
    p = Path(out_dir) / "yolo_raw.json"
    if not p.exists():
        return None
    yolo = json.load(open(p))
    fp = yolo.get("fdi_panoramic")
    if not fp:
        return None
    boxes = {}
    for d in fp["dets"]:
        if d["cls"] not in boxes or d["conf"] > boxes[d["cls"]][1]:
            boxes[d["cls"]] = (d["xyxy"], d["conf"])
    return {f: b for f, (b, _) in boxes.items()}


def _fdi_boxes_direct(pano_path):
    """Fallback: run the FDI-panoramic YOLO here (CLAHE) to get boxes when yolo_raw is absent."""
    from ultralytics import YOLO
    r = YOLO(str(FDI_MODEL)).predict(_clahe(pano_path), imgsz=640, conf=0.25, verbose=False)[0]
    boxes = {}
    names = r.names
    for b in r.boxes:
        cls = names[int(b.cls)]
        conf = float(b.conf)
        if cls not in boxes or conf > boxes[cls][1]:
            boxes[cls] = ([float(v) for v in b.xyxy[0]], conf)
    return {f: box for f, (box, _) in boxes.items()}


def run(ctx: Ctx):
    if not ctx.panoramic or not Path(ctx.panoramic).exists():
        print("no panoramic for this patient, skipping tooth-shape seg")
        return
    if not SEG_MODEL.exists():
        print("tooth-seg panoramic checkpoint missing, skipping:", SEG_MODEL)
        return
    try:
        fdi_boxes = _fdi_boxes_from_yolo(ctx.out) or _fdi_boxes_direct(ctx.panoramic)
    except Exception as e:
        print("[warn] FDI-panoramic boxes unavailable, skipping tooth-shape seg:", e)
        return
    if not fdi_boxes:
        print("no FDI-panoramic boxes, skipping tooth-shape seg")
        return

    teeth = compute_shapes(ctx.panoramic, fdi_boxes)
    result = {
        "meta": {
            "model": "YOLO26x-seg single-class tooth (STS24 2D panoramic)",
            "imgsz": IMGSZ, "conf": SEG_CONF, "K": K,
            "note": "per-FDI tooth silhouette → unit-free shape descriptor; axis[] = root "
                    "curvature (lengkung akar), prof[] = mesio-distal width/H, crown→apex.",
        },
        "teeth": teeth,
    }
    json.dump(result, open(ctx.out / "tooth_shapes.json", "w"), indent=2)
    print(f"wrote {ctx.out / 'tooth_shapes.json'} — {len(teeth)} teeth")
    for f in sorted(teeth, key=int):
        t = teeth[f]
        print(f"  {f}: aspect={t['aspect']:.2f} lenRel={t.get('lenRel','?')} "
              f"widRel={t.get('widRel','?')} apexCurve={t['axis'][-1]:+.2f}")


if __name__ == "__main__":
    run(default_datasets()[0])
