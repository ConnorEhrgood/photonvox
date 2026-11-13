import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ago } from './format'
import { useLoad } from './useLoad'

describe('ago', () => {
  const now = Date.parse('2026-11-13T12:00:00Z')
  const at = (s: number) => new Date(now - s * 1000).toISOString()
  it('says how long ago in words', () => {
    expect(ago(at(30), now)).toBe('just now')
    expect(ago(at(-30), now)).toBe('just now')                 // a clock slightly ahead is not "in the future"
    expect(ago(at(600), now)).toBe('10 minutes ago')
    expect(ago(at(3 * 3600), now)).toBe('3 hours ago')
    expect(ago(at(5 * 86400), now)).toBe('5 days ago')
  })
  it('uses the real clock by default', () => {
    expect(ago(new Date().toISOString())).toBe('just now')
  })
})

describe('useLoad', () => {
  it('loads, and keeps the newest answer when an older one arrives late', async () => {
    let release: (v: string) => void = () => {}
    const slow = new Promise<string>((r) => { release = r })
    const { result, rerender } = renderHook(({ fn }) => useLoad(fn, [fn]), { initialProps: { fn: () => slow } })
    expect(result.current.loading).toBe(true)
    rerender({ fn: () => Promise.resolve('new') })
    await waitFor(() => expect(result.current.data).toBe('new'))
    await act(async () => { release('old') })
    expect(result.current.data).toBe('new') && expect(result.current.loading).toBe(false)
  })
  it('says what went wrong, Error or not, and an older failure arriving late is ignored', async () => {
    const { result, rerender } = renderHook(({ fn }) => useLoad(fn, [fn]), { initialProps: { fn: (): Promise<string> => Promise.reject(new Error('nope')) } })
    await waitFor(() => expect(result.current.error).toBe('nope'))
    let fail: (e: unknown) => void = () => {}
    rerender({ fn: () => new Promise<string>((_, rej) => { fail = rej }) })
    rerender({ fn: () => Promise.reject('plain') })
    await waitFor(() => expect(result.current.error).toBe('plain'))
    await act(async () => { fail(new Error('late')) })
    expect(result.current.error).toBe('plain')
  })
})
