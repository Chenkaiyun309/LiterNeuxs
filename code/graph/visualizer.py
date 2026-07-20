#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations


def build_psp_caption(dataset: str, paper_count: int) -> str:
    topic = dataset.rsplit("/", 1)[-1].replace(".csv", "").replace("_", " ")
    return (
        f"Figure X. Material-Process-Structure-Property knowledge graph of {topic}, "
        f"constructed from {paper_count} literature records. Directed weighted edges "
        "illustrate inferred relationships among materials, processing routes, "
        "microstructure or mechanisms, and resulting properties."
    )


def build_psp_paths(edges: list[dict], limit: int = 8, node_types: dict[str, str] | None = None) -> list[str]:
    return [
        " → ".join(path["nodes"])
        for path in build_psp_path_details(edges, limit=limit, node_types=node_types)
    ]


def build_psp_path_details(
    edges: list[dict],
    limit: int = 8,
    node_types: dict[str, str] | None = None,
) -> list[dict]:
    outgoing: dict[str, list[dict]] = {}
    for edge in edges:
        outgoing.setdefault(edge["source"], []).append(edge)
    for node_edges in outgoing.values():
        node_edges.sort(key=lambda item: float(item.get("weight", 0)), reverse=True)

    paths: list[dict] = []
    seen: set[tuple[str, ...]] = set()

    # Prefer complete Material -> Process -> Structure -> Property chains.
    if node_types:
        for first_edges in outgoing.values():
            for first in first_edges:
                if node_types.get(first["source"]) != "MATERIAL" or node_types.get(first["target"]) != "PROCESS":
                    continue
                for second in outgoing.get(first["target"], [])[:5]:
                    if node_types.get(second["target"]) != "STRUCTURE":
                        continue
                    for third in outgoing.get(second["target"], [])[:5]:
                        if node_types.get(third["target"]) != "PROPERTY":
                            continue
                        nodes = [first["source"], first["target"], second["target"], third["target"]]
                        key = tuple(nodes)
                        if key in seen:
                            continue
                        seen.add(key)
                        paths.append({
                            "nodes": nodes,
                            "relations": [
                                first.get("relation", "processed_by"),
                                second.get("relation", "affects"),
                                third.get("relation", "affects"),
                            ],
                            "weight": round(sum(float(edge.get("weight", 0)) for edge in (first, second, third)) / 3, 4),
                            "frequency": sum(int(edge.get("frequency", 0)) for edge in (first, second, third)),
                        })
                        if len(paths) >= limit:
                            return paths

    for first_edges in outgoing.values():
        for first in first_edges:
            for second in outgoing.get(first["target"], [])[:3]:
                nodes = [first["source"], first["target"], second["target"]]
                key = tuple(nodes)
                if key not in seen:
                    seen.add(key)
                    paths.append({
                        "nodes": nodes,
                        "relations": [first.get("relation", "affects"), second.get("relation", "affects")],
                        "weight": round((float(first.get("weight", 0)) + float(second.get("weight", 0))) / 2, 4),
                        "frequency": int(first.get("frequency", 0)) + int(second.get("frequency", 0)),
                    })
                if len(paths) >= limit:
                    return paths
    return paths
