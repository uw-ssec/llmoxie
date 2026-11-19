"""What the knowledge graph shows: the concepts, the links between them, and a colour per type.

Where each concept goes is worked out in the browser (frontend/src/components/knowledge-graph.tsx),
which can move and zoom the picture; laying it out here made every page load wait for it.
"""

MAX_NODES = 150


def picture(concepts: list[dict], edges: list[dict], selected: str | None) -> dict:
    """The most linked concepts (always including the selected one), the links among them, and the legend."""
    degree = {c["id"]: 0 for c in concepts}
    for edge in edges:
        degree[edge["source"]] += 1
        degree[edge["target"]] += 1
    shown = sorted(concepts, key=lambda c: (-degree[c["id"]], c["id"]))[:MAX_NODES]
    if selected and selected in degree and all(c["id"] != selected for c in shown):
        shown[-1] = next(c for c in concepts if c["id"] == selected)
    ids = {c["id"] for c in shown}
    types = sorted({c["type"] for c in concepts})
    colour = {name: f"t{i % 6}" for i, name in enumerate(types)}
    nodes = [{"id": c["id"], "title": c["title"], "type": c["type"], "colour": colour[c["type"]], "links": degree[c["id"]]}
             for c in sorted(shown, key=lambda c: c["id"])]
    kept = [{"source": e["source"], "target": e["target"], "note": e["note"]}
            for e in edges if e["source"] in ids and e["target"] in ids]
    return {"nodes": nodes, "edges": kept, "hidden": len(concepts) - len(shown),
            "legend": [{"type": name, "colour": colour[name]} for name in types]}
