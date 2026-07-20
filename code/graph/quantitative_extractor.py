#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import re

NUMBER_PATTERN = r"\d+(?:\.\d+)?"

PROCESS_PATTERN = re.compile(
    rf"\b(?P<process>anneal(?:ed|ing)?|heat[- ]treat(?:ed|ment)?|ag(?:e|ed|ing)|"
    rf"sinter(?:ed|ing)?|solution[- ]treat(?:ed|ment)?|hot[- ]roll(?:ed|ing)?|"
    rf"cold[- ]roll(?:ed|ing)?)\b[^.;\n]{{0,80}}?"
    rf"(?P<value>{NUMBER_PATTERN})\s*(?:°|deg(?:ree)?s?\s*)?(?P<unit>[CK])\b",
    flags=re.IGNORECASE,
)

SIZE_PATTERN = re.compile(
    rf"\b(?P<kind>average grain size|grain size|grain diameter|precipitate size|particle size|"
    rf"layer thickness|coating thickness|lamellar spacing|cell spacing)\b"
    rf"[^.;\n]{{0,32}}?(?P<value>{NUMBER_PATTERN})\s*(?P<unit>nm|[µμu]m|mm)\b",
    flags=re.IGNORECASE,
)

PROPERTY_PATTERN = re.compile(
    rf"\b(?P<kind>yield strength|ultimate tensile strength|tensile strength|hardness|elongation|"
    rf"corrosion rate|creep rate|electrical conductivity|thermal conductivity)\b"
    rf"[^.;\n]{{0,40}}?(?P<value>{NUMBER_PATTERN})\s*"
    rf"(?P<unit>GPa|MPa|kPa|HV|HRC|%|MS/m|S/m|W/(?:m[· ]?K)|mm/(?:y|year)|s(?:\^-?1|⁻¹))"
    rf"(?=\s|[,.;)]|$)",
    flags=re.IGNORECASE,
)

SIZE_NAMES = {
    "average grain size": "grain size",
    "grain diameter": "grain size",
}

PROPERTY_NAMES = {
    "ultimate tensile strength": "tensile strength",
}

UNIT_NAMES = {
    "um": "µm",
    "μm": "µm",
    "µm": "µm",
    "gpa": "GPa",
    "mpa": "MPa",
    "kpa": "kPa",
    "hv": "HV",
    "hrc": "HRC",
    "ms/m": "MS/m",
    "s/m": "S/m",
    "w/mk": "W/(m·K)",
    "w/m k": "W/(m·K)",
    "w/m·k": "W/(m·K)",
    "mm/y": "mm/year",
}


def normalize_number(value: str) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value or "").strip()
    return str(int(number)) if number.is_integer() else f"{number:g}"


def normalize_unit(unit: str) -> str:
    compact = re.sub(r"\s+", " ", str(unit or "").strip())
    key = compact.lower().replace("⁻¹", "^-1")
    return UNIT_NAMES.get(key, compact)


def canonical_process(value: str) -> str:
    lowered = re.sub(r"\s+", " ", str(value or "").lower().replace("-", " ")).strip()
    if lowered.startswith("anneal"):
        return "annealing"
    if lowered.startswith("heat treat"):
        return "heat treatment"
    if lowered.startswith("ag"):
        return "aging"
    if lowered.startswith("sinter"):
        return "sintering"
    if lowered.startswith("solution treat"):
        return "solution treatment"
    if lowered.startswith("hot roll"):
        return "hot rolling"
    if lowered.startswith("cold roll"):
        return "cold rolling"
    return lowered


def extract_quantitative_terms(text: str, max_terms: int = 12) -> list[tuple[str, str]]:
    source = str(text or "")
    terms: list[tuple[str, str]] = []

    for match in PROCESS_PATTERN.finditer(source):
        process = canonical_process(match.group("process"))
        value = normalize_number(match.group("value"))
        unit = match.group("unit").upper()
        terms.append((f"{process} {value} °{unit}", "PROCESS"))

    for match in SIZE_PATTERN.finditer(source):
        kind = match.group("kind").lower()
        kind = SIZE_NAMES.get(kind, kind)
        value = normalize_number(match.group("value"))
        unit = normalize_unit(match.group("unit"))
        terms.append((f"{kind} {value} {unit}", "STRUCTURE"))

    for match in PROPERTY_PATTERN.finditer(source):
        kind = match.group("kind").lower()
        kind = PROPERTY_NAMES.get(kind, kind)
        value = normalize_number(match.group("value"))
        unit = normalize_unit(match.group("unit"))
        terms.append((f"{kind} {value} {unit}", "PROPERTY"))

    unique: list[tuple[str, str]] = []
    seen: set[str] = set()
    for term, node_type in terms:
        key = term.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append((term, node_type))
        if len(unique) >= max_terms:
            break
    return unique
