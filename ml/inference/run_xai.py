"""Explainable-AI maps for every model, per captured view -> <ctx.pub>/overlays/xai_*.jpg

For each model we render a heatmap of WHERE it attends / what drove its output, overlaid on
the model's input image, and append the cards (ids prefixed `xai_`) to the dataset's
overlays.json so the web gallery shows an "Explainable AI" section next to the raw detections.

Method per model type (dependency-free — no pytorch-grad-cam needed):
  * YOLO (FDI intraoral, FDI panoramic, seg intraoral): FEATURE-ACTIVATION CAM — forward-hook
    the layer sequence, take the per-pixel L2 energy across channels of the deepest feature
    maps (EigenCAM-style), upsample. No class gradients -> robust for the NMS-free head.
  * DoubleU-Net (panoramic caries): its own sigmoid PROBABILITY map IS the saliency.
  * RF-DETR (ICDAS): best-effort backbone conv-activation CAM; skipped cleanly if unhookable.

Models are loaded ONCE per dataset and reused across its views.
"""
import json
from pathlib import Path
import numpy as np
import cv2

from pipeline import Ctx, TOOLS, ANGLE_LABEL, default_datasets


def save_web(ov_dir, img, name, max_w=1600, q=90):
    h, w = img.shape[:2]
    if w > max_w:
        img = cv2.resize(img, (max_w, int(h * max_w / w)), interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(ov_dir / name), img, [cv2.IMWRITE_JPEG_QUALITY, q])


def heat_overlay(img_bgr, cam01, alpha=0.5):
    cam = np.clip(np.asarray(cam01, np.float32).squeeze(), 0, 1)
    cam_u8 = (cam * 255).astype(np.uint8)
    hm = cv2.applyColorMap(cam_u8, cv2.COLORMAP_JET)
    m = (cam[..., None] ** 0.6)
    return (img_bgr * (1 - alpha * m) + hm * (alpha * m)).astype(np.uint8)


def norm01(a):
    a = a.astype(np.float32)
    lo, hi = float(np.percentile(a, 1)), float(np.percentile(a, 99.5))
    if hi <= lo:
        return np.zeros_like(a)
    return np.clip((a - lo) / (hi - lo), 0, 1)


def yolo_cam(net, img_bgr, imgsz):
    """Feature-activation CAM for a preloaded Ultralytics net (m.model.eval())."""
    import torch
    seq = net.model  # nn.Sequential (backbone + neck + head)
    acts, handles = {}, []
    for i, layer in enumerate(seq):
        def mk(idx):
            def hook(mod, inp, out):
                if isinstance(out, torch.Tensor) and out.dim() == 4:
                    acts[idx] = out.detach()
            return hook
        handles.append(layer.register_forward_hook(mk(i)))
    H, W = img_bgr.shape[:2]
    im = cv2.resize(img_bgr, (imgsz, imgsz), interpolation=cv2.INTER_LINEAR)
    rgb = cv2.cvtColor(im, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    x = torch.from_numpy(np.transpose(rgb, (2, 0, 1))[None])
    with torch.no_grad():
        try:
            net(x)
        except Exception as e:
            print("  yolo forward failed:", e)
    for h in handles:
        h.remove()
    if not acts:
        return None
    items = sorted(acts.items(), key=lambda kv: kv[1].shape[-1])
    chosen = items[:3] if len(items) >= 3 else items
    cam = np.zeros((imgsz, imgsz), np.float32)
    for _, t in chosen:
        energy = t[0].pow(2).sum(0).sqrt().cpu().numpy()
        cam += cv2.resize(norm01(energy), (imgsz, imgsz), interpolation=cv2.INTER_CUBIC)
    return cv2.resize(norm01(cam), (W, H), interpolation=cv2.INTER_CUBIC)


def rfdetr_net():
    """Load RF-DETR once and return the underlying nn.Module (or None)."""
    try:
        import torch
        from rfdetr import RFDETR2XLarge
        ckpt = TOOLS / "Caries Bounding Box" / "model.pth"
        try:
            model = RFDETR2XLarge(resolution=880, num_classes=7, pretrain_weights=str(ckpt))
        except TypeError:
            model = RFDETR2XLarge(resolution=880, num_classes=7)
        obj = getattr(model, "model", None)
        if isinstance(obj, torch.nn.Module):
            net = obj
        else:
            net = getattr(obj, "model", None)
        if not isinstance(net, torch.nn.Module):
            return None
        net.eval()
        return net
    except Exception as e:
        print("  rfdetr load skipped:", e)
        return None


def rfdetr_cam(net, img_bgr, resolution=880):
    import torch
    acts, handles = [], []
    for mod in net.modules():
        if isinstance(mod, torch.nn.Conv2d):
            handles.append(mod.register_forward_hook(
                lambda m, i, o: acts.append(o.detach()) if (isinstance(o, torch.Tensor) and o.dim() == 4) else None))
    H, W = img_bgr.shape[:2]
    im = cv2.resize(img_bgr, (resolution, resolution), interpolation=cv2.INTER_LINEAR)
    rgb = cv2.cvtColor(im, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    mean = np.array([0.485, 0.456, 0.406], np.float32); std = np.array([0.229, 0.224, 0.225], np.float32)
    rgb = (rgb - mean) / std
    x = torch.from_numpy(np.transpose(rgb, (2, 0, 1))[None]).float()
    with torch.no_grad():
        try:
            net(x)
        except Exception:
            pass
    for h in handles:
        h.remove()
    feats = [a for a in acts if 8 <= a.shape[-1] <= resolution // 8]
    if not feats:
        return None
    feats = sorted(feats, key=lambda t: t.shape[-1])[:4]
    cam = np.zeros((resolution, resolution), np.float32)
    for t in feats:
        e = t[0].pow(2).sum(0).sqrt().cpu().numpy()
        cam += cv2.resize(norm01(e), (resolution, resolution), interpolation=cv2.INTER_CUBIC)
    return cv2.resize(norm01(cam), (W, H), interpolation=cv2.INTER_CUBIC)


def run(ctx: Ctx):
    from ultralytics import YOLO
    ov = ctx.overlays
    cards = []

    # load the intraoral models once
    fdi_net = YOLO(str(TOOLS / "FDI Intraoral" / "model.pt")).model.eval()
    seg_net = YOLO(str(TOOLS / "Teeth Segmentation Intraoral" / "model.pt")).model.eval()
    rf = rfdetr_net()

    for view, path in ctx.angles.items():
        img = cv2.imread(path)
        if img is None:
            continue
        vlab = ANGLE_LABEL.get(view, view)
        cam = yolo_cam(fdi_net, img, 640)
        if cam is not None:
            save_web(ov, heat_overlay(img, cam), f"xai_{view}_fdi.jpg", 1400)
            cards.append({"id": f"xai_{view}_fdi", "title": f"XAI · FDI · {vlab}",
                          "model": "YOLO26x feature-activation CAM",
                          "desc": "where the tooth detector focuses (deep feature energy)",
                          "src": f"overlays/xai_{view}_fdi.jpg"})
        cam = yolo_cam(seg_net, img, 960)
        if cam is not None:
            save_web(ov, heat_overlay(img, cam), f"xai_{view}_seg.jpg", 1400)
            cards.append({"id": f"xai_{view}_seg", "title": f"XAI · Segmentation · {vlab}",
                          "model": "YOLO26x-seg feature-activation CAM",
                          "desc": "attention of the tooth/caries segmenter",
                          "src": f"overlays/xai_{view}_seg.jpg"})
        if rf is not None:
            cam = rfdetr_cam(rf, img)
            if cam is not None:
                save_web(ov, heat_overlay(img, cam), f"xai_{view}_grade.jpg", 1400)
                cards.append({"id": f"xai_{view}_grade", "title": f"XAI · Caries ICDAS · {vlab}",
                              "model": "RF-DETR backbone-activation CAM",
                              "desc": "backbone feature energy driving the grade boxes",
                              "src": f"overlays/xai_{view}_grade.jpg"})
        print(f"  {view}: XAI done")

    # panoramic: FDI CAM on the CLAHE image the model saw
    if ctx.panoramic:
        clahe = ctx.out / "panoramic_clahe.png"
        pano_in = cv2.imread(str(clahe)) if clahe.exists() else cv2.imread(ctx.panoramic)
        if pano_in is not None:
            pan_net = YOLO(str(TOOLS / "FDI Panoramic" / "model.pt")).model.eval()
            cam = yolo_cam(pan_net, pano_in, 640)
            if cam is not None:
                save_web(ov, heat_overlay(pano_in, cam), "xai_panoramic_fdi.jpg", 2200)
                cards.append({"id": "xai_panoramic_fdi", "title": "XAI · FDI · Panoramic",
                              "model": "YOLO26x feature-activation CAM",
                              "desc": "where the panoramic tooth numberer attends",
                              "src": "overlays/xai_panoramic_fdi.jpg"})
        # DoubleU-Net: its sigmoid probability map is the saliency
        heat_p = ctx.out / "panoramic_caries_heat.png"
        if heat_p.exists():
            base = cv2.imread(ctx.panoramic)
            heat = cv2.imread(str(heat_p), cv2.IMREAD_GRAYSCALE)
            if base is not None and heat is not None:
                if heat.shape[:2] != base.shape[:2]:
                    heat = cv2.resize(heat, (base.shape[1], base.shape[0]), interpolation=cv2.INTER_LINEAR)
                save_web(ov, heat_overlay(base, heat.astype(np.float32) / 255.0, alpha=0.6),
                         "xai_panoramic_caries.jpg", 2200)
                cards.append({"id": "xai_panoramic_caries", "title": "XAI · Panoramic Caries",
                              "model": "DoubleU-Net sigmoid saliency",
                              "desc": "caries probability heatmap (pre-threshold)",
                              "src": "overlays/xai_panoramic_caries.jpg"})

    # append to the dataset's manifest (replace any prior xai_ cards, keep detection cards)
    mpath = ov / "overlays.json"
    manifest = json.load(open(mpath)) if mpath.exists() else []
    manifest = [m for m in manifest if not m["id"].startswith("xai_")] + cards
    json.dump(manifest, open(mpath, "w"), indent=2)
    print(f"appended {len(cards)} XAI cards -> {mpath}")


if __name__ == "__main__":
    for ctx in default_datasets():
        if not (ctx.out / "yolo_raw.json").exists():
            print(f"skip {ctx.name}: no cached run (run run_all first)"); continue
        print(f"\n=== XAI {ctx.name} ===")
        run(ctx)
