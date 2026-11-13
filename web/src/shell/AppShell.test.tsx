// GENERATED from @photon/ui by scripts/sync-vendored.mjs. Do not edit here: change photon-ui, then re-run it.
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { AppShell, type AppShellProps } from './AppShell'

const base: Omit<AppShellProps, 'children'> = {
  product: 'Demo',
  home: '/',
  groups: [
    { items: [{ to: '/', label: 'Overview', icon: 'overview', end: true }, { to: '/screens', label: 'Screens', icon: 'screens', badge: <b>3</b> }] },
    { label: 'Creative', items: [{ to: '/content', label: 'Content', icon: 'content' }] },
    { label: 'Empty', items: [] },
  ],
  footer: [{ to: '/settings', label: 'Settings', icon: 'settings' }],
  account: { name: 'Ada Lovelace', detail: 'ada@example.com', actions: [{ label: 'Other view', to: '/other' }, { label: 'Sign out', onClick: vi.fn() }] },
}

function renderShell(props: Partial<AppShellProps> = {}, route = '/') {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <AppShell {...base} {...props}><p>page body</p></AppShell>
      <Routes><Route path="*" element={null} /></Routes>
    </MemoryRouter>,
  )
}

describe('AppShell', () => {
  it('shows the product, grouped navigation, settings, and the page', () => {
    renderShell({ switcher: <span>org picker</span>, status: <span>2 alerts</span>, banner: <p>billing notice</p> })
    expect(screen.getAllByRole('link', { name: 'Demo' })[0]).toHaveAttribute('href', '/')
    const main = screen.getByRole('navigation', { name: 'Main' })
    expect(within(main).getAllByRole('link').map((l) => l.textContent)).toEqual(['Overview', 'Screens3', 'Content'])
    expect(within(main).getByText('Creative')).toBeInTheDocument()
    expect(within(main).queryByText('Empty')).toBeNull()
    expect(within(screen.getByRole('navigation', { name: 'Settings and administration' })).getByRole('link', { name: 'Settings' })).toHaveAttribute('href', '/settings')
    for (const t of ['org picker', '2 alerts', 'billing notice', 'page body']) expect(screen.getByText(t)).toBeInTheDocument()
    expect(screen.getByRole('main')).toHaveTextContent('page body')
  })

  it('marks the current page, and only that one', () => {
    renderShell({}, '/content')
    expect(screen.getByRole('link', { name: 'Content' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('link', { name: 'Overview' })).not.toHaveAttribute('aria-current')
  })

  it('leaves out the footer, switcher, status and banner when there are none', () => {
    renderShell({ footer: undefined })
    expect(screen.queryByRole('navigation', { name: 'Settings and administration' })).toBeNull()
  })

  it('opens the account menu, follows a link, and runs an action', async () => {
    const user = userEvent.setup()
    const signOut = vi.fn()
    renderShell({ account: { ...base.account, actions: [{ label: 'Other view', to: '/other' }, { label: 'Sign out', onClick: signOut }] } })
    expect(screen.queryByRole('menu')).toBeNull()
    expect(screen.getByText('A')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Ada Lovelace/ }))
    expect(screen.getByRole('button', { name: /Ada Lovelace/ })).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('menuitem', { name: 'Other view' })).toHaveAttribute('href', '/other')
    await user.click(screen.getByRole('menuitem', { name: 'Sign out' }))
    expect(signOut).toHaveBeenCalledOnce()
    expect(screen.queryByRole('menu')).toBeNull()
    await user.click(screen.getByRole('button', { name: /Ada Lovelace/ }))
    await user.click(screen.getByRole('menuitem', { name: 'Other view' }))
    expect(screen.queryByRole('menu')).toBeNull()
  })

  it('closes the account menu with Escape or a click elsewhere, and copes with a missing action handler and name', async () => {
    const user = userEvent.setup()
    const { container } = renderShell({ account: { name: ' ', actions: [{ label: 'Nothing' }] } })
    expect(screen.getByText('?')).toBeInTheDocument()
    const open = () => user.click(container.querySelector('.ph-account-btn')!)
    await open()
    await user.click(screen.getByRole('menuitem', { name: 'Nothing' }))
    expect(screen.queryByRole('menu')).toBeNull()
    await open()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('menu')).toBeNull()
    await open()
    await user.click(screen.getByText('page body'))
    expect(screen.queryByRole('menu')).toBeNull()
    await open()
    await user.click(screen.getByRole('menu'))
    expect(screen.getByRole('menu')).toBeInTheDocument()
  })

  it('opens and closes the phone drawer from the menu button, the scrim, Escape and navigation', async () => {
    const user = userEvent.setup()
    const { container } = renderShell()
    const sidebar = container.querySelector('#ph-sidebar')!
    const button = () => screen.getByRole('button', { name: /menu/i })
    expect(sidebar).not.toHaveAttribute('data-open')
    expect(button()).toHaveAccessibleName('Open menu')
    await user.click(button())
    expect(sidebar).toHaveAttribute('data-open')
    expect(button()).toHaveAccessibleName('Close menu')
    await user.click(button())
    expect(sidebar).not.toHaveAttribute('data-open')
    await user.click(button())
    await user.click(container.querySelector('.ph-scrim')!)
    expect(sidebar).not.toHaveAttribute('data-open')
    await user.click(button())
    await user.keyboard('{Escape}')
    expect(sidebar).not.toHaveAttribute('data-open')
    await user.click(button())
    await user.click(screen.getByRole('link', { name: 'Content' }))
    expect(sidebar).not.toHaveAttribute('data-open')
  })
})
