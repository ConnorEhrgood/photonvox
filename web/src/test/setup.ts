import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

// Recent Node versions define their own, unusable `localStorage` global that can hide jsdom's,
// so make sure there is a working pair (same workaround as PhotonConsole).
class MemoryStorage implements Storage {
  private data = new Map<string, string>()
  get length() { return this.data.size }
  clear() { this.data.clear() }
  getItem(key: string) { return this.data.has(key) ? (this.data.get(key) as string) : null }
  key(index: number) { return [...this.data.keys()][index] ?? null }
  removeItem(key: string) { this.data.delete(key) }
  setItem(key: string, value: string) { this.data.set(key, String(value)) }
  [name: string]: unknown
}
for (const name of ['localStorage', 'sessionStorage'] as const) {
  if (typeof (globalThis as unknown as Record<string, { getItem?: unknown } | undefined>)[name]?.getItem !== 'function') {
    Object.defineProperty(globalThis, name, { configurable: true, value: new MemoryStorage() })
  }
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  try {
    localStorage.clear()
    sessionStorage.clear()
  } catch { /* storage unavailable */ }
})

// jsdom's Blob has no `stream()`, which Node's own `Response`/`fetch` call when handed one (`new Response(new Blob([...]))`). Give it one, built on
// jsdom's FileReader, so tests can use blobs the way the browser does.
if (typeof Blob !== 'undefined' && typeof Blob.prototype.stream !== 'function') {
  Blob.prototype.stream = function stream(this: Blob) {
    const blob = this
    return new ReadableStream<Uint8Array>({
      start(controller) {
        return new Promise<void>((resolve, reject) => {
          const reader = new FileReader()
          reader.onload = () => { controller.enqueue(new Uint8Array(reader.result as ArrayBuffer)); controller.close(); resolve() }
          reader.onerror = () => reject(reader.error)
          reader.readAsArrayBuffer(blob)
        })
      },
    })
  }
}
