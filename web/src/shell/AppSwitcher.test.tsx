// GENERATED from @photon/ui by scripts/sync-vendored.mjs. Do not edit here: change photon-ui, then re-run it.
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { AppSwitcher, loadApps, type SwitcherData } from './AppSwitcher'

const DATA: SwitcherData = {
  home: 'https://account.photonind.com/',
  organization: { id: 'o1', slug: 'huepc', name: 'HUEPC' },
  site: { id: 's1', slug: 'main-office', name: 'Main Office' },
  apps: [
    { key: 'board', name: 'PhotonBoard', state: 'not_enabled' },
    { key: 'console', name: 'PhotonConsole', state: 'open', url: 'https://console.photonind.com/org/huepc/site/main-office/' },
    { key: 'guard', name: 'PhotonGuard', state: 'no_access' },
    { key: 'vox', name: 'PhotonVox', state: 'open', url: 'https://vox.photonind.com/org/huepc/site/main-office/' },
    { key: 'entry', name: 'PhotonEntry', state: 'coming' },
  ],
}

function Harness({ load, current = 'vox', start = false }: { load: () => Promise<SwitcherData>; current?: string; start?: boolean }) {
  const [open, setOpen] = useState(start)
  return <div><AppSwitcher current={current} load={load} open={open} onOpenChange={setOpen} /><p>outside</p></div>
}

describe('AppSwitcher', () => {
  it('lists every product for this organization and site: open ones link there, the rest say why, Home first', async () => {
    const load = vi.fn(async () => DATA)
    render(<Harness load={load} />)
    expect(load).not.toHaveBeenCalled()                           // nothing is asked until it is opened
    await userEvent.click(screen.getByRole('button', { name: 'Switch app' }))
    expect(await screen.findByText('In HUEPC · Main Office')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Home/ })).toHaveAttribute('href', 'https://account.photonind.com/')
    expect(screen.getByRole('link', { name: 'PhotonConsole' })).toHaveAttribute('href', 'https://console.photonind.com/org/huepc/site/main-office/')
    expect(screen.queryByRole('link', { name: /PhotonGuard/ })).toBeNull()
    expect(screen.getByText('No access')).toBeInTheDocument()
    expect(screen.getByText('Not on for this customer')).toBeInTheDocument()
    expect(screen.getByText('Coming')).toBeInTheDocument()
    expect(screen.getByText('You are here')).toBeInTheDocument()          // PhotonVox, the current product, is not a link
    expect(screen.queryByRole('link', { name: /PhotonVox/ })).toBeNull()
    expect(screen.getByRole('button', { name: 'Switch app' })).toHaveAttribute('aria-expanded', 'true')
  })

  it('without a site it names the organization only', async () => {
    render(<Harness load={async () => ({ ...DATA, site: null })} start />)
    expect(await screen.findByText('In HUEPC')).toBeInTheDocument()
  })

  it('filters as you type, says when nothing matches, and moves with the arrows', async () => {
    render(<Harness load={async () => DATA} start />)
    await screen.findByText('In HUEPC · Main Office')
    const box = screen.getByRole('textbox', { name: 'Find an app' })
    expect(box).toHaveFocus()
    await userEvent.type(box, 'cons')
    expect(screen.getByRole('link', { name: 'PhotonConsole' })).toBeInTheDocument()
    expect(screen.queryByText('PhotonBoard')).toBeNull()
    await userEvent.keyboard('{ArrowDown}')
    expect(screen.getByRole('link', { name: /Home/ })).toHaveFocus()
    await userEvent.keyboard('{ArrowDown}')
    expect(screen.getByRole('link', { name: 'PhotonConsole' })).toHaveFocus()
    await userEvent.keyboard('{ArrowDown}')
    expect(screen.getByRole('link', { name: /Home/ })).toHaveFocus()          // wraps
    await userEvent.keyboard('{ArrowUp}')
    expect(screen.getByRole('link', { name: 'PhotonConsole' })).toHaveFocus()
    box.focus()
    await userEvent.keyboard('{ArrowUp}')
    expect(screen.getByRole('link', { name: 'PhotonConsole' })).toHaveFocus()
    await userEvent.clear(box)
    await userEvent.type(box, 'zzz')
    expect(screen.getByText('No app matches “zzz”.')).toBeInTheDocument()
  })

  it('Esc closes and gives the focus back; a click outside closes', async () => {
    render(<Harness load={async () => DATA} />)
    const btn = screen.getByRole('button', { name: 'Switch app' })
    await userEvent.click(btn)
    await screen.findByText('In HUEPC · Main Office')
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(btn).toHaveFocus()
    await userEvent.click(btn)
    await userEvent.click(screen.getByText('outside'))
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('says when the list cannot be loaded, and Home still goes to the dashboard', async () => {
    render(<Harness load={async () => { throw new Error('directory away') }} start />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Couldn’t load your apps')
    expect(screen.getByRole('link', { name: /Home/ })).toHaveAttribute('href', 'https://account.photonind.com/')
  })

  it('shows that it is loading, and asks again only when the place changes', async () => {
    let resolve!: (d: SwitcherData) => void
    const load = vi.fn(() => new Promise<SwitcherData>((r) => { resolve = r }))
    const { rerender } = render(<Harness load={load} start />)
    expect(screen.getByRole('status')).toHaveTextContent('Loading your apps')
    await act(async () => resolve(DATA))
    await screen.findByText('In HUEPC · Main Office')
    rerender(<Harness load={load} start />)
    expect(load).toHaveBeenCalledTimes(1)
    const other = vi.fn(async () => ({ ...DATA, organization: { ...DATA.organization, name: 'Other' }, site: null }))
    rerender(<Harness load={other} start />)
    expect(await screen.findByText('In Other')).toBeInTheDocument()
  })

  it('ignores an answer that arrives after it was closed', async () => {
    let resolve!: (d: SwitcherData) => void
    const { unmount } = render(<Harness load={() => new Promise<SwitcherData>((r) => { resolve = r })} start />)
    unmount()
    await act(async () => resolve(DATA))
  })
})

describe('loadApps', () => {
  it('asks the directory with the token, the organization and the site', async () => {
    const f = vi.fn(async () => new Response(JSON.stringify(DATA), { status: 200 }))
    expect(await loadApps('https://api.account.test/', 'tok', 'huepc', 'main-office', f as unknown as typeof fetch)).toEqual(DATA)
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('https://api.account.test/v1/me/apps?organization=huepc&site=main-office')
    expect(init.headers).toEqual({ Authorization: 'Bearer tok' })
  })

  it('without a site or a token it asks for the organization only', async () => {
    const f = vi.fn(async () => new Response(JSON.stringify(DATA), { status: 200 }))
    await loadApps('https://api.account.test', null, 'huepc', null, f as unknown as typeof fetch)
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('https://api.account.test/v1/me/apps?organization=huepc')
    expect(init.headers).toEqual({})
  })

  it('a refusal is an error, and a slow directory is given up after the timeout', async () => {
    const refuse = vi.fn(async () => new Response('{}', { status: 404 }))
    await expect(loadApps('https://a', 't', 'x', null, refuse as unknown as typeof fetch)).rejects.toThrow('404')
    const hang = vi.fn((_u: string, init: RequestInit) => new Promise<Response>((_r, reject) => init.signal?.addEventListener('abort', () => reject(new Error('aborted')))))
    await expect(loadApps('https://a', 't', 'x', null, hang as unknown as typeof fetch, 10)).rejects.toThrow('aborted')
  })

  it('uses the browser fetch by default', async () => {
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(DATA), { status: 200 }))
    await loadApps('https://a', 't', 'x')
    expect(spy).toHaveBeenCalled()
    spy.mockRestore()
  })
})

