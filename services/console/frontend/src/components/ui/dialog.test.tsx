import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import { ActionButton } from '@/components/action-button'
import { TypeToConfirmDialog } from '@/components/type-to-confirm-dialog'
import { createMemoryRouter, RouterProvider } from 'react-router'

// The console's content security policy allows no inline styles, and a library that adds a <style>
// element at run time is refused by it: the dialog would open, but whatever that style did would not
// happen and the browser would log a violation. These dialogs must add none.
function styleElements() {
  return document.querySelectorAll('style').length
}

it('opens a dialog without adding a style element, and locks the page behind it', async () => {
  const user = userEvent.setup()
  render(
    <TypeToConfirmDialog trigger="Remove team" title="Remove Workshop" description="This cannot be undone."
      prompt="Type the team's name" expected="Workshop" confirmLabel="Remove team" onConfirm={vi.fn()} />,
  )
  const before = styleElements()
  expect(screen.queryByRole('dialog')).toBeNull()
  await user.click(screen.getByRole('button', { name: 'Remove team' }))
  const dialog = screen.getByRole('dialog', { name: 'Remove Workshop' })
  expect(dialog).toHaveAccessibleDescription('This cannot be undone.')
  expect(styleElements()).toBe(before)
  expect(document.documentElement).toHaveClass('overflow-hidden')
  // Escape reaches a native dialog as a `cancel` followed by `close`.
  fireEvent(dialog, new Event('close'))
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(document.documentElement).not.toHaveClass('overflow-hidden')
})

it('asks before an action that cannot be undone, and does nothing on Cancel', async () => {
  const user = userEvent.setup()
  const call = vi.fn().mockResolvedValue({ message: 'Team archived. 2 key(s) deleted.' })
  const router = createMemoryRouter([{
    path: '/',
    element: (
      <ActionButton call={call} variant="destructive" confirm={{ title: 'Archive this team?', description: 'Deletes every key in this team.' }}>
        Archive team
      </ActionButton>
    ),
  }])
  render(<RouterProvider router={router} />)
  const before = styleElements()
  await user.click(await screen.findByRole('button', { name: 'Archive team' }))
  const dialog = screen.getByRole('alertdialog', { name: 'Archive this team?' })
  expect(styleElements()).toBe(before)
  await user.click(screen.getByRole('button', { name: 'Cancel' }))
  expect(screen.queryByRole('alertdialog')).toBeNull()
  expect(call).not.toHaveBeenCalled()

  await user.click(screen.getByRole('button', { name: 'Archive team' }))
  const confirm = screen.getAllByRole('button', { name: 'Archive team' }).find((b) => screen.getByRole('alertdialog').contains(b))!
  await user.click(confirm)
  expect(call).toHaveBeenCalledTimes(1)
  await vi.waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull())
  expect(dialog).not.toBeVisible() // closed and hidden; the element itself stays, so focus can return to the button
})

it('closes only on a click outside it, not on one in its own margin, and closes through the element itself', async () => {
  const user = userEvent.setup()
  const close = vi.spyOn(HTMLDialogElement.prototype, 'close')
  render(
    <TypeToConfirmDialog trigger="Remove team" title="Remove Workshop" description="This cannot be undone."
      prompt="Type the team's name" expected="Workshop" confirmLabel="Remove team" onConfirm={vi.fn()} />,
  )
  await user.click(screen.getByRole('button', { name: 'Remove team' }))
  const dialog = screen.getByRole('dialog')
  await user.type(screen.getByRole('textbox'), 'Works')
  // The space around the dialog's content is still the dialog: a click there must not throw away what was typed.
  fireEvent.click(dialog.querySelector('[data-slot="dialog-body"]')!)
  expect(screen.getByRole('textbox')).toHaveValue('Works')
  // The element's own close() is what hands focus back to the button that opened it.
  close.mockClear()
  await user.click(screen.getByRole('button', { name: 'Cancel' }))
  expect(close).toHaveBeenCalled()
  expect(screen.queryByRole('dialog')).toBeNull()

  await user.click(screen.getByRole('button', { name: 'Remove team' }))
  fireEvent.click(screen.getByRole('dialog')) // on the dialog element itself: the backdrop
  expect(screen.queryByRole('dialog')).toBeNull()
  close.mockRestore()
})
