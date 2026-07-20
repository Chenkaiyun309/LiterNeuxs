#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from collections import defaultdict


def prune_edges(edges: list[dict], min_weight: float = 0.2, min_frequency: int = 2, top_k: int = 5) -> list[dict]:
    candidates = [
        edge for edge in edges
        if float(edge.get("weight", 0)) >= min_weight and int(edge.get("frequency", 0)) >= min_frequency
    ]
    by_node: defaultdict[str, list[dict]] = defaultdict(list)
    for edge in candidates:
        by_node[edge["source"]].append(edge)
        by_node[edge["target"]].append(edge)

    keep: set[tuple[str, str, str]] = set()
    for node_edges in by_node.values():
        ranked = sorted(
            node_edges,
            key=lambda edge: (float(edge.get("weight", 0)), int(edge.get("frequency", 0))),
            reverse=True,
        )
        for edge in ranked[:top_k]:
            keep.add((edge["source"], edge["target"], edge.get("relation", "")))

    return [
        edge for edge in sorted(
            candidates,
            key=lambda item: (float(item.get("weight", 0)), int(item.get("frequency", 0))),
            reverse=True,
        )
        if (edge["source"], edge["target"], edge.get("relation", "")) in keep
    ]
