#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from collections import defaultdict

TYPE_LAYERS = {
    "PROPERTY": {"y": 112, "label": "PROPERTY"},
    "STRUCTURE": {"y": 258, "label": "STRUCTURE"},
    "PROCESS": {"y": 404, "label": "PROCESS"},
    "MATERIAL": {"y": 548, "label": "MATERIAL"},
}


def apply_psp_layout(nodes: list[dict], edges: list[dict]) -> list[dict]:
    degree: defaultdict[str, float] = defaultdict(float)
    for edge in edges:
        weight = float(edge.get("weight", 0.2))
        degree[edge["source"]] += weight
        degree[edge["target"]] += weight

    by_type: defaultdict[str, list[dict]] = defaultdict(list)
    for node in nodes:
        by_type[node.get("category", "STRUCTURE")].append(node)

    positioned: list[dict] = []
    for node_type, layer in TYPE_LAYERS.items():
        layer_nodes = sorted(
            by_type.get(node_type, []),
            key=lambda node: (float(node.get("pagerank", 0)), int(node.get("count", 0)), node.get("id", "")),
            reverse=True,
        )
        total = len(layer_nodes)
        if not total:
            continue
        span = 820
        left = 90
        step = span / max(1, total - 1)
        for index, node in enumerate(layer_nodes):
            centrality = float(node.get("pagerank", 0))
            node["x"] = round(left + step * index)
            node["y"] = int(layer["y"])
            node["radius"] = round(12 + min(18, 72 * centrality + degree[node["id"]] * 2.2), 1)
            node["layer"] = node_type
            positioned.append(node)
    return positioned
