import { useRouteLoaderData } from 'react-router'
import type { Session, SignedIn } from './types'

/** Who is signed in, as the root route loaded it. */
export function useSession(): Session {
  return useRouteLoaderData('root') as Session
}

/** For pages only someone signed in can reach. */
export function useSignedIn(): SignedIn {
  return useSession() as SignedIn
}
