import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { EntryToken } from '../api/types'
import { meWith, OWNER, renderApp, TECH_A, USER } from '../test/helpers'
import { EntryPage } from './Entry'
import { settingsTabs } from './Hubs'

const B = '/tenants/t1/integrations/entry-tokens'
const T = (over: Partial<EntryToken> = {}): EntryToken => ({ id: 'k1', label: 'PhotonEntry', scope: 'vox:entry', hint: 'Zx9q', created_at: '2026-11-14T15:00:00Z',
  revoked_at: null, last_used_at: null, ...over })

describe('the PhotonEntry connection', () => {
  it('is a Settings tab for admins and owners, not users', () => {
    const can = (caps: string[]) => (c: string) => caps.includes(c)
    expect(settingsTabs(can(OWNER.capabilities)).map((t) => t.to)).toContain('entry')
    expect(settingsTabs(can(TECH_A.capabilities)).map((t) => t.to)).toContain('entry')
    expect(settingsTabs(can(USER.capabilities)).map((t) => t.to)).not.toContain('entry')
  })

  it('makes a token, shows it once, and revokes one', async () => {
    let tokens: EntryToken[] = [T({ id: 'old', hint: 'Ab12', last_used_at: '2026-11-14T15:05:00Z' })]
    const deleted: string[] = []
    const routes = {
      [`GET ${B}`]: () => tokens,
      [`POST ${B}`]: () => { const t = T({ id: 'new', hint: 'Zx9q', token: 'pvx_entry_secretsecretZx9q' }); tokens = [...tokens, { ...t, token: undefined }]; return t },
      [`DELETE ${B}/old`]: () => { deleted.push('old'); tokens = tokens.map((t) => (t.id === 'old' ? { ...t, revoked_at: '2026-11-14T16:00:00Z' } : t)); return null },
    }
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    renderApp(<EntryPage />, { me: meWith(OWNER), routes })
    expect(await screen.findByText(/…Ab12/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Make another token' }))
    expect(await screen.findByText('pvx_entry_secretsecretZx9q')).toBeInTheDocument()
    expect(screen.getByText(/cannot show it again/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Done' }))
    expect(screen.queryByText('pvx_entry_secretsecretZx9q')).toBeNull()
    await userEvent.click(screen.getAllByRole('button', { name: 'Revoke' })[0])
    expect(deleted).toEqual(['old'])
    expect(await screen.findByRole('button', { name: 'Make another token' })).toBeInTheDocument()
    expect(screen.queryByText(/…Ab12/)).toBeNull()
  })

  it('says when it is not connected, and keeps a token when revoking is cancelled', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    renderApp(<EntryPage />, { me: meWith(OWNER), routes: { [`GET ${B}`]: [T({ revoked_at: '2026-11-14T16:00:00Z' })] } })
    expect(await screen.findByText('Not connected.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Make a token' })).toBeEnabled()
  })
})
