import { useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import { useTenant } from '../auth/TenantContext'
import { ApiError } from '../api/client'
import type { ImportRow, PhoneSystemSummary, Site } from '../api/types'
import { ErrorText, Loading, Modal, PageHeader } from '../components/ui'
import { useLoad } from '../lib/useLoad'
import { ImportReview } from './Setup'

/** The phone system's people (the draft: what the next publish will put on the phones), and bulk import into it. */
export function UsersPage() {
  const { api } = useAuth()
  const { current, can } = useTenant()
  const base = `/tenants/${current!.id}`
  const ps = useLoad(async () => {
    try { return await api.get<PhoneSystemSummary>(`${base}/phone-system`) } catch (e) {
      if (e instanceof ApiError && e.data?.code === 'no_phone_system') return null
      throw e
    }
  }, [api, base])
  const sites = useLoad(() => api.get<Site[]>(`${base}/sites`), [api, base])
  const [importing, setImporting] = useState(false)
  const siteName = Object.fromEntries((sites.data ?? []).map((s) => [s.id, s.name]))
  const users = Object.entries(ps.data?.draft.users ?? {}).sort((a, b) => a[1].extension.localeCompare(b[1].extension, undefined, { numeric: true }))
  return (
    <>
      <PageHeader title="Users">
        {ps.data && can('vox.phone_system.build') && <button className="ph-btn" onClick={() => setImporting(true)}>Import users</button>}
      </PageHeader>
      <ErrorText>{ps.error}</ErrorText>
      {ps.loading && !ps.data && <Loading what="users" />}
      {!ps.loading && ps.data === null && <div className="ph-empty"><p>This customer has no phone system yet. Set it up from the Overview.</p></div>}
      {ps.data && users.length === 0 && <div className="ph-empty"><p>No users yet. Import them by pasting rows from a spreadsheet.</p></div>}
      {users.length > 0 && (
        <div className="ph-table-wrap">
          <table className="ph-table pv-table">
            <thead><tr><th>Name</th><th>Extension</th><th>Site</th><th>Email</th><th>Shows</th></tr></thead>
            <tbody>
              {users.map(([id, u]) => (
                <tr key={id}>
                  <td data-label="Name" className="pv-who"><strong>{u.name}</strong></td>
                  <td data-label="Extension">{u.extension}</td>
                  <td data-label="Site">{siteName[u.site] ?? '—'}</td>
                  <td data-label="Email">{u.email ?? ''}</td>
                  <td data-label="Shows">{u.show === 'direct' && u.direct_number ? u.direct_number : 'the site’s number'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="ph-hint">Changes here reach the phones when the phone system is published (Overview).</p>
        </div>
      )}
      {importing && ps.data && (
        <ImportModal groups={Object.keys(ps.data.draft.groups ?? {})} sites={sites.data ?? []} onClose={() => setImporting(false)}
          onDone={async () => { setImporting(false); await ps.reload() }} />
      )}
    </>
  )
}

function ImportModal({ groups, sites, onClose, onDone }: { groups: string[]; sites: Site[]; onClose: () => void; onDone: () => Promise<void> }) {
  const { api } = useAuth()
  const { current } = useTenant()
  const [text, setText] = useState('')
  const [site, setSite] = useState(sites[0]?.id ?? '')
  const [group, setGroup] = useState(groups.includes('everyone') ? 'everyone' : '')
  const [rows, setRows] = useState<ImportRow[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const call = (apply: boolean) => api.post<{ rows: ImportRow[]; ready: number }>(`/tenants/${current!.id}/phone-system/import`,
    { text, site_id: site, group: group || null, apply })
  const run = async (fn: () => Promise<void>) => {
    setBusy(true); setError(null)
    try { await fn() } catch (e) { setError(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) }
  }
  const good = rows?.filter((r) => !r.problems.length).length ?? 0
  return (
    <Modal title="Import users" onClose={onClose} wide>
      <div className="ph-field">
        <label htmlFor="pv-import">One per line: name, extension, email, direct number, site</label>
        <textarea id="pv-import" className="ph-input pv-paste" value={text} onChange={(e) => { setText(e.target.value); setRows(null) }} />
      </div>
      <div className="pv-row">
        <div className="ph-field">
          <label htmlFor="pv-import-site">Site, when a row names none</label>
          <select id="pv-import-site" className="ph-input" value={site} onChange={(e) => setSite(e.target.value)}>
            {sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </div>
        {groups.length > 0 && (
          <div className="ph-field">
            <label htmlFor="pv-import-group">Also add them to</label>
            <select id="pv-import-group" className="ph-input" value={group} onChange={(e) => setGroup(e.target.value)}>
              <option value="">no ring group</option>
              {groups.map((g) => <option key={g} value={g}>{g}</option>)}
            </select>
          </div>
        )}
      </div>
      {rows && <ImportReview rows={rows} />}
      <ErrorText>{error}</ErrorText>
      <div className="ph-modal-footer">
        <button className="ph-btn ph-btn-secondary" disabled={busy || !text.trim() || !site} onClick={() => void run(async () => setRows((await call(false)).rows))}>Check</button>
        <button className="ph-btn" disabled={busy || good === 0} onClick={() => void run(async () => { await call(true); await onDone() })}>Add {good} {good === 1 ? 'user' : 'users'}</button>
      </div>
    </Modal>
  )
}
