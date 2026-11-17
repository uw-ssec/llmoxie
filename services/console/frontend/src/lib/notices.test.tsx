import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { Notices } from '@/components/notices'
import { notices } from './notices'

beforeEach(() => vi.useFakeTimers())
afterEach(() => {
  notices.clear()
  vi.useRealTimers()
})

it('lets a success fade, and keeps a failure until it is dismissed', () => {
  render(<Notices />)
  act(() => {
    notices.add('good', 'Team budget updated.')
    notices.add('bad', 'You do not have access to that.')
  })
  expect(screen.getByText('Team budget updated.')).toBeInTheDocument()
  // A failure is announced at once; a success waits its turn.
  expect(screen.getByRole('alert')).toHaveTextContent('You do not have access to that.')
  act(() => { vi.advanceTimersByTime(60_000) })
  expect(screen.queryByText('Team budget updated.')).toBeNull()
  expect(screen.getByText('You do not have access to that.')).toBeInTheDocument() // not gone while nobody was looking
  act(() => screen.getByRole('button', { name: 'Dismiss' }).click())
  expect(screen.queryByText('You do not have access to that.')).toBeNull()
})
