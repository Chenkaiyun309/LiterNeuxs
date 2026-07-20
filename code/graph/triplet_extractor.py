#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from collections import defaultdict

TYPE_ORDER = {
    "MATERIAL": 0,
    "PROCESS": 1,
    "STRUCTURE": 2,
    "PROPERTY": 3,
}


def relation_for(subject: str, subject_type: str, obj: str, object_type: str) -> str:
    s = subject.lower()
    o = obj.lower()
    if subject_type == "PROCESS" and object_type == "STRUCTURE":
        if "anneal" in s:
            return "refines" if "microstructure" in o else "induces"
        if "rolling" in s:
            return "induces" if "deformation" in o or "strain" in o else "modifies"
        if "aging" in s:
            return "promotes" if "precipitation" in o else "modifies"
        if "coating" in s or "deposition" in s:
            return "forms"
        if "laser" in s or "casting" in s:
            return "controls"
        return "affects"
    if subject_type == "STRUCTURE" and object_type == "PROPERTY":
        if "microstructure" in s:
            return "controls"
        if "precipitation" in s and ("hardness" in o or "strength" in o):
            return "increases"
        if "fracture" in s:
            return "limits" if "ductility" in o else "affects"
        if "strain" in s or "deformation" in s:
            return "modulates"
        if "oxidation" in s:
            return "reduces" if "stability" in o or "corrosion" in o else "affects"
        return "affects"
    if subject_type == "MATERIAL" and object_type == "STRUCTURE":
        return "exhibits"
    if subject_type == "MATERIAL" and object_type == "PROPERTY":
        return "associated_with"
    if subject_type == "MATERIAL" and object_type == "PROCESS":
        return "processed_by"
    return "relates_to"


def extract_psp_triplets(terms: list[tuple[str, str]], paper_index: int) -> list[dict]:
    by_type: defaultdict[str, list[str]] = defaultdict(list)
    for term, node_type in terms:
        by_type[node_type].append(term)

    triplets: list[dict] = []
    templates = [
        ("MATERIAL", "PROCESS", 0.9),
        ("PROCESS", "STRUCTURE", 1.0),
        ("STRUCTURE", "PROPERTY", 1.0),
        ("MATERIAL", "STRUCTURE", 0.86),
        ("MATERIAL", "PROPERTY", 0.55),
    ]
    for source_type, target_type, confidence in templates:
        for source in by_type.get(source_type, []):
            for target in by_type.get(target_type, []):
                if source == target:
                    continue
                triplets.append({
                    "subject": source,
                    "subject_type": source_type,
                    "relation": relation_for(source, source_type, target, target_type),
                    "object": target,
                    "object_type": target_type,
                    "paper_index": int(paper_index),
                    "confidence": confidence,
                })
    return triplets
