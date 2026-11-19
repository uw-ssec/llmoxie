---
type: Decision
title: "The console's knowledge graph is laid out in the browser with d3-force on a canvas"
description: "graph.py sends concepts and links only; knowledge-graph.tsx runs d3-force on a canvas with hover, select panel, Shift+select intersection, drag, Ctrl/⌘+scroll zoom and type toggles, after uwssec.org/projects?view=graph, with no inline styles."
tags: [console, frontend, knowledge, graph, performance]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-19T00:55:59Z" }
status: stable
governance: constraint
code_refs:
  - "services/console/frontend/src/components/knowledge-graph.tsx"
  - "services/console/console_app/web/graph.py"
  - "services/console/frontend/src/pages/knowledge.tsx"
sources:
  - resource: "https://uwssec.org/projects?view=graph"
  - resource: "https://github.com/uw-ssec/uw-ssec.github.io/blob/main/src/components/KnowledgeGraph.tsx"
---

**Status:** implemented on branch `knowledge-hub-on-azure`, 2026-11-18.

On 2026-11-18 the owner asked for the console's knowledge graph (the Knowledge page, `services/console`) to work like the graph view on uwssec.org/projects (source: `uw-ssec/uw-ssec.github.io`, `src/components/KnowledgeGraph.tsx`), because the old one loaded slowly and was too crowded to read.

## Decision

The browser lays the graph out, with `d3-force` on a canvas (`frontend/src/components/knowledge-graph.tsx`). `console_app/web/graph.py` only picks which concepts to show (the 150 most linked, always including the open one) and sends nodes `{id, title, type, colour, links}`, edges `{source, target, note}`, `hidden` and `legend`. No positions.

Why it was slow: `graph.py` used to run a pure-Python spring layout on every request, including each concept click. Measured on 180 synthetic concepts: about 290 ms per request before, 0.1 ms after. The simulation is ticked to rest before the first draw (300 ticks, 100 when re-laying out after a type toggle), so the first picture is the settled one; it only animates while a dot is dragged.

Interactions, as on uwssec.org: hover lights a dot and its links; select opens a side panel (links in and out with notes, and "Read this concept", which changes `?concept=`); Shift + select shows what all selected dots link to; drag a dot or the background; zoom buttons and fit; type toggles in the key; Escape clears. Names show only for the 12 most linked until zoomed past 1.6x, and a name that would overlap one already drawn is skipped.

## Where it differs from uwssec.org, deliberately

- The console's colours, not the dark purple canvas.
- Zoom on Ctrl/⌘ + scroll (and trackpad pinch), not plain scroll: the graph sits mid-page, and plain-scroll zoom traps anyone scrolling past it.
- No pull towards a spot per type and no type labels: tried, the types did not visibly group in an interlinked bundle and the labels were clutter.
- No inline styles anywhere (see the related front-end decision); uwssec.org uses `style={...}` throughout.

## What must stay true

- Nothing in the graph sets a `style` attribute: canvas size goes on the `width`/`height` attributes, the cursor is toggled with classes. `knowledge.test.tsx` checks the frame has no `[style]`.
- Canvas colours are read at draw time from the `--kg-*` custom properties on `.knowledge-graph` in `index.css`; change colours there, not in the component.
- A wheel listener that calls `preventDefault` must be added natively with `{ passive: false }`; React's `onWheel` is passive.
- The canvas is not keyboard reachable; the Concepts table on the same page is the keyboard path, so the graph must never be the only way to reach a concept.

## Traps

- jsdom has no layout and no canvas: `draw` returns before `getContext` when the canvas has no width, and the tests drive the graph through its panel (open a concept from the address, then its panel's buttons), not by clicking the canvas.
- The page component stays mounted across `?concept=` changes and the loader returns a new `graph` object each time; the layout is rebuilt only when the set of shown ids and edges changes (a JSON key), so dots keep their places.
- `window.matchMedia` is missing in jsdom; the "slide the selected dot out from under the panel" effect guards it.

## How it was checked

`pixi run ui-check` (77 tests) and the root `verify` gate. The built app was walked in headless Chromium against a stand-in server sending the real CSP header, 180 synthetic concepts, desktop and phone widths: no policy violations or console errors. That harness is not in the repository. The end-to-end `tests/test_knowledge.py` was updated to the new shape but not run (needs the full Docker stack).

# Related Concepts
- [The console's pages are a React application served by console-web, under a policy that allows nothing inline](console-react-front-end.md): Drawn on a canvas because the front end's policy allows no inline styles
