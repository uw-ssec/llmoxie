import {
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type Simulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from 'd3-force'
import { MinusIcon, PlusIcon, ScanIcon, XIcon } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent, type PointerEvent } from 'react'
import { Tag } from '@/components/status-badge'
import { Button } from '@/components/ui/button'
import type { KnowledgePage } from '@/lib/types'
import { cn } from '@/lib/utils'

type Graph = KnowledgePage['graph']
type Dot = Graph['nodes'][number] & SimulationNodeDatum & { r: number }
type Arrow = SimulationLinkDatum<Dot> & { note: string | null }
type World = { key: string; dots: Dot[]; arrows: Arrow[]; sim: Simulation<Dot, Arrow> | null; fitted: boolean }
type Gesture = { dot: Dot | null; x: number; y: number; camX: number; camY: number; moved: boolean }

const MIN_ZOOM = 0.2
const MAX_ZOOM = 4
const HUBS = 12 // how many of the most linked concepts keep their name on when zoomed out
const LABELS_AT = 1.6 // the zoom from which every concept shows its name
const PANEL_WIDTH = 320 // md:w-80

const radius = (links: number) => 5 + Math.sqrt(links) * 2
const end = (arrow: Arrow) => [arrow.source as Dot, arrow.target as Dot] as const
const short = (title: string) => (title.length <= 28 ? title : `${title.slice(0, 27)}…`)

/**
 * The knowledge graph: a dot per concept, an arrow per link, laid out in the browser by a force
 * simulation. Drag a dot to move it, drag the background to pan, zoom with the buttons or with
 * Ctrl/⌘ + scroll. Hovering a dot lights it and what it links to; selecting one opens a panel with its
 * links, and Shift + select adds more to show only what they all link to.
 *
 * Drawn on a canvas: the content security policy allows no inline styles, and a canvas needs none.
 * Its colours come from custom properties on `.knowledge-graph` (index.css). The canvas can't be
 * reached by keyboard; the list of concepts on the same page can.
 */
export function KnowledgeGraph({
  graph,
  label,
  selected,
  link,
}: {
  graph: Graph
  label: string
  /** The concept open on the page, if any; it starts selected. */
  selected: string | null
  /** What makes something a link to a concept. */
  link: (id: string) => { href: string; onClick: (event: MouseEvent) => void }
}) {
  const frame = useRef<HTMLDivElement>(null)
  const canvas = useRef<HTMLCanvasElement>(null)
  const world = useRef<World>({ key: '', dots: [], arrows: [], sim: null, fitted: false })
  // `moved` once someone pans or zooms; until then a resize fits the graph to the new size again.
  const camera = useRef({ x: 0, y: 0, k: 1, moved: false })
  const size = useRef({ width: 0, height: 0 })
  const hovered = useRef<string | null>(null)
  const gesture = useRef<Gesture | null>(null)

  const [hidden, setHidden] = useState<Set<string>>(new Set())
  const [selection, setSelection] = useState<string[]>(selected ? [selected] : [])
  const [panel, setPanel] = useState<string | null>(selected)
  // Opening another concept on the page selects it here.
  const [opened, setOpened] = useState(selected)
  if (opened !== selected) {
    setOpened(selected)
    setSelection(selected ? [selected] : [])
    setPanel(selected)
  }

  const visible = useMemo(() => {
    const nodes = graph.nodes.filter((node) => !hidden.has(node.type))
    const near = new Map(nodes.map((node) => [node.id, new Set<string>()]))
    const edges = graph.edges.filter((edge) => near.has(edge.source) && near.has(edge.target))
    for (const edge of edges) {
      near.get(edge.source)!.add(edge.target)
      near.get(edge.target)!.add(edge.source)
    }
    const key = JSON.stringify([nodes.map((node) => node.id), edges.map((edge) => [edge.source, edge.target])])
    return { nodes, edges, near, key }
  }, [graph, hidden])

  const chosen = selection.filter((id) => visible.near.has(id))
  const live = useRef({ chosen, near: visible.near })

  const draw = useCallback(() => {
    const element = canvas.current
    if (!element || element.clientWidth === 0) return // not laid out yet (or in jsdom, never)
    const context = element.getContext('2d')
    if (!context) return
    const ratio = window.devicePixelRatio || 1
    const [width, height] = [Math.round(element.clientWidth * ratio), Math.round(element.clientHeight * ratio)]
    if (element.width !== width || element.height !== height) [element.width, element.height] = [width, height]
    const { dots, arrows } = world.current
    const { chosen, near } = live.current
    const { x, y, k } = camera.current
    const css = getComputedStyle(element)
    const colour = (name: string) => css.getPropertyValue(`--kg-${name}`).trim()
    const font = (size: number, weight = 400) => `${weight} ${size / k}px ${css.fontFamily}`
    context.setTransform(1, 0, 0, 1, 0, 0)
    context.clearRect(0, 0, width, height)
    context.setTransform(ratio * k, 0, 0, ratio * k, ratio * x, ratio * y)

    // What is in focus: the selected dots and what they all link to, or else the hovered dot and its links.
    const anchors = chosen.length > 0 ? chosen : hovered.current ? [hovered.current] : []
    const lit = new Set(anchors)
    if (anchors.length > 0) {
      for (const id of near.get(anchors[0]) ?? []) if (anchors.every((a) => near.get(a)?.has(id))) lit.add(id)
    }
    const focused = anchors.length > 0
    const byLinks = [...dots].sort((a, b) => b.links - a.links)
    const hubs = new Set(byLinks.slice(0, HUBS).map((dot) => dot.id))

    for (const arrow of arrows) {
      const [from, to] = end(arrow)
      const on = focused && lit.has(from.id) && lit.has(to.id) && (anchors.includes(from.id) || anchors.includes(to.id))
      const dx = to.x! - from.x!
      const dy = to.y! - from.y!
      const length = Math.hypot(dx, dy) || 1
      const [ux, uy] = [dx / length, dy / length]
      const tip = [to.x! - ux * (to.r + 2 / k), to.y! - uy * (to.r + 2 / k)]
      const head = 6 / k
      context.globalAlpha = focused && !on ? 0.12 : 1
      context.strokeStyle = context.fillStyle = colour(on ? 'lit' : 'line')
      context.lineWidth = (on ? 2 : 1) / k
      context.beginPath()
      context.moveTo(from.x!, from.y!)
      context.lineTo(tip[0] - ux * head * 0.8, tip[1] - uy * head * 0.8)
      context.stroke()
      context.beginPath()
      context.moveTo(tip[0], tip[1])
      context.lineTo(tip[0] - ux * head - uy * head * 0.5, tip[1] - uy * head + ux * head * 0.5)
      context.lineTo(tip[0] - ux * head + uy * head * 0.5, tip[1] - uy * head - ux * head * 0.5)
      context.fill()
    }

    for (const dot of dots) {
      context.globalAlpha = focused && !lit.has(dot.id) ? 0.2 : 1
      const r = dot.r * (dot.id === hovered.current ? 1.4 : 1)
      context.beginPath()
      context.arc(dot.x!, dot.y!, r, 0, Math.PI * 2)
      context.fillStyle = colour(dot.colour)
      context.fill()
      context.lineWidth = (chosen.includes(dot.id) ? 3 : 1.5) / k
      context.strokeStyle = colour(chosen.includes(dot.id) ? 'lit' : 'halo')
      context.stroke()
    }

    context.globalAlpha = 1
    context.textAlign = 'center'
    context.lineJoin = 'round'
    // Names, most important first; one that would overlap a name already drawn is left out.
    const taken: number[][] = []
    const named = byLinks.filter((dot) => (focused ? lit.has(dot.id) : k >= LABELS_AT || hubs.has(dot.id)))
    for (const dot of [...named.filter((d) => anchors.includes(d.id)), ...named.filter((d) => !anchors.includes(d.id))]) {
      const text = short(dot.title)
      context.font = font(12, anchors.includes(dot.id) ? 700 : 400)
      const half = context.measureText(text).width / 2
      const at = dot.y! + dot.r + 14 / k
      const box = [dot.x! - half, at - 12 / k, dot.x! + half, at + 4 / k]
      if (taken.some((t) => box[0] < t[2] && t[0] < box[2] && box[1] < t[3] && t[1] < box[3])) continue
      taken.push(box)
      context.lineWidth = 3 / k
      context.strokeStyle = colour('halo')
      context.fillStyle = colour('text')
      context.strokeText(text, dot.x!, at)
      context.fillText(text, dot.x!, at)
    }
  }, [])

  /** Zoom and pan so every dot is in view. */
  const fit = useCallback(() => {
    const element = canvas.current
    const { dots } = world.current
    if (!element || element.clientWidth === 0 || dots.length === 0) return
    const xs = dots.flatMap((dot) => [dot.x! - dot.r, dot.x! + dot.r])
    const ys = dots.flatMap((dot) => [dot.y! - dot.r, dot.y! + dot.r + 18])
    const [left, right, top, bottom] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)]
    const pad = 32
    const width = element.clientWidth
    const height = element.clientHeight
    const k = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Math.min((width - 2 * pad) / (right - left || 1), (height - 2 * pad) / (bottom - top || 1), 2)))
    camera.current = { k, x: width / 2 - ((left + right) / 2) * k, y: height / 2 - ((top + bottom) / 2) * k, moved: false }
    world.current.fitted = true
    draw()
  }, [draw])

  /** Zoom by a factor, keeping the point under (x, y) on the canvas where it is. */
  const zoom = useCallback(
    (factor: number, x?: number, y?: number) => {
      const element = canvas.current
      if (!element) return
      const cam = camera.current
      const k = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, cam.k * factor))
      const [px, py] = [x ?? element.clientWidth / 2, y ?? element.clientHeight / 2]
      camera.current = { k, x: px - ((px - cam.x) / cam.k) * k, y: py - ((py - cam.y) / cam.k) * k, moved: true }
      draw()
    },
    [draw],
  )

  // Lay out again when the concepts or links shown change; those already placed keep their place.
  useEffect(() => {
    if (world.current.key === visible.key) return
    world.current.sim?.stop()
    const before = new Map(world.current.dots.map((dot) => [dot.id, dot]))
    const dots: Dot[] = visible.nodes.map((node) => {
      const old = before.get(node.id)
      return { ...node, r: radius(node.links), ...(old && { x: old.x, y: old.y }) }
    })
    const arrows: Arrow[] = visible.edges.map((edge) => ({ source: edge.source, target: edge.target, note: edge.note }))
    const sim = forceSimulation<Dot, Arrow>(dots)
      .force('link', forceLink<Dot, Arrow>(arrows).id((dot) => dot.id).distance(50))
      // Pushing apart only nearby dots, with a pull to the middle, keeps concepts with few links from drifting off.
      .force('charge', forceManyBody<Dot>().strength(-140).distanceMax(250))
      .force('x', forceX<Dot>(0).strength(0.08))
      .force('y', forceY<Dot>(0).strength(0.08))
      .force('collide', forceCollide<Dot>((dot) => dot.r + 4))
      .stop()
    // Settled before it is shown: the first picture is the finished one.
    sim.tick(before.size > 0 ? 100 : 300)
    sim.on('tick', draw)
    world.current = { key: visible.key, dots, arrows, sim, fitted: world.current.fitted }
    if (world.current.fitted) draw()
    else fit()
  }, [visible, draw, fit])

  useEffect(() => () => void world.current.sim?.stop(), [])

  // On a wide screen the panel covers the right of the graph; move the dot it is about out from under it.
  useEffect(() => {
    const element = canvas.current
    const dot = world.current.dots.find((d) => d.id === panel)
    if (!element || element.clientWidth === 0 || !dot || !window.matchMedia?.('(min-width: 48rem)').matches) return
    const room = element.clientWidth - PANEL_WIDTH
    const at = dot.x! * camera.current.k + camera.current.x
    if (at < room - 40) return
    camera.current.x += room / 2 - at
    draw()
  }, [panel, draw])

  useEffect(() => {
    live.current = { chosen, near: visible.near }
    draw()
  })

  useEffect(() => {
    const element = frame.current
    if (!element) return
    const observer = new ResizeObserver(() => {
      const element = canvas.current
      if (!element) return
      const was = size.current
      size.current = { width: element.clientWidth, height: element.clientHeight }
      if (!world.current.fitted || !camera.current.moved) return fit()
      // Keep what was in the middle in the middle.
      camera.current.x += (size.current.width - was.width) / 2
      camera.current.y += (size.current.height - was.height) / 2
      draw()
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [draw, fit])

  // Zoom with Ctrl/⌘ + scroll (and a trackpad's pinch, which arrives as that); a plain scroll still scrolls the page.
  useEffect(() => {
    const element = canvas.current
    if (!element) return
    const onWheel = (event: WheelEvent) => {
      if (!event.ctrlKey && !event.metaKey) return
      event.preventDefault()
      const box = element.getBoundingClientRect()
      zoom(Math.exp(-Math.max(-50, Math.min(50, event.deltaY)) * 0.006), event.clientX - box.left, event.clientY - box.top)
    }
    element.addEventListener('wheel', onWheel, { passive: false })
    return () => element.removeEventListener('wheel', onWheel)
  }, [zoom])

  useEffect(() => {
    if (selection.length === 0) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      setSelection([])
      setPanel(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selection.length])

  const at = (event: PointerEvent<HTMLCanvasElement>) => {
    const box = event.currentTarget.getBoundingClientRect()
    const [sx, sy] = [event.clientX - box.left, event.clientY - box.top]
    const { x, y, k } = camera.current
    return { sx, sy, wx: (sx - x) / k, wy: (sy - y) / k }
  }

  const dotAt = (wx: number, wy: number): Dot | null => {
    const k = camera.current.k
    let best: Dot | null = null
    let distance = Infinity
    for (const dot of world.current.dots) {
      const d = Math.hypot(dot.x! - wx, dot.y! - wy)
      if (d < Math.max(dot.r, 8 / k) + 4 / k && d < distance) [best, distance] = [dot, d]
    }
    return best
  }

  const choose = (id: string, add: boolean) => {
    setSelection((now) => (!add ? [id] : now.includes(id) ? now.filter((other) => other !== id) : [...now, id]))
    setPanel(id)
  }

  const onPointerDown = (event: PointerEvent<HTMLCanvasElement>) => {
    if (event.button !== 0) return
    event.currentTarget.setPointerCapture?.(event.pointerId)
    const { sx, sy, wx, wy } = at(event)
    gesture.current = { dot: dotAt(wx, wy), x: sx, y: sy, camX: camera.current.x, camY: camera.current.y, moved: false }
  }

  const onPointerMove = (event: PointerEvent<HTMLCanvasElement>) => {
    const { sx, sy, wx, wy } = at(event)
    const now = gesture.current
    const element = event.currentTarget
    if (now) {
      if (!now.moved && Math.hypot(sx - now.x, sy - now.y) < 3) return
      now.moved = true
      element.classList.add('cursor-grabbing')
      if (now.dot) {
        ;[now.dot.fx, now.dot.fy] = [wx, wy]
        world.current.sim?.alphaTarget(0.3).restart()
      } else {
        camera.current = { ...camera.current, x: now.camX + sx - now.x, y: now.camY + sy - now.y, moved: true }
        draw()
      }
      return
    }
    const dot = dotAt(wx, wy)
    element.classList.toggle('cursor-pointer', dot !== null)
    if ((dot?.id ?? null) !== hovered.current) {
      hovered.current = dot?.id ?? null
      draw()
    }
  }

  const onPointerUp = (event: PointerEvent<HTMLCanvasElement>) => {
    const now = gesture.current
    gesture.current = null
    event.currentTarget.classList.remove('cursor-grabbing')
    if (!now) return
    if (now.dot) {
      ;[now.dot.fx, now.dot.fy] = [null, null]
      world.current.sim?.alphaTarget(0)
    }
    if (now.moved) return
    if (now.dot) choose(now.dot.id, event.shiftKey)
    else {
      setSelection([])
      setPanel(null)
    }
  }

  const onPointerLeave = () => {
    if (hovered.current === null) return
    hovered.current = null
    draw()
  }

  const toggle = (type: string) =>
    setHidden((now) => {
      const next = new Set(now)
      if (!next.delete(type)) next.add(type)
      return next
    })

  const byId = new Map(visible.nodes.map((node) => [node.id, node]))
  const shown = panel ? byId.get(panel) : undefined

  return (
    <>
      <div ref={frame} className="knowledge-graph relative overflow-hidden rounded-lg border bg-card">
        <canvas
          ref={canvas}
          role="img"
          aria-label={label}
          className="block h-[min(34rem,70vh)] w-full cursor-grab touch-none"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
          onPointerLeave={onPointerLeave}
        >
          Every concept in this graph is also in the list of concepts on this page.
        </canvas>
        <div className="absolute top-3 left-3 flex flex-col gap-1">
          <Button variant="secondary" size="icon-sm" aria-label="Zoom in" onClick={() => zoom(1.3)}>
            <PlusIcon />
          </Button>
          <Button variant="secondary" size="icon-sm" aria-label="Zoom out" onClick={() => zoom(1 / 1.3)}>
            <MinusIcon />
          </Button>
          <Button variant="secondary" size="icon-sm" aria-label="Fit the graph in view" onClick={fit}>
            <ScanIcon />
          </Button>
        </div>
        {shown && (
          <aside
            aria-label={`About ${shown.title}`}
            className="flex flex-col gap-3 border-t bg-card p-4 text-sm md:absolute md:inset-y-0 md:right-0 md:w-80 md:overflow-y-auto md:border-t-0 md:border-l"
          >
            <div className="flex items-start justify-between gap-2">
              <h3 className="font-heading text-base font-bold">{shown.title}</h3>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Close"
                onClick={() => {
                  setSelection([])
                  setPanel(null)
                }}
              >
                <XIcon />
              </Button>
            </div>
            <p className="flex flex-wrap items-center gap-2 text-muted-foreground">
              <Tag>{shown.type}</Tag> {shown.links} {shown.links === 1 ? 'link' : 'links'}
            </p>
            <a {...link(shown.id)}>Read this concept</a>
            {chosen.length > 1 ? (
              <Neighbours
                title={`Linked to all ${chosen.length} selected`}
                items={[...visible.near.get(chosen[0])!].filter((id) => chosen.every((c) => visible.near.get(c)!.has(id))).map((id) => ({ id, note: null }))}
                byId={byId}
                choose={choose}
              />
            ) : (
              <>
                <Neighbours
                  title="Links to"
                  items={visible.edges.filter((e) => e.source === shown.id).map((e) => ({ id: e.target, note: e.note }))}
                  byId={byId}
                  choose={choose}
                />
                <Neighbours
                  title="Linked from"
                  items={visible.edges.filter((e) => e.target === shown.id).map((e) => ({ id: e.source, note: e.note }))}
                  byId={byId}
                  choose={choose}
                />
                <p className="text-xs text-muted-foreground">Shift + select another dot to see what both link to.</p>
              </>
            )}
          </aside>
        )}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground">
        {graph.legend.map((item) => (
          <button
            key={item.type}
            type="button"
            aria-pressed={!hidden.has(item.type)}
            title={hidden.has(item.type) ? `Show ${item.type}` : `Hide ${item.type}`}
            onClick={() => toggle(item.type)}
            className={cn('inline-flex cursor-pointer items-center gap-1.5 hover:text-foreground', hidden.has(item.type) && 'line-through opacity-50')}
          >
            <svg className="knowledge-graph-key" width="12" height="12" aria-hidden="true">
              <circle className={item.colour} cx="6" cy="6" r="5" />
            </svg>
            {item.type}
          </button>
        ))}
      </div>
    </>
  )
}

function Neighbours({
  title,
  items,
  byId,
  choose,
}: {
  title: string
  items: { id: string; note: string | null }[]
  byId: Map<string, Graph['nodes'][number]>
  choose: (id: string, add: boolean) => void
}) {
  return (
    <div className="flex flex-col gap-1">
      <h4 className="font-ui text-xs font-semibold tracking-widest text-muted-foreground uppercase">{title}</h4>
      {items.length === 0 ? (
        <span className="text-muted-foreground">nothing</span>
      ) : (
        <ul className="flex flex-col gap-1">
          {items.map((item) => (
            <li key={item.id}>
              <button type="button" className="cursor-pointer text-left text-primary hover:underline" onClick={(e) => choose(item.id, e.shiftKey)}>
                {byId.get(item.id)?.title ?? item.id}
              </button>
              {item.note && <span className="text-muted-foreground"> ({item.note})</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
