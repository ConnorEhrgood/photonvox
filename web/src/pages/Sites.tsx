import { useAuth } from '../auth/AuthContext'
import { useTenant } from '../auth/TenantContext'
import type { Site } from '../api/types'
import { DIRECTORY_URL } from '../components/Layout'
import { ErrorText, Loading, PageHeader, StatusBadge } from '../components/ui'
import { useLoad } from '../lib/useLoad'

/** The organization's sites, from the PhotonID directory's copy. Sites are shared by every Photon product and are added and edited in the directory.
 *  Each site's emergency address (911) is PhotonVox's own, validated before the site can have phones (ARCHITECTURE §11): it arrives with the builder. */
export function SitesPage() {
  const { api } = useAuth()
  const { current } = useTenant()
  const sites = useLoad(() => api.get<Site[]>(`/tenants/${current!.id}/sites`), [api, current?.id])
  return (
    <>
      <PageHeader title="Sites">
        <a className="ph-btn ph-btn-secondary" href={DIRECTORY_URL} target="_blank" rel="noopener noreferrer">Manage sites</a>
      </PageHeader>
      <ErrorText>{sites.error}</ErrorText>
      {sites.loading && !sites.data && <Loading what="sites" />}
      {sites.data && sites.data.length === 0 && (
        <div className="ph-empty"><p>No sites yet. Sites are added in <a href={DIRECTORY_URL} target="_blank" rel="noopener noreferrer">Manage organization</a> and appear here by themselves.</p></div>
      )}
      {sites.data && sites.data.length > 0 && (
        <div className="ph-table-wrap">
          <table className="ph-table pv-table">
            <thead><tr><th>Site</th><th>Address</th><th>Time zone</th><th>Emergency address</th></tr></thead>
            <tbody>
              {sites.data.map((s) => (
                <tr key={s.id}>
                  <td data-label="Site" className="pv-who"><strong>{s.name}</strong><br /><small className="ph-hint">{s.slug}</small></td>
                  <td data-label="Address">{s.address || '—'}</td>
                  <td data-label="Time zone">{s.timezone} <a className="ph-hint" href={DIRECTORY_URL} target="_blank" rel="noopener noreferrer" aria-label={`Change the time zone of ${s.name}`}>Change</a></td>
                  <td data-label="Emergency address"><StatusBadge tone="warning">Not set up</StatusBadge></td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="ph-hint">Sites are edited in Manage sites, for every Photon product at once. A site needs a validated emergency address before it can have phones.</p>
        </div>
      )}
    </>
  )
}
