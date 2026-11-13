import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '../auth/AuthContext'
import { Modal, NotYet, StatusBadge } from '../components/ui'
import { FakeSource, fakeFetch, ME, renderApp } from '../test/helpers'
import { CallbackPage, LoginPage } from './Login'
import * as Soon from './Soon'

function shell(source: FakeSource, routes: Record<string, unknown> = {}, path: string | { pathname: string; state: unknown } = '/login') {
  vi.stubGlobal('fetch', fakeFetch({ 'GET /me': ME, ...routes }).fn)
  render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider source={source} baseUrl="https://api.test">
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/auth/callback" element={<CallbackPage />} />
          <Route path="/overview" element={<p>overview page</p>} />
          <Route path="/phones" element={<p>phones page</p>} />
          <Route path="/" element={<p>home</p>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('LoginPage', () => {
  it('offers sign-in and no sign-up', async () => {
    const source = new FakeSource(null)
    shell(source)
    await userEvent.click(await screen.findByRole('button', { name: 'Sign in' }))
    expect(source.signIn).toHaveBeenCalled()
    expect(screen.queryByText(/create an account/i)).toBeNull()
  })
  it('shows why a sign-in could not start', async () => {
    const source = new FakeSource(null)
    source.signIn.mockRejectedValueOnce(new Error('issuer unreachable'))
    shell(source)
    await userEvent.click(await screen.findByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('issuer unreachable')
  })
  it('lets a developer paste a token, and is on its way home once signed in', async () => {
    const source = new FakeSource(null)
    shell(source)
    await userEvent.click(await screen.findByText(/Developer: paste/))
    const use = screen.getByRole('button', { name: 'Use token' })
    expect(use).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Access token'), 'abc')
    await userEvent.click(use)
    expect(await screen.findByText('home')).toBeInTheDocument()
  })
  it('hides the paste box where the source cannot paste', async () => {
    const source = new FakeSource(null)
    source.supportsPaste = false
    shell(source)
    await screen.findByRole('button', { name: 'Sign in' })
    expect(screen.queryByText(/Developer: paste/)).toBeNull()
  })
  it('a signed-in person is sent on', async () => {
    shell(new FakeSource())
    expect(await screen.findByText('home')).toBeInTheDocument()
  })
  it('a deep link (a scanned phone label) goes straight on to PhotonID and comes back to it, without a click', async () => {
    const source = new FakeSource(null)
    source.supportsPaste = false
    shell(source, {}, { pathname: '/login', state: { from: '/phones?add=1' } })
    await waitFor(() => expect(source.signIn).toHaveBeenCalledWith('/phones?add=1'))
    expect(source.signIn).toHaveBeenCalledTimes(1)
  })
  it('a signed-in person who came from a deep link is sent back to it', async () => {
    shell(new FakeSource(), {}, { pathname: '/login', state: { from: '/phones?add=1' } })
    expect(await screen.findByText('phones page')).toBeInTheDocument()
  })
  it('no automatic sign-in without a deep link, and never to another site', async () => {
    const source = new FakeSource(null)
    source.supportsPaste = false
    shell(source, {}, { pathname: '/login', state: { from: '//evil.example/x' } })
    await userEvent.click(await screen.findByRole('button', { name: 'Sign in' }))
    expect(source.signIn).toHaveBeenCalledTimes(1)
    expect(source.signIn).toHaveBeenCalledWith('/')
  })
  it('an error loading the session is shown on the page', async () => {
    shell(new FakeSource(), { 'GET /me': new Response(JSON.stringify({ detail: 'database down' }), { status: 500 }) })
    expect(await screen.findByText('database down')).toBeInTheDocument()
  })
})

describe('CallbackPage', () => {
  it('finishes sign-in and goes where the person was headed', async () => {
    shell(new FakeSource(), {}, '/auth/callback')
    expect(await screen.findByText('overview page')).toBeInTheDocument()
  })
  it('says when the exchange fails', async () => {
    const source = new FakeSource()
    source.handleCallback.mockRejectedValueOnce(new Error('state mismatch'))
    shell(source, {}, '/auth/callback')
    expect(await screen.findByRole('alert')).toHaveTextContent('state mismatch')
    expect(screen.getByRole('link', { name: 'Try again' })).toBeInTheDocument()
  })
  it('a rejection that is not an Error is still reported', async () => {
    const source = new FakeSource()
    source.handleCallback.mockRejectedValueOnce('nope')
    shell(source, {}, '/auth/callback')
    expect(await screen.findByRole('alert')).toHaveTextContent('nope')
  })
})

describe('pages for later steps', () => {
  const pages: [string, () => React.ReactElement, string][] = [
    ['Phones', Soon.PhonesPage, 'Step 4'],
    ['Monitor', Soon.MonitorPage, 'Step 5'], ['My phone', Soon.MyPhonePage, 'Step 3'], ['Templates', Soon.TemplatesPage, 'Step 3'], ['Alerts', Soon.AlertsPage, 'Step 5'],
    ['PhotonConsole connection', Soon.ConsolePage, 'Step 5'], ['Audit log', Soon.AuditPage, 'Step 3'], ['Instances', Soon.InstancesPage, 'Step 1'],
    ['Upstreams', Soon.UpstreamsPage, 'Step 3'], ['GDMS', Soon.GdmsPage, 'Step 4'], ['Number stock', Soon.NumberStockPage, 'Step 3'],
  ]
  it.each(pages)('%s says it is not built and when it comes', (name, Page, step) => {
    renderApp(<Page />, { routes: {} })
    return screen.findByText('Not built yet').then(() => {
      expect(screen.getByText(new RegExp(step))).toBeInTheDocument()
      expect(screen.getByRole('heading', { name })).toBeInTheDocument()
    })
  })
})

describe('shared bits', () => {
  it('a modal closes on Escape and on a click outside it, and keeps clicks inside', async () => {
    const onClose = vi.fn()
    render(<Modal title="Hello" onClose={onClose} wide><p>inside</p></Modal>)
    await userEvent.click(screen.getByText('inside'))
    expect(onClose).not.toHaveBeenCalled()
    await userEvent.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledTimes(1)
    await userEvent.click(screen.getByRole('dialog').parentElement!)
    expect(onClose).toHaveBeenCalledTimes(2)
    await userEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalledTimes(3)
  })
  it('a page title with actions keeps its heading; a tab’s title without actions is only for screen readers', () => {
    render(<><NotYet title="One" arrives="Step 9">x</NotYet><StatusBadge tone="ok">fine</StatusBadge></>)
    expect(screen.getByRole('heading', { name: 'One' })).toBeInTheDocument()
    expect(screen.getByText('fine')).toHaveClass('ph-badge-ok')
  })
})
