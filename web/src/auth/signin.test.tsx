import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { App } from '../App'
import { FakeSource, fakeFetch, ME } from '../test/helpers'
import { AuthProvider } from './AuthContext'

/** The suite's sign-in contract (photonid docs/SIGNIN-PLAN.md) as PhotonVox's app follows it, through the shared ph-auth module. */
function app(path: string, source: FakeSource, routes: Record<string, unknown> = {}) {
  const f = fakeFetch({ 'GET /me': ME, ...routes })
  vi.stubGlobal('fetch', f.fn)
  window.history.replaceState(null, '', path)          // RequireSignIn reads the deep link from the real location, as in the browser
  render(<MemoryRouter initialEntries={[path]}><AuthProvider source={source} baseUrl="https://api.test"><App /></AuthProvider></MemoryRouter>)
  return f
}
const production = (token: string | null = null) => { const s = new FakeSource(token); s.supportsPaste = false; return s }
const reply = (status: number, code: string, detail = 'words') => new Response(JSON.stringify({ detail: { code, detail } }), { status })

describe('signed out', () => {
  it('a deep link goes straight to PhotonID, keeping path, query and hash, with no sign-in page of our own', async () => {
    const s = production()
    app('/numbers?site=a#n1', s)
    await waitFor(() => expect(s.fake.signIn).toHaveBeenCalledWith('/numbers?site=a#n1'))
    expect(s.fake.signIn).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('status')).toHaveTextContent('Signing you in')
    expect(screen.queryByRole('button', { name: /sign in/i })).toBeNull()
  })
  it('the old /login address is home, which then goes to PhotonID', async () => {
    const s = production()
    app('/login', s)
    await waitFor(() => expect(s.fake.signIn).toHaveBeenCalledTimes(1))
  })
  it('a development build shows the paste-a-token page instead, and a pasted token signs in', async () => {
    const s = new FakeSource(null)
    app('/overview', s)
    expect(await screen.findByRole('heading', { name: 'Developer sign-in' })).toBeInTheDocument()
    expect(s.fake.signIn).not.toHaveBeenCalled()
    const use = screen.getByRole('button', { name: 'Use token' })
    expect(use).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Access token'), 'abc')
    await userEvent.click(use)
    await waitFor(() => expect(screen.queryByRole('heading', { name: 'Developer sign-in' })).toBeNull())
  })
  it('the paste page can also sign in with the development PhotonID', async () => {
    const s = new FakeSource(null)
    s.signIn.mockClear()
    app('/login', s)
    await userEvent.click(await screen.findByRole('button', { name: 'Sign in with PhotonID' }))
    expect(s.signIn).toHaveBeenCalledWith('/')
  })
})

describe('coming back from PhotonID', () => {
  it('/auth/callback finishes the sign-in, loads the person and goes where they were headed', async () => {
    const s = production('tok')
    s.fake.handleCallback.mockResolvedValueOnce('/numbers?site=a')
    const { calls } = app('/auth/callback?code=x&state=y', s, { 'GET /numbers': [] })
    await waitFor(() => expect(calls.some((c) => c.path === '/me')).toBe(true))
    expect(s.fake.handleCallback).toHaveBeenCalledTimes(1)
  })
  it('a failed callback is a page with Try again, never a redirect by itself', async () => {
    const s = production()
    s.fake.handleCallback.mockRejectedValueOnce(new Error('state mismatch'))
    app('/auth/callback?code=x', s)
    expect(await screen.findByRole('heading', { name: "We couldn't sign you in" })).toBeInTheDocument()
    expect(s.fake.signIn).not.toHaveBeenCalled()
  })
  it('a 401 right after signing in is the problem page: one trip to PhotonID, no loop', async () => {
    const s = production('tok')
    s.unauthorized.mockResolvedValueOnce('problem')
    app('/overview', s, { 'GET /me': new Response('{"detail":"Invalid token"}', { status: 401 }) })
    expect(await screen.findByRole('heading', { name: "We couldn't sign you in" })).toBeInTheDocument()
    expect(s.fake.signIn).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(s.signOut).toHaveBeenCalled()
  })
  it('a 401 later in the session (it ended) goes to PhotonID again, back to the same page', async () => {
    const s = production('tok')
    app('/overview?x=1', s, { 'GET /me': new Response('{}', { status: 401 }) })
    await waitFor(() => expect(s.fake.signIn).toHaveBeenCalledWith('/overview?x=1'))
    expect(s.unauthorized).toHaveBeenCalledTimes(1)
  })
})

describe('a 403 is always a page', () => {
  it('no access to PhotonVox: a page with Sign out, no redirect', async () => {
    const s = production('tok')
    app('/overview', s, { 'GET /me': reply(403, 'no_access', 'This account has no access to PhotonVox.') })
    expect(await screen.findByRole('heading', { name: 'No access to PhotonVox' })).toBeInTheDocument()
    expect(screen.getByText('This account has no access to PhotonVox.')).toBeInTheDocument()
    expect(s.fake.signIn).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(s.signOut).toHaveBeenCalled()
  })
  it('any other 403 on /me is the same page', async () => {
    const s = production('tok')
    app('/overview', s, { 'GET /me': new Response('{"detail":"Forbidden"}', { status: 403 }) })
    expect(await screen.findByRole('heading', { name: 'No access to PhotonVox' })).toBeInTheDocument()
    expect(s.fake.signIn).not.toHaveBeenCalled()
  })
  it('access being set up: the shared page, which checks again by itself', async () => {
    const s = production('tok')
    app('/overview', s, { 'GET /me': reply(503, 'access_pending') })
    expect(await screen.findByRole('heading', { name: /Setting up your access to PhotonVox/ })).toBeInTheDocument()
    expect(s.fake.signIn).not.toHaveBeenCalled()
  })
})

describe('signing out', () => {
  it('/auth/signed-out (PhotonID’s post-logout address) goes straight on to the sign-in form', async () => {
    const s = production()
    app('/auth/signed-out', s)
    await waitFor(() => expect(s.fake.afterSignOut).toHaveBeenCalledTimes(1))
    expect(screen.getByRole('status')).toHaveTextContent('Signed out')
  })
  it('the auth routes in a paste-only development build go to the paste page', async () => {
    const s = new FakeSource(null)
    ;(s as { auth: unknown }).auth = null
    app('/auth/signed-out', s)
    expect(await screen.findByRole('heading', { name: 'Developer sign-in' })).toBeInTheDocument()
  })
  it('… and so does the callback', async () => {
    const s = new FakeSource(null)
    ;(s as { auth: unknown }).auth = null
    app('/auth/callback', s)
    expect(await screen.findByRole('heading', { name: 'Developer sign-in' })).toBeInTheDocument()
  })
})

describe('tokens', () => {
  it('nothing about the session is written to localStorage', async () => {
    localStorage.clear()
    const s = production('tok')
    app('/overview', s, { 'GET /me': reply(403, 'no_access') })
    await screen.findByRole('heading', { name: 'No access to PhotonVox' })
    expect(Object.keys(localStorage).filter((k) => /oidc|token|auth/i.test(k))).toEqual([])
  })
})
