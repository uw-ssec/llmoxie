import type { ActionResult } from '@/lib/api'
import type { PendingInvite } from '@/lib/types'
import { ActionButton } from './action-button'

/**
 * Invitations not yet settled. One sent and not yet accepted can be cancelled; one accepted from a
 * different address than it was sent to waits here for a yes or a no.
 */
export function PendingInvites({
  invites,
  decide,
  cancel,
}: {
  invites: PendingInvite[]
  decide: (invite: PendingInvite, approve: boolean) => Promise<ActionResult>
  /** Leave out when this viewer may not cancel invitations. */
  cancel?: (invite: PendingInvite) => Promise<ActionResult>
}) {
  if (invites.length === 0) return null
  return (
    <ul className="flex flex-col gap-2">
      {invites.map((invite) => (
        <li key={invite.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md bg-muted px-4 py-2 text-sm">
          <span className="font-medium">{invite.email}</span>
          {invite.status === 'needs_approval' ? (
            <>
              <span>
                signed in as <strong>{invite.signin_email ?? 'an unverified address'}</strong>
              </span>
              <span className="ml-auto flex gap-1">
                <ActionButton call={() => decide(invite, true)}>Approve</ActionButton>
                <ActionButton call={() => decide(invite, false)}>Reject</ActionButton>
              </span>
            </>
          ) : (
            <>
              <span className="text-muted-foreground">invited, not yet accepted</span>
              {cancel && (
                <span className="ml-auto">
                  <ActionButton call={() => cancel(invite)}>Cancel invitation</ActionButton>
                </span>
              )}
            </>
          )}
        </li>
      ))}
    </ul>
  )
}
