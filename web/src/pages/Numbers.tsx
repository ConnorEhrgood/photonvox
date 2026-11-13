import { useState } from 'react'
import type { Draft, DraftNumber } from '../api/types'
import { TargetPicker, targetText, targetValue, toTarget, useDraft, useSiteNames } from '../components/draft'
import { ErrorText, Loading, Modal, PageHeader } from '../components/ui'

const E164 = /^\+1[2-9][0-9]{2}[2-9][0-9]{6}$/
/** "(724) 555-0100", "724-555-0100", "17245550100" → "+17245550100". */
export const toE164 = (raw: string): string => {
  let d = raw.replace(/\D/g, '')
  if (d.length === 10) d = '1' + d
  return d ? `+${d}` : ''
}

/** The organization's numbers and what each rings, by its hours (ARCHITECTURE §8: outcomes, never routes). */
export function NumbersPage() {
  const { ps, draft, change, saving, error, canBuild } = useDraft()
  const [editing, setEditing] = useState<string | null>(null)       // a number, or '' for a new one
  const names = useSiteNames()
  if (ps.loading && !ps.data) return <><PageHeader title="Numbers" /><Loading what="numbers" /></>
  if (!draft) return <><PageHeader title="Numbers" /><ErrorText>{ps.error}</ErrorText><div className="ph-empty"><p>This customer has no phone system yet. Set it up from the Overview.</p></div></>
  const sites = Object.keys(draft.sites ?? {})
  const numbers = Object.entries(draft.numbers ?? {}).sort(([a], [b]) => a.localeCompare(b))
  return (
    <>
      <PageHeader title="Numbers">{canBuild && sites.length > 0 && <button className="ph-btn" onClick={() => setEditing('')}>Add a number</button>}</PageHeader>
      <ErrorText>{error}</ErrorText>
      {numbers.length === 0 ? <div className="ph-empty"><p>No numbers yet.</p></div> : (
        <div className="ph-table-wrap">
          <table className="ph-table pv-table">
            <thead><tr><th>Number</th><th>Site</th><th>Rings</th><th>After hours</th><th>Hours</th><th><span className="ph-sr-only">Change</span></th></tr></thead>
            <tbody>
              {numbers.map(([num, n]) => (
                <tr key={num}>
                  <td data-label="Number" className="pv-who"><strong>{num}</strong></td>
                  <td data-label="Site">{names[n.site] ?? '—'}</td>
                  <td data-label="Rings">{targetText(draft, n.open)}</td>
                  <td data-label="After hours">{n.closed ? targetText(draft, n.closed) : 'the same, at all hours'}</td>
                  <td data-label="Hours">{n.closed ? (n.hours ?? draft.sites?.[n.site]?.hours ?? '—') : '—'}</td>
                  <td data-label="">{canBuild && <button className="ph-btn ph-btn-secondary ph-btn-sm" aria-label={`Change ${num}`} onClick={() => setEditing(num)}>Change</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="ph-hint">Changes reach the phones when the phone system is published (Overview).</p>
        </div>
      )}
      {editing !== null && (
        <NumberForm draft={draft} names={names} number={editing} saving={saving} error={error} onClose={() => setEditing(null)}
          onSave={async (num, n) => {
            if (await change((d) => ({ ...d, numbers: { ...Object.fromEntries(Object.entries(d.numbers ?? {}).filter(([k]) => k !== editing)), [num]: n } }))) setEditing(null)
          }}
          onRemove={async () => {
            if (await change((d) => ({ ...d, numbers: Object.fromEntries(Object.entries(d.numbers ?? {}).filter(([k]) => k !== editing)) }))) setEditing(null)
          }} />
      )}
    </>
  )
}

function NumberForm({ draft, names, number, saving, error, onClose, onSave, onRemove }: {
  draft: Draft; names: Record<string, string>; number: string; saving: boolean; error: string | null; onClose: () => void
  onSave: (num: string, n: DraftNumber) => Promise<void>; onRemove: () => Promise<void>
}) {
  const was = draft.numbers?.[number]
  const sites = Object.keys(draft.sites ?? {})
  const [num, setNum] = useState(number)
  const [site, setSite] = useState(was?.site ?? sites[0])
  const [open, setOpen] = useState(targetValue(was?.open))
  const [split, setSplit] = useState(!!was?.closed)
  const [closed, setClosed] = useState(targetValue(was?.closed))
  const [hours, setHours] = useState(was?.hours ?? '')
  const e164 = toE164(num)
  const valid = E164.test(e164) && !!open && (!split || !!closed)
  return (
    <Modal title={number ? `Change ${number}` : 'Add a number'} onClose={onClose}>
      <div className="ph-field">
        <label htmlFor="pv-num">Number</label>
        <input id="pv-num" className="ph-input" inputMode="tel" value={num} onChange={(e) => setNum(e.target.value)} aria-invalid={!!num && !E164.test(e164)} />
      </div>
      <div className="ph-field">
        <label htmlFor="pv-num-site">Site (its 911 address and caller ID)</label>
        <select id="pv-num-site" className="ph-input" value={site} onChange={(e) => setSite(e.target.value)}>
          {sites.map((s) => <option key={s} value={s}>{names[s] ?? s}</option>)}
        </select>
      </div>
      <TargetPicker id="pv-num-open" label={split ? 'In office hours it rings' : 'It rings'} draft={draft} value={open} onChange={setOpen} />
      <label className="ph-check"><input type="checkbox" checked={split} onChange={(e) => setSplit(e.target.checked)} /> Something else after hours</label>
      {split && (
        <>
          <TargetPicker id="pv-num-closed" label="After hours it rings" draft={draft} value={closed} onChange={setClosed} />
          <div className="ph-field">
            <label htmlFor="pv-num-hours">Office hours</label>
            <select id="pv-num-hours" className="ph-input" value={hours} onChange={(e) => setHours(e.target.value)}>
              <option value="">the site’s hours</option>
              {Object.keys(draft.hours ?? {}).map((h) => <option key={h} value={h}>{h}</option>)}
            </select>
          </div>
        </>
      )}
      <ErrorText>{error}</ErrorText>
      <div className="ph-modal-footer">
        {number && <button className="ph-btn ph-btn-danger" disabled={saving} onClick={() => void onRemove()}>Remove {number}</button>}
        <button className="ph-btn" disabled={saving || !valid} onClick={() => void onSave(e164, {
          site, open: toTarget(open)!, ...(split ? { closed: toTarget(closed), hours: hours || null } : {}),
        })}>Save</button>
      </div>
    </Modal>
  )
}
