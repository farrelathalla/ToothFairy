"""Shared config for the multi-angle inference pipeline.

The clinic captures up to 5 standard intraoral views + 1 panoramic:

    front · side_left · side_right · up (maxillary occlusal) · bottom (mandibular occlusal)

Each intraoral view is run through the SAME three intraoral models (FDI numbering, tooth/
caries segmentation, RF-DETR ICDAS grading); the panoramic gets the FDI-panoramic YOLO +
the DoubleU-Net caries net. `fuse.py` then merges every view's evidence onto the same FDI
teeth (a tooth seen from several angles keeps its STRONGEST evidence), so any subset of
views works — even a single one. Teeth not visible in ANY uploaded view stay healthy
unless the panoramic flags a hidden lesion (the single-side rule, CLAUDE.md §4).

A "dataset" is one patient's capture. We precompute a few known ones into
`web/public/results/<name>/` so the viewer can switch between them with no backend; the
same `Ctx` also drives live uploads through the ML service.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path

ML_DIR = Path(__file__).resolve().parents[1]     # ml/
REPO_ROOT = ML_DIR.parent                        # repository root
TOOLS = ML_DIR / "training"                      # model weights (downloaded from Hugging Face)
OUT_ROOT = Path(__file__).resolve().parent / "out"
PUB_ROOT = REPO_ROOT / "web" / "public" / "results"
SAMPLES = REPO_ROOT / "assets" / "samples"

# Kept for callers that predate the ml/ split.
ROOT = ML_DIR

# canonical intraoral view keys (order = display order)
ANGLES = ["front", "side_left", "side_right", "up", "bottom"]
ANGLE_LABEL = {
    "front": "Front", "side_left": "Side Left", "side_right": "Side Right",
    "up": "Upper (occlusal)", "bottom": "Lower (occlusal)",
}

# Which FDI teeth each standard view actually shows clearly. Multi-arch views (front/side)
# let the FDI model leak numbering across quadrants, so we only trust a view's caries
# evidence for the teeth it is anatomically supposed to depict. This stops a lower-molar
# lesion in the front photo from being pinned onto an upper premolar, etc.
#   quadrant q = fdi//10 (1 upper-right, 2 upper-left, 3 lower-left, 4 lower-right)
#   position p = fdi%10  (1 central incisor .. 8 third molar)
VIEW_FDI = {
    "up":         lambda q, p: q in (1, 2),               # maxillary occlusal -> upper arch
    "bottom":     lambda q, p: q in (3, 4),               # mandibular occlusal -> lower arch
    "front":      lambda q, p: p <= 5,                    # anteriors + premolars, both arches
    "side_left":  lambda q, p: q in (2, 3) and p >= 3,    # patient's left buccal, canine->molar
    "side_right": lambda q, p: q in (1, 4) and p >= 3,    # patient's right buccal, canine->molar
}


def view_allows(view, fdi):
    pred = VIEW_FDI.get(view)
    if pred is None:
        return True
    return pred(int(fdi) // 10, int(fdi) % 10)


@dataclass
class Ctx:
    """One patient capture + where its intermediate/public outputs go."""
    name: str
    angles: dict           # {angle_key: image path str}  (any subset of ANGLES)
    panoramic: str | None  # panoramic image path str, or None
    out: Path              # intermediate JSON dir (inference/out/<name>)
    pub: Path              # public result dir (web/public/results/<name>)
    do_xai: bool = False

    def __post_init__(self):
        self.out = Path(self.out); self.pub = Path(self.pub)
        self.out.mkdir(parents=True, exist_ok=True)
        (self.pub / "overlays").mkdir(parents=True, exist_ok=True)

    @property
    def overlays(self) -> Path:
        return self.pub / "overlays"


def angle_from_filename(fn: str) -> str | None:
    """Map a filename to a canonical intraoral view key. Panoramic returns None so the
    caller can route it separately (panoramics here are named 12x.png / *panoramic*)."""
    s = Path(fn).stem.lower().replace("-", " ").replace("_", " ")
    s = "".join(c for c in s if not c.isdigit()).strip()
    if "front" in s:
        return "front"
    if "side" in s and "left" in s or s.strip() in ("left", "sideleft"):
        return "side_left"
    if "side" in s and "right" in s or s.strip() in ("right", "sideright"):
        return "side_right"
    if s.startswith("up") or "upper" in s or "maxill" in s or "atas" in s:
        return "up"
    if "bottom" in s or "lower" in s or "mandib" in s or "bawah" in s:
        return "bottom"
    return None


def ctx_from_dir(name: str, folder: str | Path, do_xai: bool = False) -> Ctx:
    """Build a Ctx by classifying every image in a folder by filename. Any file that
    isn't a recognizable intraoral view AND looks like a panoramic (12x / panoramic) is
    used as the panoramic."""
    folder = Path(folder)
    angles, pano = {}, None
    for p in sorted(folder.iterdir()):
        if p.suffix.lower() not in (".jpg", ".jpeg", ".png", ".bmp", ".webp"):
            continue
        a = angle_from_filename(p.name)
        if a:
            angles[a] = str(p)
        elif pano is None:
            pano = str(p)   # unclassified -> treat as the panoramic (12x.png etc.)
    return Ctx(name=name, angles=angles, panoramic=pano,
               out=OUT_ROOT / name, pub=PUB_ROOT / name, do_xai=do_xai)


def default_datasets() -> list[Ctx]:
    """The precomputed demo patients shipped with the app."""
    tp = SAMPLES
    ds = []
    # original single-view patient (upper occlusal intraoral + full panoramic)
    ds.append(Ctx(name="original",
                  angles={"up": str(tp / "intraoral.jpg")},
                  panoramic=str(tp / "panoramic.png"),
                  out=OUT_ROOT / "original", pub=PUB_ROOT / "original", do_xai=True))
    # the three 5-view progression sets
    for name, sub in (("set1", "set1"), ("set2", "set2"), ("set3", "set3")):
        if (tp / sub).is_dir():
            ds.append(ctx_from_dir(name, tp / sub, do_xai=True))
    return ds
