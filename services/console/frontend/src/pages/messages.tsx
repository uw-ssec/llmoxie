// The pages that are one message each.
import { isRouteErrorResponse, useLoaderData, useParams, useRouteError } from 'react-router'
import { Button } from '@/components/ui/button'
import { Centered } from '@/components/page'
import { ApiError } from '@/lib/api'
import type { Invitation, Me } from '@/lib/types'

const lede = 'max-w-[60ch] text-lg text-muted-foreground'
const SPENT = 'It may have been used already, expired, or been replaced by a newer one. Ask for a new invitation.'

export function NotInvited({ me }: { me: Me }) {
  return (
    <Centered title="You are not invited yet">
      <p className={lede}>
        You are signed in{me.email ? ` as ${me.email}` : ''}, but this account is not part of any organization or team. Open the
        invitation link from your email, or ask your organization's lead to invite this address.
      </p>
    </Centered>
  )
}

/** Opening the link changes nothing. Only the button does, so an email scanner cannot use an invitation up. */
export function InvitationPage() {
  const info = useLoaderData() as Invitation
  const { token } = useParams()
  if (!info.valid) {
    return (
      <Centered title="This invitation cannot be used">
        <p className={lede}>{SPENT}</p>
      </Centered>
    )
  }
  return (
    <Centered title={info.kind === 'lead' ? `Lead ${info.org_name}` : `Join ${info.team_name}`}>
      <p className={lede}>
        {info.kind === 'lead'
          ? `You have been invited to manage ${info.org_name} on the LLMoxie console.`
          : `You have been invited to ${info.team_name}, run by ${info.org_name}.`}{' '}
        Sign in with the email address this invitation was sent to.
      </p>
      {/* A plain form, not a call: accepting signs you in first when you are not. */}
      <form method="post" action={`/invite/${token}`}>
        <Button type="submit" size="lg">
          Accept and sign in
        </Button>
      </form>
    </Centered>
  )
}

export function InvitationResult() {
  const { outcome } = useParams()
  return (
    <Centered title={outcome === 'waiting' ? 'Waiting for approval' : 'This invitation cannot be used'}>
      <p className={lede}>
        {outcome === 'waiting'
          ? "You signed in with a different email address than the one that was invited, so the organization's lead has to approve your request. You have no access until they do."
          : SPENT}
      </p>
      <p>
        <a href="/">Go to the console</a>
      </p>
    </Centered>
  )
}

/** Whatever went wrong loading a page, said plainly, with a way back. */
export function ErrorScreen() {
  const error = useRouteError()
  const message =
    error instanceof ApiError
      ? error.message
      : isRouteErrorResponse(error) && error.status === 404
        ? 'That does not exist.'
        : 'Something went wrong showing this page.'
  return (
    <Centered title={message}>
      <p>
        {/* A full reload: whatever state led here is dropped. */}
        <a href="/">Back to the console</a>
      </p>
    </Centered>
  )
}
