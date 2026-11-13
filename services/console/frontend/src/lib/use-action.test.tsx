import { act, renderHook } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, expect, it, vi } from 'vitest'
import { ApiError, type ActionResult } from './api'
import { notices } from './notices'
import { useAction } from './use-action'

afterEach(() => notices.clear())

function setup(loader = vi.fn(() => null)) {
  let hook!: ReturnType<typeof useAction>
  function Probe() {
    hook = useAction()
    return null
  }
  const router = createMemoryRouter(
    [
      { path: '/start', loader, element: <Probe /> },
      { path: '/orgs/:id', element: <p>org page</p> },
    ],
    { initialEntries: ['/start'] },
  )
  const view = renderHook(() => null, { wrapper: () => <RouterProvider router={router} /> })
  return { router, loader, view, get hook() { return hook } }
}

it('sends one request when run twice before the first settles', async () => {
  const t = setup()
  await vi.waitFor(() => expect(t.hook).toBeDefined())
  let finish!: (value: ActionResult) => void
  const call = vi.fn(() => new Promise<ActionResult>((resolve) => (finish = resolve)))
  await act(async () => {
    void t.hook.run(call)
    void t.hook.run(call)
  })
  expect(call).toHaveBeenCalledTimes(1)
  expect(t.hook.pending).toBe(true)
  await act(async () => finish({ message: 'Done.' }))
  expect(t.hook.pending).toBe(false)
})

it('shows the message, then reloads the page data when there is no goto', async () => {
  const t = setup()
  await vi.waitFor(() => expect(t.hook).toBeDefined())
  expect(t.loader).toHaveBeenCalledTimes(1)
  await act(async () => { await t.hook.run(async () => ({ message: 'Team budget updated.' })) })
  expect(notices.list().map((n) => [n.kind, n.message])).toEqual([['good', 'Team budget updated.']])
  await vi.waitFor(() => expect(t.loader).toHaveBeenCalledTimes(2))
})

it('goes to goto when the answer has one', async () => {
  const t = setup()
  await vi.waitFor(() => expect(t.hook).toBeDefined())
  await act(async () => { await t.hook.run(async () => ({ message: 'Created.', goto: '/orgs/7' })) })
  await vi.waitFor(() => expect(t.router.state.location.pathname).toBe('/orgs/7'))
})

it('keeps a refusal the user can fix for the form to show, and says other failures aloud', async () => {
  const t = setup()
  await vi.waitFor(() => expect(t.hook).toBeDefined())
  await act(async () => { await t.hook.run(async () => { throw new ApiError(409, 'That short name is taken.') }, { inline: true }) })
  expect(t.hook.error).toBe('That short name is taken.')
  expect(notices.list()).toEqual([])
  await act(async () => { await t.hook.run(async () => { throw new ApiError(502, 'Nothing was changed.') }, { inline: true }) })
  expect(t.hook.error).toBeNull()
  expect(notices.list().map((n) => [n.kind, n.message])).toEqual([['bad', 'Nothing was changed.']])
})
