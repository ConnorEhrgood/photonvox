import { useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import type { PlatformOrganization } from '../api/types'
import { ErrorText, Loading, PageHeader } from '../components/ui'
import { useLoad } from '../lib/useLoad'
import { toE164 } from './Numbers'

interface Held { number: string; tenant_id: string | null; organization: string | null; carrier: string; note: string }

/** Photon's numbers and which organization each is assigned to (security review C2): a phone system may use only its organization's numbers,
 *  and only Photon staff assign them. A number goes back to the carrier only once it is assigned to nobody. */
export function NumberStockPage() {
  const { api } = useAuth()
  const numbers = useLoad(() => api.get<Held[]>('/platform/numbers'), [api])
  const orgs = useLoad(() => api.get<PlatformOrganization[]>('/platform/organizations'), [api])
  const [number, setNumber] = useState('')
  const [org, setOrg] = useState('')
  const [error, setError] = useState<string | null>(null)
  const act = async (fn: () => Promise<unknown>) => {
    setError(null)
    try { await fn(); await numbers.reload() } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
  }
  const assign = (n: string, tenant: string | null) => act(() => api.put(`/platform/numbers/${encodeURIComponent(n)}`, { tenant_id: tenant }))
  return (
    <>
      <PageHeader title="Number stock" as="h2" />
      <div className="pv-row">
        <div className="ph-field"><label htmlFor="pv-stock-number">Number</label>
          <input id="pv-stock-number" className="ph-input" inputMode="tel" value={number} onChange={(e) => setNumber(e.target.value)} /></div>
        <div className="ph-field"><label htmlFor="pv-stock-org">Assign to</label>
          <select id="pv-stock-org" className="ph-input" value={org} onChange={(e) => setOrg(e.target.value)}>
            <option value="">Photon’s stock</option>
            {(orgs.data ?? []).map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
          </select></div>
      </div>
      <div className="ph-actions"><button className="ph-btn" disabled={!number.trim()} onClick={() => void assign(toE164(number), org || null).then(() => setNumber(''))}>Save</button></div>
      <ErrorText>{error ?? numbers.error}</ErrorText>
      {numbers.loading && !numbers.data && <Loading what="numbers" />}
      {numbers.data?.length === 0 && <p className="ph-hint">No numbers yet.</p>}
      {!!numbers.data?.length && (
        <div className="ph-table-wrap">
          <table className="ph-table pv-table">
            <thead><tr><th>Number</th><th>Organization</th><th>Carrier</th><th><span className="ph-sr-only">Change</span></th></tr></thead>
            <tbody>
              {numbers.data.map((n) => (
                <tr key={n.number}>
                  <td data-label="Number" className="pv-who"><strong>{n.number}</strong></td>
                  <td data-label="Organization">{n.organization ?? 'Photon’s stock'}</td>
                  <td data-label="Carrier">{n.carrier.toUpperCase()}</td>
                  <td data-label="">{n.tenant_id
                    ? <button className="ph-btn ph-btn-secondary ph-btn-sm" aria-label={`Back to stock: ${n.number}`} onClick={() => void assign(n.number, null)}>Back to stock</button>
                    : <button className="ph-btn ph-btn-danger ph-btn-sm" aria-label={`Give ${n.number} back to the carrier`} onClick={() => void act(() => api.del(`/platform/numbers/${encodeURIComponent(n.number)}`))}>Give back</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}
