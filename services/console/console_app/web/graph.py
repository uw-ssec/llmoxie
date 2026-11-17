"""Where to draw each concept of a knowledge graph. Laid out here, so the page only has to draw it.

A spring layout: linked concepts pull together, all concepts push apart. It starts from a circle and
runs a fixed number of steps, so the same bundle always gives the same picture.
"""

import math

WIDTH, HEIGHT, MARGIN = 880, 520, 70
MAX_NODES = 150


def layout(ids: list[str], edges: list[tuple[str, str]]) -> dict[str, tuple[float, float]]:
    count = len(ids)
    if count == 0:
        return {}
    if count == 1:
        return {ids[0]: (WIDTH / 2, HEIGHT / 2)}
    spot = {node: [math.cos(2 * math.pi * i / count), math.sin(2 * math.pi * i / count)] for i, node in enumerate(ids)}
    ideal = math.sqrt(4 / count)                 # the area is the square from -1 to 1
    steps = 150
    for step in range(steps):
        move = {node: [0.0, 0.0] for node in ids}
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                dx, dy = spot[a][0] - spot[b][0], spot[a][1] - spot[b][1]
                distance = math.hypot(dx, dy) or 0.01
                push = ideal * ideal / distance
                move[a][0] += dx / distance * push
                move[a][1] += dy / distance * push
                move[b][0] -= dx / distance * push
                move[b][1] -= dy / distance * push
        for a, b in edges:
            dx, dy = spot[a][0] - spot[b][0], spot[a][1] - spot[b][1]
            distance = math.hypot(dx, dy) or 0.01
            pull = distance * distance / ideal
            move[a][0] -= dx / distance * pull
            move[a][1] -= dy / distance * pull
            move[b][0] += dx / distance * pull
            move[b][1] += dy / distance * pull
        heat = 0.1 * (1 - step / steps)
        for node in ids:
            dx, dy = move[node]
            # A pull to the middle, strong enough that a concept with no links stays beside the rest
            # instead of drifting off and squeezing them into a corner.
            dx, dy = dx - spot[node][0] * 3, dy - spot[node][1] * 3
            distance = math.hypot(dx, dy) or 0.01
            spot[node][0] += dx / distance * min(distance, heat)
            spot[node][1] += dy / distance * min(distance, heat)
    xs, ys = [p[0] for p in spot.values()], [p[1] for p in spot.values()]
    wide, high = (max(xs) - min(xs)) or 1, (max(ys) - min(ys)) or 1
    return {node: (round(MARGIN + (p[0] - min(xs)) / wide * (WIDTH - 2 * MARGIN), 1),
                   round(MARGIN + (p[1] - min(ys)) / high * (HEIGHT - 2 * MARGIN - 14), 1))
            for node, p in spot.items()}


def picture(concepts: list[dict], edges: list[dict], selected: str | None) -> dict:
    """What the page draws: nodes with a place and a colour class, and lines between them."""
    degree = {c["id"]: 0 for c in concepts}
    for edge in edges:
        degree[edge["source"]] += 1
        degree[edge["target"]] += 1
    shown = sorted(concepts, key=lambda c: (-degree[c["id"]], c["id"]))[:MAX_NODES]
    if selected and selected in degree and all(c["id"] != selected for c in shown):
        shown[-1] = next(c for c in concepts if c["id"] == selected)
    ids = sorted(c["id"] for c in shown)
    kept = [e for e in edges if e["source"] in ids and e["target"] in ids]
    places = layout(ids, [(e["source"], e["target"]) for e in kept])
    types = sorted({c["type"] for c in concepts})
    colour = {name: f"t{i % 6}" for i, name in enumerate(types)}
    near = {selected} | {e["target"] for e in kept if e["source"] == selected} | \
        {e["source"] for e in kept if e["target"] == selected}
    nodes = [{"id": c["id"], "title": c["title"], "label": c["title"] if len(c["title"]) <= 22 else c["title"][:21] + "…",
              "type": c["type"], "colour": colour[c["type"]], "x": places[c["id"]][0], "y": places[c["id"]][1],
              "selected": c["id"] == selected, "faded": bool(selected in ids and c["id"] not in near)}
             for c in sorted(shown, key=lambda c: c["id"])]
    lines = []
    for edge in kept:
        (x1, y1), (x2, y2) = places[edge["source"]], places[edge["target"]]
        length = math.hypot(x2 - x1, y2 - y1) or 1
        lines.append({"x1": x1, "y1": y1, "x2": round(x2 - (x2 - x1) / length * 11, 1),   # stop at the circle's edge
                      "y2": round(y2 - (y2 - y1) / length * 11, 1), "note": edge["note"],
                      "selected": selected in (edge["source"], edge["target"])})
    return {"width": WIDTH, "height": HEIGHT, "nodes": nodes, "lines": lines, "hidden": len(concepts) - len(shown),
            "legend": [{"type": name, "colour": colour[name]} for name in types]}
