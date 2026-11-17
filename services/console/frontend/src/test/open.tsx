// Opens the whole application at an address, against a stand-in server (see ./server).
import { render } from '@testing-library/react'
import { vi } from 'vitest'

export async function openApp(path: string) {
  vi.resetModules() // a fresh session cache for every test
  const { createMemoryRouter, RouterProvider } = await import('react-router')
  const { routes } = await import('@/router')
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  render(<RouterProvider router={router} />)
  return router
}
