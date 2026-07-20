#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import math
from collections import Counter


def weighted_edges_from_triplets(
    triplet_counts: Counter,
    node_counts: Counter,
    relation_counts: dict[tuple[str, str, str], Counter],
    total_documents: int,
) -> list[dict]:
    if not triplet_counts:
        return []

    max_freq = max(triplet_counts.values()) or 1
    raw_edges: list[dict] = []
    raw_scores: list[float] = []
    for (source, target), frequency in triplet_counts.items():
        source_count = max(1, node_counts.get(source, 1))
        target_count = max(1, node_counts.get(target, 1))
        pmi = math.log2((frequency * max(1, total_documents)) / (source_count * target_count))
        positive_pmi = max(0.0, pmi)
        freq_score = frequency / max_freq
        raw_score = (0.72 * positive_pmi) + (0.28 * freq_score)
        raw_scores.append(raw_score)
        relation_counter = relation_counts.get((source, target), Counter())
        relation = relation_counter.most_common(1)[0][0] if relation_counter else "affects"
        raw_edges.append({
            "source": source,
            "target": target,
            "relation": relation,
            "frequency": int(frequency),
            "pmi": round(float(pmi), 4),
            "_raw_score": raw_score,
        })

    max_score = max(raw_scores) if raw_scores else 1
    for edge in raw_edges:
        edge["weight"] = round(float(edge["_raw_score"] / max_score), 4) if max_score > 0 else 0.0
        del edge["_raw_score"]
    return raw_edges
