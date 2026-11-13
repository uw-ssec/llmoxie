import { Link, useLoaderData } from 'react-router'
import { ActionForm } from '@/components/action-form'
import { Field, Row } from '@/components/form-field'
import { Muted, PageHeader, Section } from '@/components/page'
import { StatusTag } from '@/components/status-badge'
import { Input } from '@/components/ui/input'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { post } from '@/lib/api'
import { usd } from '@/lib/format'
import { num, th } from '@/lib/styles'
import type { AdminOrgs } from '@/lib/types'

export function AdminOrgsPage() {
  const { orgs } = useLoaderData() as AdminOrgs
  return (
    <>
      <PageHeader title="Organizations" lede="Create organizations, set their budget ceilings and appoint their leads." />
      <Section>
        {orgs.length === 0 ? (
          <Muted>No organizations yet.</Muted>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className={th}>Organization</TableHead>
                <TableHead className={th}>Short name</TableHead>
                <TableHead className={`${th} ${num}`}>Budget ceiling</TableHead>
                <TableHead className={`${th} ${num}`}>Leads</TableHead>
                <TableHead className={`${th} ${num}`}>Teams</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {orgs.map((org) => (
                <TableRow key={org.id}>
                  <TableCell>
                    <Link to={`/orgs/${org.id}`}>{org.name}</Link>
                  </TableCell>
                  <TableCell>
                    <code>{org.slug}</code>
                  </TableCell>
                  <TableCell className={num}>{usd(org.budget_ceiling)}</TableCell>
                  <TableCell className={num}>{org.leads}</TableCell>
                  <TableCell className={num}>{org.teams}</TableCell>
                  <TableCell className="text-right">
                    <StatusTag status={org.status} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Section>
      <Section title="New organization">
        <ActionForm
          submit="Create organization"
          call={(fields) =>
            post('/admin/orgs', {
              name: String(fields.get('name')),
              slug: String(fields.get('slug')),
              budget_ceiling: Number(fields.get('budget_ceiling')),
            })
          }
        >
          <Field label="Name">
            <Input name="name" required minLength={2} maxLength={80} />
          </Field>
          <Row>
            <Field label="Short name, used as the model prefix">
              <Input name="slug" required pattern="[a-z0-9][a-z0-9\-]{1,30}" placeholder="e.g. uw-ess" />
            </Field>
            <Field label="Budget ceiling (USD)">
              <Input name="budget_ceiling" type="number" min={0} step={0.01} required />
            </Field>
          </Row>
        </ActionForm>
      </Section>
    </>
  )
}
