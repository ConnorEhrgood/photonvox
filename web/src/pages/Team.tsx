import { useAuth } from '../auth/AuthContext'
import { useTenant } from '../auth/TenantContext'
import { ROLE_LABEL, scopeText, type Member, type Site } from '../api/types'
import { DIRECTORY_URL } from '../components/Layout'
import { ErrorText, Loading, PageHeader, StatusBadge } from '../components/ui'
import { useLoad } from '../lib/useLoad'
import { NotForYou } from './Hubs'

/** PhotonVox’s view of the people the PhotonID directory says may sign in here. They are invited, given roles and removed in the directory.
 *  People who only have a phone are PhotonVox’s own users (the Users page), and need no PhotonID account. */
export function TeamPage() {
  const { api } = useAuth()
  const { current, can } = useTenant()
  const tid = current!.id
  const allowed = can('vox.members.view')
  const members = useLoad(() => (allowed ? api.get<Member[]>(`/tenants/${tid}/members`) : Promise.resolve([])), [api, tid, allowed])
  const sites = useLoad(() => api.get<Site[]>(`/tenants/${tid}/sites`), [api, tid])
  if (!allowed) return <NotForYou />
  const names = Object.fromEntries((sites.data ?? []).map((s) => [s.id, s.name]))

  return (
    <>
      <PageHeader title="Team" as="h2">
        <a className="ph-btn ph-btn-secondary" href={DIRECTORY_URL} target="_blank" rel="noopener noreferrer">Manage organization</a>
      </PageHeader>
      <p className="ph-hint">The people who can sign in to PhotonVox for {current!.name}. Invitations and roles are managed in Manage organization.</p>
      <ErrorText>{members.error}</ErrorText>
      {members.loading && !members.data && <Loading what="the team" />}
      {members.data && members.data.length > 0 && (
        <div className="ph-table-wrap">
          <table className="ph-table pv-table">
            <thead><tr><th>Person</th><th>Role</th><th>Where</th><th>State</th></tr></thead>
            <tbody>
              {members.data.map((m) => (
                <tr key={m.person_id}>
                  <td data-label="Person" className="pv-who"><strong>{m.name || m.email}</strong>{m.name && m.email && <><br /><small className="ph-hint">{m.email}</small></>}</td>
                  <td data-label="Role">{ROLE_LABEL[m.role]}{m.source === 'partner' ? ' (partner)' : ''}</td>
                  <td data-label="Where">{scopeText(m.scope, names)}</td>
                  <td data-label="State">{m.pending ? <StatusBadge tone="info">Invited</StatusBadge> : <StatusBadge tone="ok">Active</StatusBadge>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}
