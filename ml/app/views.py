"""Canonical capture views. Shared by the schemas and the inference adapter.

The clinic captures up to five standard intraoral views plus one panoramic radiograph.
Any subset works — the fusion step merges whatever arrived onto the same FDI teeth — but the
key names are fixed, because the pipeline uses them to decide which teeth a given photo is
anatomically allowed to provide evidence for.
"""
from __future__ import annotations

from enum import Enum


class ViewKey(str, Enum):
    front = "front"
    side_left = "side_left"
    side_right = "side_right"
    up = "up"            # maxillary occlusal (upper arch)
    bottom = "bottom"    # mandibular occlusal (lower arch)
    panoramic = "panoramic"


VIEW_KEYS: list[str] = [v.value for v in ViewKey]
INTRAORAL_VIEWS: list[str] = [v.value for v in ViewKey if v is not ViewKey.panoramic]
