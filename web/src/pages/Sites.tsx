import { useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import { useTenant } from '../auth/TenantContext'
import type { Draft, EmergencyState, Site } from '../api/types'
import { useDraft } from '../components/draft'
import { DIRECTORY_URL } from '../components/Layout'
import { ErrorText, Loading, Modal, PageHeader, StatusBadge } from '../components/ui'
import { useLoad } from '../lib/useLoad'

const LOCATION = { pending: ['info', 'Waiting for Photon to check'], validated: ['ok', 'Validated'], rejected: ['error', 'Not valid'] } as const
const EMPTY = { street: '', unit: '', city: '', state: '', zip: '' }

/** The organization's sites, from the PhotonID directory's copy (added and edited in the directory, for every Photon product). Here each site is
 *  set up for phones: its emergency address (911, validated before the site can have phones: ARCHITECTURE §11), the number a 911 call from it
 *  shows, the number its calls show, and its office hours. */
export function SitesPage() {
  const { api } = useAuth()
  const { current, can } = useTenant()
  const base = `/tenants/${current!.id}`
  const sites = useLoad(() => api.get<Site[]>(`${base}/sites`), [api, base])
  const { draft, change, saving, error, ps } = useDraft()
  const e911 = useLoad(() => (ps.data ? api.get<EmergencyState>(`${base}/emergency`) : Promise.resolve(null)), [api, base, ps.data?.id])
  const [setup, setSetup] = useState<Site | null>(null)
  const build = !!draft && can('vox.phone_system.build')
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
            <thead><tr><th>Site</th><th>Address</th><th>Time zone</th><th>Emergency address</th><th>Phones</th><th><span className="ph-sr-only">Set up</span></th></tr></thead>
            <tbody>
              {sites.data.map((s) => {
                const inDraft = draft?.sites?.[s.id]
                const loc = e911.data?.locations.find((l) => l.site_id === s.id && (!inDraft || l.key === inDraft.emergency_location))
                const [tone, text] = loc ? LOCATION[loc.status] : (['warning', 'Not set up'] as const)
                return (
                  <tr key={s.id}>
                    <td data-label="Site" className="pv-who"><strong>{s.name}</strong><br /><small className="ph-hint">{s.slug}</small></td>
                    <td data-label="Address">{s.address || '—'}</td>
                    <td data-label="Time zone">{s.timezone} <a className="ph-hint" href={DIRECTORY_URL} target="_blank" rel="noopener noreferrer" aria-label={`Change the time zone of ${s.name}`}>Change</a></td>
                    <td data-label="Emergency address"><StatusBadge tone={tone}>{text}</StatusBadge>{loc?.note && <><br /><small className="ph-error">{loc.note}</small></>}</td>
                    <td data-label="Phones">{inDraft ? <>911 shows {inDraft.emergency_number}<br /><small className="ph-hint">calls show {inDraft.caller_id}</small></> : '—'}</td>
                    <td data-label="">{build && <button className="ph-btn ph-btn-secondary ph-btn-sm" aria-label={`Set up ${s.name} for phones`} onClick={() => setSetup(s)}>
                      {inDraft ? 'Change' : 'Set up for phones'}</button>}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          <p className="ph-hint">Sites are edited in Manage sites, for every Photon product at once. A site needs a validated emergency address before it can have phones.</p>
        </div>
      )}
      {setup && draft && (
        <SiteSetup site={setup} draft={draft} known={e911.data?.locations.find((l) => l.site_id === setup.id) ?? null} saving={saving} error={error}
          onClose={() => setSetup(null)}
          onSave={async (key, address, emergency, caller, hours) => {
            if (address) await api.post(`${base}/sites/${setup.id}/emergency-locations`, { key, ...address })
            const ok = await change((d) => ({ ...d, sites: { ...d.sites, [setup.id]: { ...d.sites?.[setup.id], emergency_location: key,
              emergency_number: emergency, caller_id: caller, hours: hours || null } } }))
            if (ok) { setSetup(null); await e911.reload() }
          }} />
      )}
    </>
  )
}

function SiteSetup({ site, draft, known, saving, error, onClose, onSave }: {
  site: Site; draft: Draft; known: { key: string } | null; saving: boolean; error: string | null; onClose: () => void
  onSave: (key: string, address: typeof EMPTY | null, emergency: string, caller: string, hours: string) => Promise<void>
}) {
  const was = draft.sites?.[site.id]
  const numbers = Object.keys(draft.numbers ?? {}).sort()
  const [address, setAddress] = useState(EMPTY)
  const [emergency, setEmergency] = useState(was?.emergency_number ?? numbers[0] ?? '')
  const [caller, setCaller] = useState(was?.caller_id ?? numbers[0] ?? '')
  const [hours, setHours] = useState(was?.hours ?? '')
  const [failed, setFailed] = useState<string | null>(null)
  const needAddress = !known
  const filled = !needAddress || (address.street && address.city && /^[A-Z]{2}$/.test(address.state) && /^[0-9]{5}$/.test(address.zip))
  const set = (k: keyof typeof EMPTY) => (e: React.ChangeEvent<HTMLInputElement>) => setAddress({ ...address, [k]: k === 'state' ? e.target.value.toUpperCase() : e.target.value })
  const save = async () => {
    setFailed(null)
    try { await onSave(known?.key ?? 'main', needAddress ? address : null, emergency, caller, hours) } catch (e) { setFailed(e instanceof Error ? e.message : String(e)) }
  }
  return (
    <Modal title={`${site.name}: phones`} onClose={onClose}>
      {needAddress ? (
        <>
          <p className="ph-hint">The address 911 calls from {site.name} are sent to. Photon checks it before the site can have phones.</p>
          <div className="pv-row">
            <div className="ph-field"><label htmlFor="pv-s-street">Street</label><input id="pv-s-street" className="ph-input" value={address.street} onChange={set('street')} /></div>
            <div className="ph-field"><label htmlFor="pv-s-unit">Suite or floor</label><input id="pv-s-unit" className="ph-input" value={address.unit} onChange={set('unit')} /></div>
          </div>
          <div className="pv-row">
            <div className="ph-field"><label htmlFor="pv-s-city">City</label><input id="pv-s-city" className="ph-input" value={address.city} onChange={set('city')} /></div>
            <div className="ph-field"><label htmlFor="pv-s-state">State</label><input id="pv-s-state" className="ph-input" maxLength={2} value={address.state} onChange={set('state')} /></div>
            <div className="ph-field"><label htmlFor="pv-s-zip">ZIP code</label><input id="pv-s-zip" className="ph-input" value={address.zip} onChange={set('zip')} /></div>
          </div>
        </>
      ) : <p className="ph-hint">Its emergency address is set (Overview shows whether Photon has validated it).</p>}
      {numbers.length === 0 ? <p className="ph-error">Add the site’s numbers first (Numbers): 911 calls must show one of them.</p> : (
        <div className="pv-row">
          <div className="ph-field"><label htmlFor="pv-s-911">A 911 call from here shows</label>
            <select id="pv-s-911" className="ph-input" value={emergency} onChange={(e) => setEmergency(e.target.value)}>{numbers.map((n) => <option key={n}>{n}</option>)}</select></div>
          <div className="ph-field"><label htmlFor="pv-s-cid">Other calls show</label>
            <select id="pv-s-cid" className="ph-input" value={caller} onChange={(e) => setCaller(e.target.value)}>{numbers.map((n) => <option key={n}>{n}</option>)}</select></div>
        </div>
      )}
      <div className="ph-field"><label htmlFor="pv-s-hours">Office hours</label>
        <select id="pv-s-hours" className="ph-input" value={hours} onChange={(e) => setHours(e.target.value)}>
          <option value="">none</option>{Object.keys(draft.hours ?? {}).map((h) => <option key={h}>{h}</option>)}
        </select></div>
      <ErrorText>{failed ?? error}</ErrorText>
      <div className="ph-modal-footer"><button className="ph-btn" disabled={saving || !filled || !emergency} onClick={() => void save()}>Save</button></div>
    </Modal>
  )
}
