import { useEffect, useRef, type MouseEvent } from 'react'
import type { KnowledgePage } from '@/lib/types'

/**
 * The knowledge graph: a dot per concept, an arrow per link. The server works out where everything
 * goes (console_app/web/graph.py); this only draws it. Colours and states are classes, styled in
 * index.css, because the content security policy allows no inline styles.
 */
export function KnowledgeGraph({
  graph,
  label,
  link,
}: {
  graph: KnowledgePage['graph']
  label: string
  /** What makes a dot a link to its concept. */
  link: (id: string) => { href: string; onClick: (event: MouseEvent) => void }
}) {
  const frame = useRef<HTMLDivElement>(null)
  const chosen = graph.nodes.find((node) => node.selected)
  const at = chosen ? chosen.x / graph.width : null
  useEffect(() => {
    const element = frame.current
    if (element && at !== null) element.scrollLeft = at * element.scrollWidth - element.clientWidth / 2
  }, [at, chosen?.id])
  return (
    <>
      <div ref={frame} className="overflow-x-auto">
        <svg className="knowledge-graph" viewBox={`0 0 ${graph.width} ${graph.height}`} role="img" aria-label={label}>
          <defs>
            <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="9" markerHeight="9" orient="auto-start-reverse">
              <path d="M0 0 10 5 0 10z" />
            </marker>
          </defs>
          {graph.lines.map((line, index) => (
            <line key={index} className={line.selected ? 'on' : undefined} x1={line.x1} y1={line.y1} x2={line.x2} y2={line.y2} markerEnd="url(#arrow)">
              {line.note && <title>{line.note}</title>}
            </line>
          ))}
          {graph.nodes.map((node) => (
            <a key={node.id} {...link(node.id)} className={[node.selected && 'on', node.faded && 'faded'].filter(Boolean).join(' ') || undefined}>
              <title>{`${node.title} (${node.type})`}</title>
              <circle className={node.colour} cx={node.x} cy={node.y} r={8} />
              <text x={node.x} y={node.y + 22} textAnchor="middle">
                {node.label}
              </text>
            </a>
          ))}
        </svg>
      </div>
      <p className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground">
        {graph.legend.map((item) => (
          <span key={item.type} className="inline-flex items-center gap-1.5">
            <svg className="knowledge-graph-key" width="12" height="12" aria-hidden="true">
              <circle className={item.colour} cx="6" cy="6" r="5" />
            </svg>
            {item.type}
          </span>
        ))}
      </p>
    </>
  )
}
