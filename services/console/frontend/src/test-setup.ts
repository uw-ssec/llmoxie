import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

afterEach(() => {
  cleanup()
  window.localStorage.clear() // how the sidebar was left is remembered there; no test should inherit it
})

// jsdom's <dialog> has the `open` attribute but may lack the methods. Enough of them for the tests.
if (!HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute('open', '')
  }
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute('open')
    this.dispatchEvent(new Event('close'))
  }
}

// jsdom has no layout, so no ResizeObserver; the checkbox asks for one.
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
}
