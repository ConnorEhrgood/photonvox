import { useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import { useTenant } from '../auth/TenantContext'
import type { EmergencyState, ImportRow, Site, Template } from '../api/types'
import { ErrorText, Loading, Modal } from '../components/ui'
import { useLoad } from '../lib/useLoad'

const STEPS = ['Site and 911 address', 'Main number and template', 'People']
const EMPTY = { street: '', unit: '', city: '', state: '', zip: '' }

/** The new-customer wizard (ARCHITECTURE §3): a site and its emergency address, the main number and a template, then the people, pasted from a
 *  spreadsheet and reviewed row by row. It replaces the draft; nothing reaches the phones until someone presses Publish. */
export function SetupWizard({ onClose, onDone }: { onClose: () => void; onDone: () => Promise<void> }) {
  const { api } = useAuth()
  const { current } = useTenant()
  const base = `/tenants/${current!.id}`
  const sites = useLoad(() => api.get<Site[]>(`${base}/sites`), [api, base])
  const templates = useLoad(() => api.get<Template[]>(`${base}/phone-system/templates`), [api, base])
  const [step, setStep] = useState(0)
  const [site, setSite] = useState('')
  const [address, setAddress] = useState(EMPTY)
  const [location, setLocation] = useState('')
  const [number, setNumber] = useState('')
  const [template, setTemplate] = useState('ring-everyone')
  const [people, setPeople] = useState('')
  const [rows, setRows] = useState<ImportRow[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = async (fn: () => Promise<void>) => {
    setBusy(true); setError(null)
    try { await fn() } catch (e) { setError(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) }
  }
  const chosen = site || sites.data?.[0]?.id || ''

  const saveAddress = () => run(async () => {
    // A site that already has an emergency address keeps it: the wizard uses it rather than adding a second.
    const known = (await api.get<EmergencyState>(`${base}/emergency`)).locations.find((l) => l.site_id === chosen)
    if (known) { setLocation(known.key); setStep(1); return }
    await api.post(`${base}/sites/${chosen}/emergency-locations`, { key: 'main', ...address })
    setLocation('main'); setStep(1)
  })
  const review = () => run(async () => {
    const r = await api.post<{ rows: ImportRow[] }>(`${base}/phone-system/import`, { text: people, site_id: chosen })
    setRows(r.rows)
  })
  const finish = () => run(async () => {
    await api.post(`${base}/phone-system/draft/template`, { template, site_id: chosen, location, main_number: number, users: people })
    await onDone()
  })
  const set = (k: keyof typeof EMPTY) => (e: React.ChangeEvent<HTMLInputElement>) => setAddress({ ...address, [k]: e.target.value })
  const good = rows?.filter((r) => r.problems.length === 0).length ?? 0

  return (
    <Modal title="Set up the phone system" onClose={onClose} wide>
      <ol className="pv-steps">{STEPS.map((s, i) => <li key={s} aria-current={i === step ? 'step' : undefined}>{i + 1}. {s}</li>)}</ol>
      {step === 0 && (sites.data ? (
        <>
          <div className="ph-field">
            <label htmlFor="pv-site">Site</label>
            <select id="pv-site" className="ph-input" value={chosen} onChange={(e) => setSite(e.target.value)}>
              {sites.data.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </div>
          <p className="ph-hint">The address 911 calls from this site are sent to. Photon checks it against the 911 database before the site can have phones;
            you can carry on meanwhile. (If the site already has one, it is used.)</p>
          <div className="pv-row">
            <div className="ph-field"><label htmlFor="pv-street">Street</label><input id="pv-street" className="ph-input" value={address.street} onChange={set('street')} /></div>
            <div className="ph-field"><label htmlFor="pv-unit">Suite or floor</label><input id="pv-unit" className="ph-input" value={address.unit} onChange={set('unit')} /></div>
          </div>
          <div className="pv-row">
            <div className="ph-field"><label htmlFor="pv-city">City</label><input id="pv-city" className="ph-input" value={address.city} onChange={set('city')} /></div>
            <div className="ph-field"><label htmlFor="pv-state">State</label><input id="pv-state" className="ph-input" maxLength={2} value={address.state}
              onChange={(e) => setAddress({ ...address, state: e.target.value.toUpperCase() })} /></div>
            <div className="ph-field"><label htmlFor="pv-zip">ZIP code</label><input id="pv-zip" className="ph-input" value={address.zip} onChange={set('zip')} /></div>
          </div>
          <ErrorText>{error}</ErrorText>
          <div className="ph-modal-footer"><button className="ph-btn" disabled={busy || !chosen} onClick={() => void saveAddress()}>Next</button></div>
        </>
      ) : <><ErrorText>{sites.error}</ErrorText><Loading what="sites" /></>)}
      {step === 1 && (
        <>
          <div className="ph-field">
            <label htmlFor="pv-number">Main number</label>
            <input id="pv-number" className="ph-input" inputMode="tel" placeholder="(724) 555-0100" value={number} onChange={(e) => setNumber(e.target.value)} />
          </div>
          <p className="ph-hint">One of this customer’s numbers. It is also the number a 911 call from the site shows, so the dispatcher can call back.</p>
          <fieldset className="ph-field">
            <legend>Template</legend>
            {(templates.data ?? []).map((t) => (
              <label key={t.key} className="ph-check">
                <input type="radio" name="pv-template" value={t.key} checked={template === t.key} onChange={() => setTemplate(t.key)} />
                <span><strong>{t.name}</strong> <span className="ph-hint">{t.description}</span></span>
              </label>
            ))}
          </fieldset>
          <div className="ph-modal-footer">
            <button className="ph-btn ph-btn-secondary" onClick={() => setStep(0)}>Back</button>
            <button className="ph-btn" disabled={!number.trim()} onClick={() => setStep(2)}>Next</button>
          </div>
        </>
      )}
      {step === 2 && (
        <>
          <div className="ph-field">
            <label htmlFor="pv-people">People, one per line: name, extension, email, direct number, site</label>
            <textarea id="pv-people" className="ph-input pv-paste" value={people} placeholder={'Ada Front, 100, ada@example.com\nBen Office'}
              onChange={(e) => { setPeople(e.target.value); setRows(null) }} />
          </div>
          <p className="ph-hint">Paste from a spreadsheet: columns in that order, or a header row naming them. A blank extension gets the next free one.</p>
          {rows && <ImportReview rows={rows} />}
          <ErrorText>{error}</ErrorText>
          <div className="ph-modal-footer">
            <button className="ph-btn ph-btn-secondary" onClick={() => setStep(1)}>Back</button>
            <button className="ph-btn ph-btn-secondary" disabled={busy || !people.trim()} onClick={() => void review()}>Check</button>
            <button className="ph-btn" disabled={busy || !rows || good === 0} onClick={() => void finish()}>Create the phone system with {good} {good === 1 ? 'person' : 'people'}</button>
          </div>
        </>
      )}
    </Modal>
  )
}

/** Pasted rows as they would be imported: each with its problems, in words. Rows with problems are left out. */
export function ImportReview({ rows }: { rows: ImportRow[] }) {
  const bad = rows.filter((r) => r.problems.length).length
  return (
    <div className="ph-table-wrap">
      <p role="status">{rows.length - bad} ready{bad ? `, ${bad} with problems (left out)` : ''}.</p>
      <table className="ph-table pv-table">
        <thead><tr><th>Line</th><th>Name</th><th>Extension</th><th>Email</th><th>Problems</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.line}>
              <td data-label="Line">{r.line}</td>
              <td data-label="Name" className="pv-who">{r.user.name || '—'}</td>
              <td data-label="Extension">{r.user.extension}</td>
              <td data-label="Email">{r.user.email ?? ''}</td>
              <td data-label="Problems">{r.problems.length ? <span className="ph-error">{r.problems.join('; ')}</span> : 'none'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
