import { act, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from '../App'
import { ME, FakeSource, fakeFetch } from '../test/helpers'
import { AuthProvider, PENDING_RETRY_MS, useAuth } from './AuthContext'
import { TenantProvider, useTenant } from './TenantContext'

function Probe() {
  const { status } = useAuth()
  return <p>status: {status}</p>
}

function mount(routes: Record<string, unknown>, source = new FakeSource()) {
  const f = fakeFetch(routes)
  vi.stubGlobal('fetch', f.fn)
  render(<MemoryRouter><AuthProvider source={source} baseUrl="https://api.test"><Probe /></AuthProvider></MemoryRouter>)
  return { ...f, source }
}

const err = (status: number, code: string) => new Response(JSON.stringify({ detail: { code, detail: 'words' } }), { status })

describe('the states between signed out and ready', () => {
  beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }))
  afterEach(() => vi.useRealTimers())

  it('no token: signed out', async () => {
    mount({}, new FakeSource(null))
    expect(await screen.findByText('status: signedOut')).toBeInTheDocument()
  })
  it('a person the directory has not told us about yet is shown as pending and asked about again by itself', async () => {
    let n = 0
    const { calls } = mount({ 'GET /me': () => (++n < 3 ? err(503, 'access_pending') : ME) })
    expect(await screen.findByText('status: pending')).toBeInTheDocument()
    await act(async () => { await vi.advanceTimersByTimeAsync(PENDING_RETRY_MS) })
    expect(await screen.findByText('status: pending')).toBeInTheDocument()
    await act(async () => { await vi.advanceTimersByTimeAsync(PENDING_RETRY_MS) })
    expect(await screen.findByText('status: ready')).toBeInTheDocument()
    expect(calls.filter((c) => c.path === '/me').length).toBe(3)
  })
  it('an account with no access is said so and not retried', async () => {
    const { calls } = mount({ 'GET /me': () => err(403, 'no_access') })
    expect(await screen.findByText('status: noAccess')).toBeInTheDocument()
    await act(async () => { await vi.advanceTimersByTimeAsync(PENDING_RETRY_MS * 3) })
    expect(calls.length).toBe(1)
  })
  it('any other failure is an error with the API’s words', async () => {
    mount({ 'GET /me': new Response(JSON.stringify({ detail: 'database down' }), { status: 500 }) })
    expect(await screen.findByText('status: error')).toBeInTheDocument()
  })
  it('a 401 means signed out, not an error', async () => {
    mount({ 'GET /me': new Response('{}', { status: 401 }) })
    expect(await screen.findByText('status: signedOut')).toBeInTheDocument()
  })
  it('a network failure is an error', async () => {
    vi.stubGlobal('fetch', async () => { throw new TypeError('offline') })
    render(<MemoryRouter><AuthProvider source={new FakeSource()} baseUrl="https://api.test"><Probe /></AuthProvider></MemoryRouter>)
    expect(await screen.findByText('status: error')).toBeInTheDocument()
  })
  it('a non-Error rejection is still reported', async () => {
    vi.stubGlobal('fetch', async () => { throw 'weird' })    // eslint-disable-line no-throw-literal
    render(<MemoryRouter><AuthProvider source={new FakeSource()} baseUrl="https://api.test"><Probe /></AuthProvider></MemoryRouter>)
    expect(await screen.findByText('status: error')).toBeInTheDocument()
  })
})

describe('the app’s front doors', () => {
  const app = (routes: Record<string, unknown>) => {
    vi.stubGlobal('fetch', fakeFetch(routes).fn)
    render(<MemoryRouter initialEntries={['/overview']}><AuthProvider source={new FakeSource()} baseUrl="https://api.test"><App /></AuthProvider></MemoryRouter>)
  }
  it('pending shows a calm page that continues by itself', async () => {
    app({ 'GET /me': () => err(503, 'access_pending') })
    expect(await screen.findByRole('heading', { name: 'Setting up your access' })).toBeInTheDocument()
  })
  it('no access shows who is signed in and offers sign out', async () => {
    app({ 'GET /me': () => err(403, 'no_access') })
    expect(await screen.findByRole('heading', { name: 'No access to PhotonVox' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeInTheDocument()
  })
  it('an error offers to try again', async () => {
    app({ 'GET /me': new Response(JSON.stringify({ detail: 'database down' }), { status: 500 }) })
    expect(await screen.findByRole('heading', { name: 'Something went wrong' })).toBeInTheDocument()
    expect(screen.getByText('database down')).toBeInTheDocument()
  })
})

describe('tenant choice', () => {
  function Show() {
    const { current, can, select } = useTenant()
    return <><p>{current?.name ?? 'none'}</p><p>{can('vox.phone.enroll') ? 'can enroll' : 'cannot enroll'}</p><button onClick={() => select('zzz')}>pick missing</button></>
  }
  const withMe = (me: unknown, setup?: () => void) => {
    setup?.()
    vi.stubGlobal('fetch', fakeFetch({ 'GET /me': me }).fn)
    render(<MemoryRouter><AuthProvider source={new FakeSource()} baseUrl="https://api.test"><Wait><TenantProvider><Show /></TenantProvider></Wait></AuthProvider></MemoryRouter>)
  }
  function Wait({ children }: { children: React.ReactNode }) { return useAuth().status === 'ready' ? <>{children}</> : null }

  it('follows the capabilities the server sent', async () => {
    withMe(ME)
    expect(await screen.findByText('Cedar Works')).toBeInTheDocument()
    expect(screen.getByText('can enroll')).toBeInTheDocument()
  })
  it('falls back to the first organization when the remembered one is gone', async () => {
    withMe(ME, () => localStorage.setItem('pg:tenant', 'gone'))
    expect(await screen.findByText('Cedar Works')).toBeInTheDocument()
  })
  it('works when storage is unavailable', async () => {
    const real = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')!
    Object.defineProperty(globalThis, 'localStorage', { configurable: true, get() { throw new Error('blocked') } })
    try {
      withMe(ME)
      expect(await screen.findByText('Cedar Works')).toBeInTheDocument()
      await act(async () => { screen.getByText('pick missing').click() })
      await waitFor(() => expect(screen.getByText('Cedar Works')).toBeInTheDocument())     // an id that is not there falls back to the first; nothing throws
    } finally {
      Object.defineProperty(globalThis, 'localStorage', real)
    }
  })
  it('a person with no organizations has no current one and can do nothing', async () => {
    withMe({ ...ME, tenants: [] })
    expect(await screen.findByText('none')).toBeInTheDocument()
    expect(screen.getByText('cannot enroll')).toBeInTheDocument()
  })
})
