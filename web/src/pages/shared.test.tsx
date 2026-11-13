import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Modal, NotYet, StatusBadge } from '../components/ui'
import { renderApp } from '../test/helpers'
import * as Soon from './Soon'

describe('pages for later steps', () => {
  const pages: [string, () => React.ReactElement, string][] = [
    ['Phones', Soon.PhonesPage, 'Step 4'],
    ['Monitor', Soon.MonitorPage, 'Step 5'], ['My phone', Soon.MyPhonePage, 'Step 3'], ['Templates', Soon.TemplatesPage, 'Step 3'], ['Alerts', Soon.AlertsPage, 'Step 5'],
    ['PhotonConsole connection', Soon.ConsolePage, 'Step 5'], ['Audit log', Soon.AuditPage, 'Step 3'], ['Instances', Soon.InstancesPage, 'Step 1'],
    ['Upstreams', Soon.UpstreamsPage, 'Step 3'], ['GDMS', Soon.GdmsPage, 'Step 4'],
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
