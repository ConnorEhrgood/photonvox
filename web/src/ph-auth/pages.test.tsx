// GENERATED from @photon/ui by scripts/sync-vendored.mjs. Do not edit here: change photon-ui, then re-run it. photon-ui 031c370e5fa1
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { StrictMode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { AccessPending, CallbackRoute, NoAccess, RequireSignIn, SignedOutRoute, SignInProblem, SigningIn } from './pages'
import { SignInError, type PhotonSignIn } from './signin'

function fakeAuth(over: Partial<Record<keyof PhotonSignIn, unknown>> = {}) {
  return {
    signIn: vi.fn(async () => {}),
    signOut: vi.fn(async () => {}),
    afterSignOut: vi.fn(async () => {}),
    handleCallback: vi.fn(async () => '/o/1/team'),
    ...over,
  } as unknown as PhotonSignIn & Record<string, ReturnType<typeof vi.fn>>
}

describe('the sign-in screens', () => {
  it('signing in is a live status with the logo', () => {
    render(<SigningIn logo="/logo.png" />)
    expect(screen.getByRole('status')).toHaveTextContent('Signing you in')
    expect(screen.getByRole('img', { name: 'Photon' })).toHaveAttribute('src', '/logo.png')
  })

  it('a problem offers Try again and Sign out, with the detail', async () => {
    const retry = vi.fn(), out = vi.fn()
    render(<SignInProblem detail="access_denied" onRetry={retry} onSignOut={out} />)
    expect(screen.getByRole('heading')).toHaveTextContent("We couldn't sign you in")
    expect(screen.getByText(/access_denied/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(retry).toHaveBeenCalled()
    expect(out).toHaveBeenCalled()
  })

  it('a problem without sign out or detail shows neither', () => {
    render(<SignInProblem onRetry={() => {}} />)
    expect(screen.queryByRole('button', { name: 'Sign out' })).toBeNull()
    expect(screen.queryByText(/Details/)).toBeNull()
  })

  it('access being set up names the product and lets you sign out', async () => {
    const out = vi.fn()
    render(<AccessPending product="PhotonConsole" onSignOut={out} />)
    expect(screen.getByRole('status')).toHaveTextContent('Setting up your access to PhotonConsole')
    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(out).toHaveBeenCalled()
  })

  it('no access says so, with the product or its own words', () => {
    const { rerender } = render(<NoAccess product="PhotonGuard" onSignOut={() => {}} />)
    expect(screen.getByRole('heading')).toHaveTextContent('No access to PhotonGuard')
    expect(screen.getByText(/has no access to PhotonGuard/)).toBeInTheDocument()
    rerender(<NoAccess product="PhotonID" detail="This account is disabled." onSignOut={() => {}} />)
    expect(screen.getByText('This account is disabled.')).toBeInTheDocument()
  })
})

describe('RequireSignIn', () => {
  it('shows the content when signed in, and does not leave', () => {
    const auth = fakeAuth()
    render(<RequireSignIn auth={auth} signedIn><p>inside</p></RequireSignIn>)
    expect(screen.getByText('inside')).toBeInTheDocument()
    expect(auth.signIn).not.toHaveBeenCalled()
  })

  it('waits while the product finds out', () => {
    const auth = fakeAuth()
    render(<RequireSignIn auth={auth} signedIn={null}><p>inside</p></RequireSignIn>)
    expect(screen.getByRole('status')).toHaveTextContent('Loading')
    expect(auth.signIn).not.toHaveBeenCalled()
  })

  it('signed out: straight to PhotonID with the address the visitor asked for (no sign-in card)', () => {
    window.history.replaceState(null, '', '/o/1/sites?x=1#map')
    const auth = fakeAuth()
    render(<StrictMode><RequireSignIn auth={auth} signedIn={false}><p>inside</p></RequireSignIn></StrictMode>)
    expect(auth.signIn).toHaveBeenCalledWith('/o/1/sites?x=1#map')
    expect(screen.queryByRole('button')).toBeNull()
    expect(screen.getByRole('status')).toHaveTextContent('Signing you in')
  })

  it('when leaving fails it shows the problem and Try again reloads', async () => {
    const reload = vi.fn()
    const original = window.location
    Object.defineProperty(window, 'location', { configurable: true, value: { ...original, reload, pathname: '/', search: '', hash: '' } })
    try {
      const auth = fakeAuth({ signIn: vi.fn(async () => { throw new Error('PhotonID unreachable') }) })
      render(<RequireSignIn auth={auth} signedIn={false}><p>inside</p></RequireSignIn>)
      expect(await screen.findByText(/PhotonID unreachable/)).toBeInTheDocument()
      await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
      expect(reload).toHaveBeenCalled()
    } finally {
      Object.defineProperty(window, 'location', { configurable: true, value: original })
    }
  })

  it('a thrown non-error is shown as text', async () => {
    const auth = fakeAuth({ signIn: vi.fn(async () => { throw 'plain' }) })
    render(<RequireSignIn auth={auth} signedIn={false}><p>inside</p></RequireSignIn>)
    expect(await screen.findByText(/plain/)).toBeInTheDocument()
  })
})

describe('CallbackRoute', () => {
  it('finishes the sign-in once and hands the deep link to the product', async () => {
    const auth = fakeAuth()
    const done = vi.fn()
    render(<StrictMode><CallbackRoute auth={auth} onSignedIn={done} /></StrictMode>)
    await waitFor(() => expect(done).toHaveBeenCalledWith('/o/1/team'))
    expect(screen.getByRole('status')).toBeInTheDocument()
  })

  it('a refusal is a problem page, not a redirect: Try again starts over from home, Sign out signs out', async () => {
    const auth = fakeAuth({ handleCallback: vi.fn(async () => { throw new SignInError('access_denied') }) })
    render(<CallbackRoute auth={auth} onSignedIn={() => {}} />)
    expect(await screen.findByText(/access_denied/)).toBeInTheDocument()
    expect(auth.signIn).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(auth.signIn).toHaveBeenCalledWith('/')
    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(auth.signOut).toHaveBeenCalled()
  })

  it('a sign-out that cannot reach PhotonID says so instead of failing silently', async () => {
    const auth = fakeAuth({
      handleCallback: vi.fn(async () => { throw new SignInError('access_denied') }),
      signOut: vi.fn(async () => { throw new Error('Failed to fetch') }),
    })
    render(<CallbackRoute auth={auth} onSignedIn={() => {}} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Sign out' }))
    expect(await screen.findByText(/Sign-out did not complete \(Failed to fetch\)\. Try again\./)).toBeInTheDocument()
  })

  it('other failures show their message; a non-error too', async () => {
    const auth = fakeAuth({ handleCallback: vi.fn(async () => { throw new Error('network') }) })
    const { unmount } = render(<CallbackRoute auth={auth} onSignedIn={() => {}} />)
    expect(await screen.findByText(/network/)).toBeInTheDocument()
    unmount()
    render(<CallbackRoute auth={fakeAuth({ handleCallback: vi.fn(async () => { throw 'odd' }) })} onSignedIn={() => {}} />)
    expect(await screen.findByText(/odd/)).toBeInTheDocument()
  })

  it('does nothing after it has gone away', async () => {
    let resolve!: (v: string) => void
    const auth = fakeAuth({ handleCallback: vi.fn(() => new Promise<string>((r) => { resolve = r })) })
    const done = vi.fn()
    const { unmount } = render(<CallbackRoute auth={auth} onSignedIn={done} />)
    unmount()
    await act(async () => resolve('/x'))
    expect(done).not.toHaveBeenCalled()
  })
})

describe('SignedOutRoute', () => {
  it('goes straight on to the sign-in form', () => {
    const auth = fakeAuth()
    render(<SignedOutRoute auth={auth} />)
    expect(auth.afterSignOut).toHaveBeenCalled()
    expect(screen.getByRole('status')).toHaveTextContent('Signed out')
  })

  it('if PhotonID cannot be reached, a problem with Try again (the sign-in form again)', async () => {
    const auth = fakeAuth({ afterSignOut: vi.fn(async () => { throw new Error('offline') }) })
    render(<SignedOutRoute auth={auth} />)
    expect(await screen.findByText(/offline/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(auth.signIn).toHaveBeenCalledWith('/', { prompt: 'login' })
  })

  it('a thrown non-error is shown as text', async () => {
    render(<SignedOutRoute auth={fakeAuth({ afterSignOut: vi.fn(async () => { throw 'plain' }) })} />)
    expect(await screen.findByText(/plain/)).toBeInTheDocument()
  })
})
