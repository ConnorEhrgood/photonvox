import { useNavigate } from 'react-router-dom'
import { orgPath, useTenant } from '../auth/TenantContext'
import { ROLE_LABEL } from '../api/types'
import { PageHeader, StatusBadge } from '../components/ui'

/** The integrator's home: every customer they work on. Opening one makes it the current organization and goes to its overview. Phone-system
 *  state and problems per customer join this list with the monitoring pane (Step 5). */
export function CustomersPage() {
  const { tenants } = useTenant()
  const nav = useNavigate()
  const open = (t: (typeof tenants)[number]) => nav(orgPath(t) + '/')
  return (
    <>
      <PageHeader title="Customers" />
      <div className="ph-table-wrap">
        <table className="ph-table pv-table">
          <thead><tr><th>Customer</th><th>Your access</th><th>Phone system</th><th>Status</th><th><span className="ph-sr-only">Open</span></th></tr></thead>
          <tbody>
            {tenants.map((t) => (
              <tr key={t.id}>
                <td data-label="Customer" className="pv-who"><strong>{t.name}</strong></td>
                <td data-label="Your access">{ROLE_LABEL[t.role]}{t.source === 'partner' ? ' (partner)' : ''}</td>
                <td data-label="Phone system" className="ph-hint">Not set up yet</td>
                <td data-label="Status"><StatusBadge tone={t.status === 'active' ? 'ok' : 'warning'}>{t.status === 'active' ? 'Active' : 'Restricted'}</StatusBadge></td>
                <td data-label=""><button className="ph-btn ph-btn-secondary ph-btn-sm" onClick={() => open(t)}>Open {t.name}</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="ph-hint">New customers are created in Manage organization, with PhotonVox switched on. They appear here by themselves.</p>
    </>
  )
}
