"""Run the DoubleU-Net panoramic caries segmentation and map it to FDI teeth.

    python inference/run_panoramic_seg.py

The DoubleU-Net (DC1000 recipe, best-val-Dice) is run on the **whole panoramic** exactly as
the notebook's test loop does (resize to 384x384, /255, sigmoid, threshold 0.5). The model
relies on global scale/context — on tight single-tooth crops it emits ~0 everywhere, but on
the full radiograph it localizes caries sharply — so whole-image is the faithful path. The
resulting caries mask is then assigned to FDI teeth by which FDI-panoramic box (yolo_raw.json)
each caries pixel falls in, giving a per-tooth radiolucent-area ratio.

Purpose (per the brief): flag teeth that look sound from the outside but hide a deeper lesion
on the X-ray. Output feeds fuse.py, which treats a panoramic-only lesion as a HIDDEN/internal
caries (the 3D carves the dentine/pulp under an intact enamel shell).

Outputs:
  inference/out/panoramic_caries.json        per-FDI {caries, grade, ratio, box, px}
  inference/out/panoramic_caries_heat.png    full-panoramic caries probability heatmap (XAI)
  inference/out/panoramic_caries_mask.png    full-panoramic binary caries mask (for overlay)

Skips gracefully if torch / the checkpoint is unavailable (fuse.py tolerates a missing file).
"""
import json
from pathlib import Path
import numpy as np
import cv2

from pipeline import Ctx, TOOLS, default_datasets

CKPT = TOOLS / "Caries Segmentation Panoramic" / "model.pth"

SIZE = 384              # model input, per the notebook
THR = 0.5               # sigmoid threshold, per the notebook
MIN_RATIO = 0.012      # ignore specks: need this caries-area / tooth-box-area to count
MIN_PX = 40            # ...and this many caries pixels inside the tooth box


def pano_grade(ratio):
    """Radiographic lesion size -> a severity for the hidden lesion. The panoramic model
    has NO ICDAS class, so we grade by how much of the tooth the radiolucency covers. Capped
    at D5: a plain radiograph can't confidently call frank necrosis (D6) without the clinical
    view, and hidden caries is by definition not grossly cavitated on the surface."""
    if ratio >= 0.16:
        return 5
    if ratio >= 0.08:
        return 4
    if ratio >= 0.035:
        return 3
    return 2


# --- DoubleU-Net (verbatim architecture from the model's notebook) -----------------------
def build_model():
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    from torchvision.models import vgg19

    class Conv2D(nn.Module):
        def __init__(self, in_c, out_c, kernel_size=3, padding=1, dilation=1, bias=False, act=True):
            super().__init__(); self.act = act
            self.conv = nn.Sequential(
                nn.Conv2d(in_c, out_c, kernel_size=kernel_size, padding=padding, dilation=dilation, bias=bias),
                nn.BatchNorm2d(out_c))
            self.relu = nn.ReLU(inplace=True)
        def forward(self, x):
            x = self.conv(x)
            return self.relu(x) if self.act else x

    class squeeze_excitation_block(nn.Module):
        def __init__(self, in_channels, ratio=8):
            super().__init__()
            self.avgpool = nn.AdaptiveAvgPool2d(1)
            self.fc = nn.Sequential(nn.Linear(in_channels, in_channels // ratio), nn.ReLU(inplace=True),
                                    nn.Linear(in_channels // ratio, in_channels), nn.Sigmoid())
        def forward(self, x):
            b, c, _, _ = x.size()
            y = self.avgpool(x).view(b, c)
            y = self.fc(y).view(b, c, 1, 1)
            return x * y.expand_as(x)

    class ASPP(nn.Module):
        def __init__(self, in_c, out_c):
            super().__init__()
            self.avgpool = nn.Sequential(nn.AdaptiveAvgPool2d((2, 2)), Conv2D(in_c, out_c, kernel_size=1, padding=0))
            self.c1 = Conv2D(in_c, out_c, kernel_size=1, padding=0, dilation=1)
            self.c2 = Conv2D(in_c, out_c, kernel_size=3, padding=6, dilation=6)
            self.c3 = Conv2D(in_c, out_c, kernel_size=3, padding=12, dilation=12)
            self.c4 = Conv2D(in_c, out_c, kernel_size=3, padding=18, dilation=18)
            self.c5 = Conv2D(out_c * 5, out_c, kernel_size=1, padding=0, dilation=1)
        def forward(self, x):
            x0 = self.avgpool(x); x0 = F.interpolate(x0, size=x.size()[2:], mode="bilinear", align_corners=True)
            xc = torch.cat([x0, self.c1(x), self.c2(x), self.c3(x), self.c4(x)], axis=1)
            return self.c5(xc)

    class conv_block(nn.Module):
        def __init__(self, in_c, out_c):
            super().__init__()
            self.c1 = Conv2D(in_c, out_c); self.c2 = Conv2D(out_c, out_c); self.a1 = squeeze_excitation_block(out_c)
        def forward(self, x): return self.a1(self.c2(self.c1(x)))

    class encoder1(nn.Module):
        def __init__(self):
            super().__init__()
            network = vgg19(weights=None)  # weights come from the checkpoint; no ImageNet download
            self.x1 = network.features[:4];   self.x2 = network.features[4:9]
            self.x3 = network.features[9:18]; self.x4 = network.features[18:27]
            self.x5 = network.features[27:36]
        def forward(self, x):
            x1 = self.x1(x); x2 = self.x2(x1); x3 = self.x3(x2); x4 = self.x4(x3); x5 = self.x5(x4)
            return x5, [x4, x3, x2, x1]

    class decoder1(nn.Module):
        def __init__(self):
            super().__init__()
            self.up = nn.Upsample(scale_factor=2, mode="bilinear", align_corners=True)
            self.c1 = conv_block(64 + 512, 256); self.c2 = conv_block(512, 128)
            self.c3 = conv_block(256, 64);       self.c4 = conv_block(128, 32)
        def forward(self, x, skip):
            s1, s2, s3, s4 = skip
            x = self.c1(torch.cat([self.up(x), s1], axis=1))
            x = self.c2(torch.cat([self.up(x), s2], axis=1))
            x = self.c3(torch.cat([self.up(x), s3], axis=1))
            x = self.c4(torch.cat([self.up(x), s4], axis=1))
            return x

    class encoder2(nn.Module):
        def __init__(self):
            super().__init__()
            self.pool = nn.MaxPool2d((2, 2))
            self.c1 = conv_block(3, 32); self.c2 = conv_block(32, 64)
            self.c3 = conv_block(64, 128); self.c4 = conv_block(128, 256)
        def forward(self, x):
            x1 = self.c1(x);  p1 = self.pool(x1)
            x2 = self.c2(p1); p2 = self.pool(x2)
            x3 = self.c3(p2); p3 = self.pool(x3)
            x4 = self.c4(p3); p4 = self.pool(x4)
            return p4, [x4, x3, x2, x1]

    class decoder2(nn.Module):
        def __init__(self):
            super().__init__()
            self.up = nn.Upsample(scale_factor=2, mode="bilinear", align_corners=True)
            self.c1 = conv_block(832, 256); self.c2 = conv_block(640, 128)
            self.c3 = conv_block(320, 64);  self.c4 = conv_block(160, 32)
        def forward(self, x, skip1, skip2):
            x = self.c1(torch.cat([self.up(x), skip1[0], skip2[0]], axis=1))
            x = self.c2(torch.cat([self.up(x), skip1[1], skip2[1]], axis=1))
            x = self.c3(torch.cat([self.up(x), skip1[2], skip2[2]], axis=1))
            x = self.c4(torch.cat([self.up(x), skip1[3], skip2[3]], axis=1))
            return x

    class DoubleUnet(nn.Module):
        def __init__(self):
            super().__init__()
            self.e1 = encoder1(); self.a1 = ASPP(512, 64); self.d1 = decoder1()
            self.y1 = nn.Conv2d(32, 1, kernel_size=1, padding=0); self.sigmoid = nn.Sigmoid()
            self.e2 = encoder2(); self.a2 = ASPP(256, 64); self.d2 = decoder2()
            self.y2 = nn.Conv2d(32, 1, kernel_size=1, padding=0)
        def forward(self, x):
            x0 = x
            x, skip1 = self.e1(x); x = self.a1(x); x = self.d1(x, skip1); y1 = self.y1(x)
            input_x = x0 * self.sigmoid(y1)
            x, skip2 = self.e2(input_x); x = self.a2(x); x = self.d2(x, skip1, skip2); y2 = self.y2(x)
            return y2

    return DoubleUnet


def predict_prob(model, torch, bgr):
    """DoubleU-Net forward on a BGR image -> sigmoid probability map at the input's H,W.
    Preprocessing mirrors the notebook exactly: resize 384 NEAREST, CHW, /255."""
    h, w = bgr.shape[:2]
    inp = cv2.resize(bgr, (SIZE, SIZE), interpolation=cv2.INTER_NEAREST)
    inp = np.transpose(inp, (2, 0, 1))[None].astype(np.float32) / 255.0
    with torch.no_grad():
        logits = model(torch.from_numpy(inp))
        prob = torch.sigmoid(logits)[0, 0].cpu().numpy()
    return cv2.resize(prob, (w, h), interpolation=cv2.INTER_LINEAR)


def run(ctx: Ctx):
    OUT = ctx.out
    if not ctx.panoramic or not Path(ctx.panoramic).exists():
        print("no panoramic for this patient, skipping panoramic caries seg")
        return
    try:
        import torch
    except Exception as e:
        print("torch not available, skipping panoramic seg:", e)
        return
    if not CKPT.exists():
        print("panoramic seg checkpoint missing, skipping:", CKPT)
        return

    yolo = json.load(open(OUT / "yolo_raw.json")) if (OUT / "yolo_raw.json").exists() else None
    if not yolo or "fdi_panoramic" not in yolo:
        print("yolo_raw.json (fdi_panoramic) missing — run run_yolo.py first; skipping")
        return

    pano = cv2.imread(ctx.panoramic, cv2.IMREAD_COLOR)  # 3-channel (grayscale replicated), like the notebook's imread
    H, W = pano.shape[:2]

    DoubleUnet = build_model()
    model = DoubleUnet()
    state = torch.load(CKPT, map_location="cpu")
    if isinstance(state, dict) and "model" in state and not any(k.startswith(("e1", "e2")) for k in state):
        state = state["model"]
    missing, unexpected = model.load_state_dict(state, strict=False)
    if missing:
        print(f"[warn] {len(missing)} missing keys when loading (e.g. {missing[:2]})")
    if unexpected:
        print(f"[warn] {len(unexpected)} unexpected keys (e.g. {unexpected[:2]})")
    model.eval()
    print("loaded DoubleU-Net; running whole-panoramic segmentation...")

    # whole-panoramic forward -> probability + binary caries mask (the faithful path)
    heat = predict_prob(model, torch, pano)   # full-res probability (also the XAI heatmap)
    mask = heat > THR

    # best-confidence box per FDI on the panoramic
    boxes = {}
    for d in yolo["fdi_panoramic"]["dets"]:
        if d["cls"] not in boxes or d["conf"] > boxes[d["cls"]]["conf"]:
            boxes[d["cls"]] = {"box": d["xyxy"], "conf": d["conf"]}

    # assign caries pixels to the FDI tooth whose box contains them
    teeth = {}
    for fdi, info in boxes.items():
        x0, y0, x1, y1 = [int(v) for v in info["box"]]
        sub = mask[max(0, y0):y1, max(0, x0):x1]
        if sub.size == 0:
            continue
        px = int(sub.sum())
        ratio = px / float(sub.size)
        caries = ratio >= MIN_RATIO and px >= MIN_PX
        # lesion centroid within the tooth box (normalized u,v) for the 3D carve site
        uv = None
        if px:
            ys, xs = np.where(sub)
            uv = [round(float(xs.mean() / max(sub.shape[1], 1)), 3),
                  round(float(ys.mean() / max(sub.shape[0], 1)), 3)]
        teeth[fdi] = {
            "caries": bool(caries),
            "grade": pano_grade(ratio) if caries else 0,
            "ratio": round(float(ratio), 4),
            "px": px,
            "uv": uv,
            "box": [round(v, 1) for v in info["box"]],
        }

    # save heatmap (XAI) + binary mask (overlay)
    heat_u8 = np.clip(heat * 255, 0, 255).astype(np.uint8)
    cv2.imwrite(str(OUT / "panoramic_caries_heat.png"), heat_u8)
    cv2.imwrite(str(OUT / "panoramic_caries_mask.png"), ((heat > THR) * 255).astype(np.uint8))

    result = {
        "meta": {
            "model": "DoubleU-Net (DC1000, best-val-Dice)",
            "input": "whole panoramic, 384x384, /255 (notebook test recipe)",
            "threshold": THR,
            "grade_note": "no ICDAS class from this model; severity = f(radiolucent area / tooth area), capped D5",
            "image_wh": [W, H],
        },
        "teeth": teeth,
    }
    json.dump(result, open(OUT / "panoramic_caries.json", "w"), indent=2)
    flagged = {f: t for f, t in teeth.items() if t["caries"]}
    print("wrote panoramic_caries.json — flagged teeth:",
          {f: f'D{t["grade"]} r={t["ratio"]:.3f}' for f, t in sorted(flagged.items())} or "none")


if __name__ == "__main__":
    run(default_datasets()[0])
