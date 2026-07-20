#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import re

SPECIFIC_STRUCTURE_PATTERNS: list[tuple[str, str, str]] = [
    (r"\blamellar (?:microstructure|colonies|structure)\b", "lamellar microstructure", "microstructure"),
    (r"\bγ lamellae\b|\bgamma lamellae\b", "γ lamellae", "microstructure"),
    (r"\bα2 lamellae\b|\balpha2 lamellae\b", "α2 lamellae", "microstructure"),
    (r"\bequiaxed (?:crystals|grains)\b", "equiaxed grains", "microstructure"),
    (r"\bgrain boundar(?:y|ies)\b", "grain boundary", "microstructure"),
    (r"\bsub[- ]?grain boundar(?:y|ies)\b", "sub-grain boundary", "microstructure"),
    (r"\bdislocation walls?\b", "dislocation walls", "deformation mechanism"),
    (r"\bdislocation arrays?\b", "dislocation arrays", "deformation mechanism"),
    (r"\btwins?\b", "twins", "deformation mechanism"),
    (r"\bCr[- ]rich phases?\b|\bCr[- ]rich precipitates?\b", "Cr-rich precipitates", "precipitation"),
    (r"\bNb precipitates?\b", "Nb precipitates", "precipitation"),
    (r"\bnano[- ]scale .*?precipitates?\b|\bnano precipitates?\b", "nano precipitates", "precipitation"),
    (r"\bBCC phase\b|\bbody[- ]centered cubic phase\b", "BCC phase", "phase"),
    (r"\bFCC phase\b|\bface[- ]centered cubic phase\b", "FCC phase", "phase"),
    (r"\bHCP phase\b|\bhexagonal close[- ]packed phase\b", "HCP phase", "phase"),
    (r"\bLaves phase\b", "Laves phase", "phase"),
    (r"\bmartensit(?:e|ic phase)\b", "martensite", "phase transformation"),
    (r"\baustenit(?:e|ic phase)\b", "austenite", "phase transformation"),
    (r"\b(?:β|beta)[- ]phase\b", "β phase", "phase"),
    (r"\b(?:α|alpha)[- ]phase\b", "α phase", "phase"),
    (r"\boxide scales?\b", "oxide scale", "oxidation"),
    (r"\bcoating layers?\b", "coating layer", "microstructure"),
    (r"\bbarrier scales?\b", "barrier scale", "oxidation"),
]


def extract_specific_structures(text: str) -> list[dict]:
    source = str(text or "")
    structures: dict[str, dict] = {}
    for pattern, term, parent in SPECIFIC_STRUCTURE_PATTERNS:
        if re.search(pattern, source, flags=re.IGNORECASE):
            structures[term] = {
                "term": term,
                "category": "STRUCTURE",
                "parent_node": parent,
                "specificity": "specific",
            }
    return list(structures.values())
