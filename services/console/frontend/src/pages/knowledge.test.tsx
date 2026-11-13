import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { openApp } from '@/test/open'
import { serve, signedIn } from '@/test/server'

afterEach(() => vi.unstubAllGlobals())

const lead = signedIn({ lead_orgs: [{ id: 'o1', name: 'Astro Lab', status: 'active' }] })
const CONCEPTS = [
  { id: 'facts/lab-door', title: 'Lab door code', type: 'fact', description: 'How to get in', tags: [], links: 1, written_at: '2026-11-03T10:00:00Z' },
  { id: 'decisions/badge-readers', title: 'Badge readers', type: 'decision', description: 'Doors get badge readers', tags: ['doors'], links: 1, written_at: '2026-11-04T10:00:00Z' },
]
const GRAPH = {
  width: 880, height: 520, hidden: 0,
  nodes: [
    { id: 'decisions/badge-readers', title: 'Badge readers', label: 'Badge readers', type: 'decision', colour: 't0', x: 300, y: 200, selected: false, faded: false },
    { id: 'facts/lab-door', title: 'Lab door code', label: 'Lab door code', type: 'fact', colour: 't1', x: 500, y: 300, selected: false, faded: false },
  ],
  lines: [{ x1: 300, y1: 200, x2: 490, y2: 295, note: 'replaces', selected: false }],
  legend: [{ type: 'decision', colour: 't0' }, { type: 'fact', colour: 't1' }],
}
const LIST = { org: { id: 'o1', name: 'Astro Lab' }, tools: 'knowledge_astro', edge_count: 1, concepts: CONCEPTS, concept: null, graph: GRAPH, log_html: '<h2>2026-11-04</h2><ul><li>Created a concept.</li></ul>' }
const DOOR = {
  ...LIST,
  graph: { ...GRAPH, nodes: GRAPH.nodes.map((n) => ({ ...n, selected: n.id === 'facts/lab-door' })), lines: [{ ...GRAPH.lines[0], selected: true }] },
  concept: {
    id: 'facts/lab-door', title: 'Lab door code', type: 'fact', status: 'stable', written_at: '2026-11-03', tags: ['doors'], description: 'How to get in',
    html: '<h2>Why</h2><p>The marker is <strong>DOOR-1</strong>. &lt;script&gt;alert(1)&lt;/script&gt; <a href="?concept=decisions/badge-readers#concept">Badge readers</a> <a href="https://example.org/x" rel="noopener noreferrer">site</a></p>',
    links_out: [], links_in: [{ id: 'decisions/badge-readers', title: 'Badge readers', note: 'replaces' }],
  },
}

it('lists the concepts and draws the graph, with no concept text until one is selected', async () => {
  serve({ ...lead, 'GET /web-api/orgs/o1/knowledge': { json: LIST } })
  await openApp('/orgs/o1/knowledge')
  expect(await screen.findByRole('heading', { name: 'Knowledge', level: 1 })).toBeInTheDocument()
  expect(screen.getByText('2 concepts, 1 link · read-only', { exact: false })).toBeInTheDocument()
  expect(within(screen.getByRole('main')).getByRole('link', { name: 'Astro Lab' })).toHaveAttribute('href', '/orgs/o1')
  const row = screen.getAllByRole('link', { name: 'Lab door code' }).map((a) => a.closest('tr')).find(Boolean)!
  expect(within(row).getByText('facts/lab-door')).toBeInTheDocument()
  expect(within(row).getByText('2026-11-03')).toBeInTheDocument()
  const graph = screen.getByRole('img', { name: 'Knowledge graph of Astro Lab' })
  expect(graph.querySelectorAll('circle')).toHaveLength(2)
  expect(graph.querySelectorAll('line')).toHaveLength(1)
  expect(graph.querySelector('line title')).toHaveTextContent('replaces')
  expect(graph.querySelector('[style]')).toBeNull() // drawn with classes: the policy allows no inline styles
  expect(screen.getByText('Created a concept.')).toBeInTheDocument()
  expect(screen.queryByText(/DOOR-1/)).toBeNull()
  expect(document.querySelector('#concept')).toBeNull()
})

it("renders the selected concept's HTML, with member-written markup as text", async () => {
  serve({ ...lead, 'GET /web-api/orgs/o1/knowledge?concept=facts%2Flab-door': { json: DOOR } })
  await openApp('/orgs/o1/knowledge?concept=facts/lab-door')
  const concept = (await screen.findByRole('heading', { name: /Lab door code/, level: 2 })).closest('section')!
  expect(within(concept).getByText('DOOR-1').tagName).toBe('STRONG')
  expect(within(concept).getByText(/<script>alert\(1\)<\/script>/)).toBeInTheDocument() // shown, not run
  expect(concept.querySelector('script')).toBeNull()
  expect(within(concept).getByText('stable')).toBeInTheDocument()
  expect(within(concept).getByText('(replaces)')).toBeInTheDocument()
  expect(within(concept).getByText('nothing')).toBeInTheDocument() // links to nothing
  expect(within(concept).getByRole('link', { name: 'site' })).toHaveAttribute('href', 'https://example.org/x')
  const graph = screen.getByRole('img', { name: 'Knowledge graph of Astro Lab' })
  expect(graph.querySelectorAll('a.on')).toHaveLength(1)
  expect(graph.querySelector('line.on')).not.toBeNull()
})

it('opens a concept from the list, the graph or a link in the text without leaving the page', async () => {
  const user = userEvent.setup()
  const badge = { ...LIST, concept: { ...DOOR.concept, id: 'decisions/badge-readers', title: 'Badge readers', html: '<p>BADGE-1</p>', links_in: [] } }
  const { calls } = serve({
    ...lead,
    'GET /web-api/orgs/o1/knowledge': { json: LIST },
    'GET /web-api/orgs/o1/knowledge?concept=facts%2Flab-door': { json: DOOR },
    'GET /web-api/orgs/o1/knowledge?concept=decisions%2Fbadge-readers': { json: badge },
  })
  const router = await openApp('/orgs/o1/knowledge')
  const graph = await screen.findByRole('img', { name: 'Knowledge graph of Astro Lab' })
  await user.click(within(graph).getByText('Lab door code'))
  expect(await screen.findByText('DOOR-1')).toBeInTheDocument()
  expect(router.state.location.search).toBe('?concept=facts%2Flab-door')
  // A link the server wrote into the concept's text, to another concept of the same bundle.
  await user.click(within(document.querySelector('#concept .doc') as HTMLElement).getByRole('link', { name: 'Badge readers' }))
  expect(await screen.findByText('BADGE-1')).toBeInTheDocument()
  expect(router.state.location.pathname).toBe('/orgs/o1/knowledge')
  expect(calls.filter((call) => call.path === '/web-api/session')).toHaveLength(1) // the application was not reloaded
})

it('explains how to add knowledge when there are no concepts', async () => {
  serve({ ...lead, 'GET /web-api/orgs/o1/knowledge': { json: { ...LIST, edge_count: 0, concepts: [], graph: { ...GRAPH, nodes: [], lines: [], legend: [] }, log_html: '' } } })
  await openApp('/orgs/o1/knowledge')
  expect(await screen.findByText(/Nothing has been written yet/)).toBeInTheDocument()
  expect(screen.getByText('knowledge_astro-okf_create')).toBeInTheDocument()
  expect(screen.queryByRole('img')).toBeNull()
  expect(screen.getByText('0 concepts, 0 links · read-only', { exact: false })).toBeInTheDocument()
})

it('says how many concepts the graph leaves out', async () => {
  serve({ ...lead, 'GET /web-api/orgs/o1/knowledge': { json: { ...LIST, graph: { ...GRAPH, hidden: 7 } } } })
  await openApp('/orgs/o1/knowledge')
  expect(await screen.findByText(/Showing the 2 most linked; 7 more are in the list below\./)).toBeInTheDocument()
})
