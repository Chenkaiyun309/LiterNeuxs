#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import re
from collections.abc import Iterable

NODE_TYPES = ("MATERIAL", "PROCESS", "STRUCTURE", "PROPERTY")

NODE_TYPE_LABELS = {
    "MATERIAL": "材料",
    "PROCESS": "工艺",
    "STRUCTURE": "组织",
    "PROPERTY": "性能",
}

NODE_TYPE_COLORS = {
    "MATERIAL": "#2E6FDF",
    "PROCESS": "#F28C28",
    "STRUCTURE": "#2E9F5C",
    "PROPERTY": "#D64541",
}

NODE_PATTERNS: dict[str, list[str]] = {
    "MATERIAL": [
        r"\bNb alloy\b", r"\bTi alloy\b", r"\bTi[- ]Nb\b", r"\bNiTi\b", r"\bβ[- ]?Ti\b",
        r"\bCu[- ]Cr[- ]Nb\b", r"\bMoSi2\b", r"\bSiO2\b", r"\balloy(?:s)?\b",
        r"\bmesh(?:es)?\b", r"\bcomposite(?:s)?\b",
    ],
    "PROCESS": [
        r"\bcasting\b", r"\brolling\b", r"\bannealing\b", r"\bsintering\b", r"\bcoating(?:s)?\b",
        r"\bsurface coating\b", r"\blaser processing\b", r"\baging\b", r"\bpre[- ]oxidation\b",
        r"\bspraying\b", r"\belectrophoretic deposition\b", r"\bdeposition\b", r"\badditive manufacturing\b",
        r"\bheat treatment\b", r"\bcold rolling\b", r"\bhot corrosion\b",
    ],
    "STRUCTURE": [
        r"\bmicrostructure(?:s)?\b", r"\bmicrostructure evolution\b", r"\bprecipitation\b",
        r"\bdeformation mechanism\b", r"\bphase transformation\b", r"\bstrain\b",
        r"\bfracture\b", r"\bgrain(?:s)?\b", r"\bdislocation(?:s)?\b",
        r"\bphase\b", r"\binterface\b", r"\bcrack(?:s)?\b", r"\boxidation\b",
    ],
    "PROPERTY": [
        r"\bstrength\b", r"\btensile\b", r"\btensile strength\b", r"\byield strength\b",
        r"\bductility\b", r"\bhardness\b", r"\bcorrosion resistance\b", r"\bstability\b",
        r"\bcorrosion\b", r"\bconductivity\b", r"\belectrical conductivity\b", r"\bbiocompatibility\b",
        r"\belongation\b", r"\bplasticity\b", r"\bsoftening resistance\b",
    ],
}

CANONICAL_TERMS = {
    "aging": "aging",
    "additive manufacturing": "additive manufacturing",
    "annealing": "annealing",
    "casting": "casting",
    "coating": "coating",
    "nb alloy": "Nb alloy",
    "ti alloy": "Ti alloy",
    "ti-nb": "Ti-Nb",
    "ti nb": "Ti-Nb",
    "niti": "NiTi",
    "deposition": "deposition",
    "heat treatment": "heat treatment",
    "hot corrosion": "hot corrosion",
    "hot rolling": "hot rolling",
    "cold rolling": "cold rolling",
    "laser processing": "laser processing",
    "rolling": "rolling",
    "sintering": "sintering",
    "surface coating": "surface coating",
    "coatings": "coating",
    "composite": "composite",
    "composites": "composite",
    "alloy": "alloy",
    "crack": "crack",
    "corrosion": "corrosion",
    "cracks": "crack",
    "dislocation": "dislocation",
    "dislocations": "dislocation",
    "fracture": "fracture",
    "grain": "grain",
    "interface": "interface",
    "microstructures": "microstructure",
    "microstructure": "microstructure",
    "grains": "grain",
    "interfaces": "interface",
    "mesh": "mesh",
    "meshes": "mesh",
    "oxidation": "oxidation",
    "phase": "phase",
    "precipitation": "precipitation",
    "strain": "strain",
    "phases": "phase",
    "alloys": "alloy",
    "biocompatibility": "biocompatibility",
    "conductivity": "conductivity",
    "corrosion resistance": "corrosion resistance",
    "ductility": "ductility",
    "elongation": "elongation",
    "hardness": "hardness",
    "plasticity": "plasticity",
    "softening resistance": "softening resistance",
    "stability": "stability",
    "strength": "strength",
    "tensile": "tensile",
    "electrical conductivity": "conductivity",
    "tensile strength": "strength",
    "yield strength": "strength",
}

TYPE_PRIORITY = {
    "MATERIAL": 0,
    "PROCESS": 1,
    "STRUCTURE": 2,
    "PROPERTY": 3,
}

ALLOWED_AUTO_STRUCTURE_TERMS = {
    "microstructure", "precipitation", "deformation", "fracture", "strain", "phase",
    "interface", "grain", "dislocation", "oxidation", "crack", "texture", "nanocrystals",
}


def normalize_term(term: str) -> str:
    value = str(term or "").translate(str.maketrans({"–": "-", "—": "-", "−": "-"}))
    value = re.sub(r"\s+", " ", value.strip().strip(".,;:"))
    if not value:
        return ""
    lower = value.lower()
    return CANONICAL_TERMS.get(lower, value)


def classify_term(term: str) -> str:
    normalized = normalize_term(term)
    if not normalized:
        return "STRUCTURE"
    for node_type in NODE_TYPES:
        for pattern in NODE_PATTERNS[node_type]:
            if re.fullmatch(pattern, normalized, flags=re.IGNORECASE):
                return node_type
    for node_type in NODE_TYPES:
        for pattern in NODE_PATTERNS[node_type]:
            if re.search(pattern, normalized, flags=re.IGNORECASE):
                return node_type
    return "STRUCTURE"


def extract_typed_terms(text: str, auto_terms: Iterable[str] | None = None) -> list[tuple[str, str]]:
    found: dict[str, str] = {}
    source = str(text or "")
    for node_type in NODE_TYPES:
        for pattern in NODE_PATTERNS[node_type]:
            for match in re.finditer(pattern, source, flags=re.IGNORECASE):
                term = normalize_term(match.group(0))
                if term:
                    found[term] = node_type

    for term in auto_terms or []:
        normalized = normalize_term(term)
        if normalized and len(normalized) > 2:
            classified = classify_term(normalized)
            if classified != "STRUCTURE" or normalized.lower() in ALLOWED_AUTO_STRUCTURE_TERMS:
                found.setdefault(normalized, classified)

    return sorted(found.items(), key=lambda item: (TYPE_PRIORITY[item[1]], item[0].lower()))
