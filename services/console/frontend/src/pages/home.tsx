import { Link } from 'react-router'
import { PageHeader, Section } from '@/components/page'
import { StatusTag } from '@/components/status-badge'
import { Table, TableBody, TableCell, TableRow } from '@/components/ui/table'
import type { SignedIn } from '@/lib/types'

export function Home({ session }: { session: SignedIn }) {
  const { me, config } = session
  return (
    <>
      <PageHeader title="Welcome" lede={me.email} />
      {me.is_admin && (
        <Section title="SSEC admin">
          <p>
            <Link to="/admin">Organizations</Link> · <Link to="/admin/audit">Audit log</Link>
            {config.litellm_admin_url && (
              <>
                {' '}
                ·{' '}
                <a href={`${config.litellm_admin_url}/ui/`} rel="noopener">
                  LiteLLM UI
                </a>
              </>
            )}
          </p>
        </Section>
      )}
      {me.lead_orgs.length > 0 && (
        <Section title="Organizations you lead">
          <Table>
            <TableBody>
              {me.lead_orgs.map((org) => (
                <TableRow key={org.id}>
                  <TableCell>
                    <Link to={`/orgs/${org.id}`}>{org.name}</Link>
                  </TableCell>
                  <TableCell className="text-right">
                    <StatusTag status={org.status} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Section>
      )}
      {me.teams.length > 0 && (
        <Section title="Your teams">
          <Table>
            <TableBody>
              {me.teams.map((team) => (
                <TableRow key={team.id}>
                  <TableCell>
                    <Link to={`/teams/${team.id}`}>{team.name}</Link>
                  </TableCell>
                  <TableCell className="text-muted-foreground">{team.org_name}</TableCell>
                  <TableCell className="text-right">
                    <StatusTag status={team.status} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Section>
      )}
    </>
  )
}
