import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import { TypeToConfirmDialog } from './type-to-confirm-dialog'

it('keeps the confirm button disabled until the text matches exactly, then sends what was typed', async () => {
  const user = userEvent.setup()
  const onConfirm = vi.fn().mockResolvedValue(undefined)
  render(
    <TypeToConfirmDialog trigger="Remove organization" title="Remove Astro Lab" description="This cannot be undone."
      prompt="Type the short name" expected="astro-lab" confirmLabel="Remove organization" onConfirm={onConfirm} />,
  )
  await user.click(screen.getByRole('button', { name: 'Remove organization' }))
  const dialog = screen.getByRole('dialog')
  const confirm = screen.getAllByRole('button', { name: 'Remove organization' }).find((b) => dialog.contains(b))!
  expect(confirm).toBeDisabled()
  await user.type(screen.getByRole('textbox'), 'Astro-Lab')
  expect(confirm).toBeDisabled()
  await user.clear(screen.getByRole('textbox'))
  await user.type(screen.getByRole('textbox'), 'astro-lab')
  expect(confirm).toBeEnabled()
  await user.click(confirm)
  expect(onConfirm).toHaveBeenCalledWith('astro-lab')
})
