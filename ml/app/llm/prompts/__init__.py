"""Prompt builders for the clinical agents.

`prompts.build_system()` / `prompts.build_user()` stay bound to the **diagnosis** agent for
backwards compatibility; the recommendation agent is reached through `prompts.recommendation`.
"""
from __future__ import annotations

from . import common, diagnosis, recommendation
from .common import ANAMNESA_LABELS
from .diagnosis import build_system, build_user

__all__ = [
    "ANAMNESA_LABELS",
    "build_system",
    "build_user",
    "common",
    "diagnosis",
    "recommendation",
]
