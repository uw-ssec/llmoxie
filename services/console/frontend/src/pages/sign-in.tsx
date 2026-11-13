import { useSearchParams } from 'react-router'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Centered } from '@/components/page'

/** What anyone sees before signing in. `next` is where to return to afterwards; the server checks it. */
export function SignIn() {
  const [query] = useSearchParams()
  return (
    <Centered title="LLMoxie console">
      <p className="text-lg text-muted-foreground">Manage your organization's teams, models and API keys.</p>
      {query.get('signin') === 'failed' && (
        <Alert variant="destructive" role="alert">
          <AlertDescription>That sign-in could not be completed. Please start again.</AlertDescription>
        </Alert>
      )}
      {/* A plain form, not a call: signing in leaves for the identity provider. */}
      <form method="post" action="/login">
        <input type="hidden" name="next" value={query.get('next') ?? '/'} />
        <Button type="submit" size="lg">
          Sign in
        </Button>
      </form>
    </Centered>
  )
}
