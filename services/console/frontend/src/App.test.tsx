import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import App from './App'

it('names the console', () => {
  render(<App />)
  expect(screen.getByRole('heading', { name: 'LLMoxie console' })).toBeInTheDocument()
})
