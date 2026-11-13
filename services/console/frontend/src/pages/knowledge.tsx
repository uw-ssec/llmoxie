import { Fragment, useEffect, type MouseEvent } from 'react'
import { Link, useLoaderData, useNavigate } from 'react-router'
import { KnowledgeGraph } from '@/components/knowledge-graph'
import { Muted, PageHeader, Section } from '@/components/page'
import { Tag } from '@/components/status-badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { day } from '@/lib/format'
import { num, th } from '@/lib/styles'
import type { ConceptLink, KnowledgePage } from '@/lib/types'

const plural = (count: number, word: string) => `${count} ${word}${count === 1 ? '' : 's'}`
const address = (id: string) => `?concept=${encodeURIComponent(id)}`

/**
 * An organization's knowledge base, for its leads: read-only. The text is what members' tools wrote,
 * so it is not trusted. The server turns it into HTML in which markup is text and only safe links
 * survive (console_app/web/markdown.py); this page inserts that HTML as it is and adds nothing to it.
 */
export function KnowledgePageView() {
  const view = useLoaderData() as KnowledgePage
  const { org, concepts, concept, graph } = view
  const navigate = useNavigate()

  // Opening a concept is a change of address on this page, not a new page load.
  const open = (id: string) => ({
    href: address(id),
    onClick: (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
      event.preventDefault()
      void navigate(address(id))
    },
  })

  // The same for a link the server wrote into the text: `?concept=<id>#concept`, to another concept here.
  const followTextLink = (event: MouseEvent<HTMLDivElement>) => {
    const href = (event.target as Element).closest('a')?.getAttribute('href')
    if (!href?.startsWith('?concept=')) return
    const id = new URLSearchParams(href.slice(1).split('#')[0]).get('concept')
    if (id) open(id).onClick(event)
  }

  useEffect(() => {
    if (concept) document.getElementById('concept')?.scrollIntoView?.({ block: 'start' })
  }, [concept?.id]) // eslint-disable-line react-hooks/exhaustive-deps -- only when another concept is opened

  return (
    <>
      <PageHeader
        title="Knowledge"
        lede={
          <>
            <Link to={`/orgs/${org.id}`}>{org.name}</Link> · {plural(concepts.length, 'concept')}, {plural(view.edge_count, 'link')} · read-only
            <span className="block">
              One knowledge base, shared by all of {org.name}'s teams and written through their MCP clients. Only leads can read all of it
              here.
            </span>
          </>
        }
      />
      {concepts.length === 0 ? (
        <Section>
          <Muted>
            Nothing has been written yet. Members add knowledge from their MCP client, with the tools named{' '}
            <code>{view.tools}-okf_create</code> and <code>{view.tools}-okf_relate</code>.
          </Muted>
        </Section>
      ) : (
        <>
          {concept && (
            <section id="concept" className="scroll-mt-20">
              <Section
                title={
                  <span className="flex flex-wrap items-center gap-3">
                    {concept.title} <Tag>{concept.type}</Tag>
                    {concept.status && <Tag>{concept.status}</Tag>}
                  </span>
                }
              >
                {/* The text at reading width; beside it, what the concept is and what it links to. */}
                <div className="grid gap-x-10 gap-y-5 @4xl:grid-cols-[minmax(0,75ch)_minmax(14rem,1fr)]">
                  <div className="flex min-w-0 flex-col gap-5">
                    {concept.description && <p className="text-base">{concept.description}</p>}
                    <div className="doc" onClick={followTextLink} dangerouslySetInnerHTML={{ __html: concept.html }} />
                  </div>
                  <div className="flex flex-col gap-5 @4xl:border-l @4xl:pl-10">
                    <p className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
                      <code>{concept.id}</code>
                      {concept.written_at && <span>· written {concept.written_at}</span>}
                      {(concept.tags ?? []).map((tag) => (
                        <Tag key={tag}>{tag}</Tag>
                      ))}
                    </p>
                    <dl className="flex flex-col gap-1 text-sm">
                      <dt className={th}>Links to</dt>
                      <dd className="mb-3">
                        <Links to={concept.links_out} open={open} />
                      </dd>
                      <dt className={th}>Linked from</dt>
                      <dd>
                        <Links to={concept.links_in} open={open} />
                      </dd>
                    </dl>
                  </div>
                </div>
              </Section>
            </section>
          )}

          <Section
            title="Graph"
            description={
              <>
                Each dot is a concept and each arrow a link from one to another. Select a dot to read the concept.
                {graph.hidden > 0 && ` Showing the ${graph.nodes.length} most linked; ${graph.hidden} more are in the list below.`}
              </>
            }
          >
            <KnowledgeGraph graph={graph} label={`Knowledge graph of ${org.name}`} link={open} />
          </Section>

          <Section title="Concepts">
            <Table stack="medium">
              <TableHeader>
                <TableRow>
                  <TableHead className={th}>Concept</TableHead>
                  <TableHead className={th}>Type</TableHead>
                  <TableHead className={th}>About</TableHead>
                  <TableHead className={`${th} ${num}`}>Links</TableHead>
                  <TableHead className={th}>Written</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {concepts.map((item) => (
                  <TableRow key={item.id}>
                    <TableCell>
                      <a {...open(item.id)}>{item.title}</a>
                      <br />
                      <code>{item.id}</code>
                    </TableCell>
                    <TableCell>{item.type}</TableCell>
                    <TableCell className="whitespace-normal">
                      {item.description}{' '}
                      {(item.tags ?? []).map((tag) => (
                        <Tag key={tag}>{tag}</Tag>
                      ))}
                    </TableCell>
                    <TableCell className={num}>{item.links}</TableCell>
                    <TableCell className="tabular-nums">{day(item.written_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Section>

          {view.log_html && (
            <Section title="Change log" description="Kept by the knowledge base itself, newest first.">
              <div className="doc" dangerouslySetInnerHTML={{ __html: view.log_html }} />
            </Section>
          )}
        </>
      )}
    </>
  )
}

function Links({ to, open }: { to: ConceptLink[]; open: (id: string) => { href: string; onClick: (event: MouseEvent) => void } }) {
  if (to.length === 0) return <span className="text-muted-foreground">nothing</span>
  return (
    <>
      {to.map((link, index) => (
        <Fragment key={link.id}>
          {index > 0 && ', '}
          <a {...open(link.id)}>{link.title}</a>
          {link.note && <span className="text-muted-foreground"> ({link.note})</span>}
        </Fragment>
      ))}
    </>
  )
}
