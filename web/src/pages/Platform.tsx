import { useAuth } from '../auth/AuthContext'
import type { DirectoryStatus, PlatformOrganization } from '../api/types'
import { ErrorText, Loading, StatusBadge } from '../components/ui'
import { ago } from '../lib/format'
import { useLoad } from '../lib/useLoad'

/** PhotonVox’s view of every organization entitled to it. Partners and people are managed in the PhotonID directory. */
export function PlatformOrganizationsPage() {
  const { api } = useAuth()
  const orgs = useLoad(() => api.get<PlatformOrganization[]>('/platform/organizations'), [api])
  const dir = useLoad(() => api.get<DirectoryStatus>('/platform/directory'), [api])
  return (
    <>
      <h2 className="ph-sr-only">Organizations</h2>
      {dir.data && (
        dir.data.last_error
          ? <div className="ph-banner ph-banner-error" role="alert">The directory copy could not be refreshed: {dir.data.last_error}. {dir.data.last_ok_at ? `Last good pull ${ago(dir.data.last_ok_at)}.` : 'It has never succeeded.'}</div>
          : <p className="ph-hint">Directory copy: {dir.data.last_ok_at ? `up to date ${ago(dir.data.last_ok_at)}` : 'not pulled yet'}.</p>
      )}
      <ErrorText>{orgs.error}</ErrorText>
      {orgs.loading && !orgs.data && <Loading what="organizations" />}
      {orgs.data && orgs.data.length === 0 && <div className="ph-empty"><p>No organization has PhotonVox switched on yet. Switch it on in the PhotonID directory.</p></div>}
      {orgs.data && orgs.data.length > 0 && (
        <div className="ph-table-wrap">
          <table className="ph-table pv-table">
            <thead><tr><th>Organization</th><th>Plan</th><th>Region</th><th>Also has</th><th>Status</th><th>Phone system</th></tr></thead>
            <tbody>
              {orgs.data.map((o) => (
                <tr key={o.id}>
                  <td data-label="Organization" className="pv-who"><strong>{o.name}</strong></td>
                  <td data-label="Plan">{o.plan_key || '—'}</td>
                  <td data-label="Region">{o.home_region}</td>
                  <td data-label="Also has" className="ph-hint">{(o.products ?? []).filter((k) => k !== 'vox').join(', ') || '—'}</td>
                  <td data-label="Status"><StatusBadge tone={o.status === 'active' ? 'ok' : 'warning'}>{o.status === 'active' ? 'Active' : 'Restricted'}</StatusBadge></td>
                  <td data-label="Phone system" className="ph-hint">Not set up yet</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}
