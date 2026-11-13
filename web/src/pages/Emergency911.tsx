import { useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import type { CarrierRequestRow, EmergencyAddress, PendingLocation } from '../api/types'
import { ErrorText, Loading, PageHeader, StatusBadge } from '../components/ui'
import { ago } from '../lib/format'
import { useLoad } from '../lib/useLoad'

const line = (a: EmergencyAddress) => `${a.street}${a.unit ? `, ${a.unit}` : ''}, ${a.city}, ${a.state} ${a.zip}`

/** Photon staff's 911 work (ARCHITECTURE §11, §11a): addresses to check against the 911 database, and the carrier's records to keep in step
 *  (decision 31: Hickory is told by email, or by a ticket staff note here, and its answer is recorded here; numbers stay unconfirmed until then). */
export function Emergency911Page() {
  const { api } = useAuth()
  const locations = useLoad(() => api.get<PendingLocation[]>('/platform/emergency-locations'), [api])
  const requests = useLoad(() => api.get<CarrierRequestRow[]>('/platform/carrier-requests'), [api])
  const [error, setError] = useState<string | null>(null)
  const [notes, setNotes] = useState<Record<string, string>>({})
  const act = async (fn: () => Promise<unknown>) => {
    setError(null)
    try { await fn(); await locations.reload(); await requests.reload() } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
  }
  const note = (id: string) => notes[id] ?? ''
  return (
    <>
      <PageHeader title="911" as="h2" />
      <ErrorText>{error ?? locations.error ?? requests.error}</ErrorText>
      <h3>Addresses to check</h3>
      {locations.loading && !locations.data && <Loading what="addresses" />}
      {locations.data?.length === 0 && <p className="ph-hint">None waiting.</p>}
      {locations.data?.map((l) => (
        <div key={l.id} className="ph-card">
          <p><strong>{l.organization}</strong>: {line(l.address)}</p>
          <div className="ph-actions">
            <button className="ph-btn ph-btn-sm" onClick={() => void act(() => api.post(`/platform/emergency-locations/${l.id}/validate`, { ok: true }))}>Valid</button>
            <button className="ph-btn ph-btn-secondary ph-btn-sm" onClick={() => void act(() => api.post(`/platform/emergency-locations/${l.id}/validate`, { ok: false, note: note(l.id) }))}>Not valid</button>
            <input className="ph-input" aria-label={`Note on ${line(l.address)}`} placeholder="Why not (for the customer)" value={note(l.id)}
              onChange={(e) => setNotes({ ...notes, [l.id]: e.target.value })} />
          </div>
        </div>
      ))}
      <h3>Requests to carriers</h3>
      {requests.data?.length === 0 && <p className="ph-hint">Nothing waiting for a carrier.</p>}
      {requests.data?.map((r) => (
        <div key={r.id} className="ph-card">
          <p><strong>{r.organization}</strong> <StatusBadge tone={r.status === 'sent' ? 'info' : 'warning'}>{r.status === 'sent' ? `Sent ${r.sent_at ? ago(r.sent_at) : ''}` : 'Not sent yet'}</StatusBadge>
            {r.reference && <span className="ph-hint"> {r.reference}</span>}</p>
          <ul>{r.items.map((i) => <li key={i.number}>{i.action} {i.number}{i.address ? `: ${line(i.address)}` : ''}</li>)}</ul>
          <details><summary>The email to {r.carrier.toUpperCase()}</summary><p><strong>{r.email.subject}</strong></p><pre>{r.email.body}</pre></details>
          <div className="ph-actions">
            <input className="ph-input" aria-label={`Ticket or note for ${r.organization}`} placeholder="Ticket number or note" value={note(r.id)}
              onChange={(e) => setNotes({ ...notes, [r.id]: e.target.value })} />
            {r.status === 'open' && <button className="ph-btn ph-btn-secondary ph-btn-sm" onClick={() => void act(() => api.post(`/platform/carrier-requests/${r.id}/sent`, { ok: true, reference: note(r.id) }))}>Sent by hand</button>}
            <button className="ph-btn ph-btn-sm" onClick={() => void act(() => api.post(`/platform/carrier-requests/${r.id}/close`, { ok: true, note: note(r.id) }))}>Carrier confirmed</button>
            <button className="ph-btn ph-btn-danger ph-btn-sm" onClick={() => void act(() => api.post(`/platform/carrier-requests/${r.id}/close`, { ok: false, note: note(r.id) }))}>Carrier rejected</button>
          </div>
        </div>
      ))}
    </>
  )
}
