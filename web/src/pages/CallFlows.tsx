import { useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import { useTenant } from '../auth/TenantContext'
import { VOICES, type Draft, type DraftDoor, type DraftGroup, type DraftHours, type DraftMenu, type DraftPage } from '../api/types'
import { rename, slug, TargetPicker, targetText, targetValue, toTarget, useDraft, useSiteNames } from '../components/draft'
import { ErrorText, Loading, Modal, PageHeader } from '../components/ui'

type Kind = 'group' | 'menu' | 'box' | 'hours' | 'door' | 'page'
const DAYS = [['mon', 'Monday'], ['tue', 'Tuesday'], ['wed', 'Wednesday'], ['thu', 'Thursday'], ['fri', 'Friday'], ['sat', 'Saturday'], ['sun', 'Sunday']] as const
const SPAN = /^([01][0-9]|2[0-3]):[0-5][0-9]-(([01][0-9]|2[0-3]):[0-5][0-9]|24:00)$/
const DIGITS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0']

/** Call flows (ARCHITECTURE §8): ring groups, menus, shared mailboxes and office hours, as outcomes. Every change is saved to the draft at once;
 *  what it breaks (a number pointing at a removed group) is listed on the Overview and stops publishing, never saving. */
export function CallFlowsPage() {
  const { ps, draft, change, saving, error, canBuild } = useDraft()
  const names = useSiteNames()
  const [editing, setEditing] = useState<{ kind: Kind; key: string } | null>(null)
  if (ps.loading && !ps.data) return <><PageHeader title="Call flows" /><Loading what="call flows" /></>
  if (!draft) return <><PageHeader title="Call flows" /><ErrorText>{ps.error}</ErrorText><div className="ph-empty"><p>This customer has no phone system yet. Set it up from the Overview.</p></div></>
  const save = async (fn: (d: Draft) => Draft) => { if (await change(fn)) setEditing(null) }
  const add = (kind: Kind) => canBuild && <button className="ph-btn ph-btn-secondary ph-btn-sm" onClick={() => setEditing({ kind, key: '' })}>Add</button>
  const edit = (kind: Kind, key: string) => canBuild && <button className="ph-btn ph-btn-secondary ph-btn-sm" aria-label={`Change ${key}`} onClick={() => setEditing({ kind, key })}>Change</button>
  const groups = Object.entries(draft.groups ?? {})
  const menus = Object.entries(draft.menus ?? {})
  const boxes = Object.entries(draft.boxes ?? {})
  const hours = Object.entries(draft.hours ?? {})
  const doors = Object.entries(draft.doors ?? {})
  const pages = Object.entries(draft.pages ?? {})
  return (
    <>
      <PageHeader title="Call flows">{canBuild && <CloneFrom onDone={() => ps.reload()} />}</PageHeader>
      <ErrorText>{error}</ErrorText>
      <section aria-label="Ring groups">
        <div className="ph-page-header"><h2>Ring groups</h2><div className="ph-actions">{add('group')}</div></div>
        {groups.length === 0 ? <p className="ph-hint">None yet.</p> : (
          <ul className="pv-plain">{groups.map(([k, g]) => (
            <li key={k}><strong>{k}</strong>: {g.members.map((m) => draft.users?.[m]?.name ?? m).join(', ')} <span className="ph-hint">
              ({g.strategy === 'sequence' ? `one after another, ${g.ring_seconds ?? 25} s each` : `all at once, ${g.ring_seconds ?? 25} s`}, then {g.then ? targetText(draft, g.then) : 'hang up'})</span> {edit('group', k)}</li>
          ))}</ul>
        )}
      </section>
      <section aria-label="Menus">
        <div className="ph-page-header"><h2>Menus</h2><div className="ph-actions">{add('menu')}</div></div>
        <div className="ph-field">
          <label htmlFor="pv-voice">Greetings are spoken in</label>
          <select id="pv-voice" className="ph-input" disabled={!canBuild || saving} value={draft.voice ?? VOICES[0][0]}
            onChange={(e) => void change((d) => ({ ...d, voice: e.target.value }))}>
            {VOICES.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
          </select>
          <small className="ph-hint">Spoken when the phone system is published. A recorded greeting, when there is one, is played instead.</small>
        </div>
        {menus.length === 0 ? <p className="ph-hint">None yet.</p> : (
          <ul className="pv-plain">{menus.map(([k, m]) => (
            <li key={k}><strong>{k}</strong>: “{m.greeting}” <span className="ph-hint">
              {Object.entries(m.options).map(([d, t]) => `${d} → ${targetText(draft, t)}`).join('; ')}; no key → {m.timeout ? targetText(draft, m.timeout) : 'the call ends'}</span> {edit('menu', k)}</li>
          ))}</ul>
        )}
      </section>
      <section aria-label="Shared mailboxes">
        <div className="ph-page-header"><h2>Shared mailboxes</h2><div className="ph-actions">{add('box')}</div></div>
        {boxes.length === 0 ? <p className="ph-hint">None yet. Everyone also has their own.</p> : (
          <ul className="pv-plain">{boxes.map(([k, b]) => <li key={k}><strong>{b.name}</strong> <span className="ph-hint">{b.email ? `emails ${b.email}` : 'no email'}</span> {edit('box', k)}</li>)}</ul>
        )}
      </section>
      <section aria-label="Office hours">
        <div className="ph-page-header"><h2>Office hours</h2><div className="ph-actions">{add('hours')}</div></div>
        {hours.length === 0 ? <p className="ph-hint">None yet.</p> : (
          <ul className="pv-plain">{hours.map(([k, h]) => (
            <li key={k}><strong>{k}</strong>: <span className="ph-hint">{DAYS.filter(([d]) => h.week[d]?.length).map(([d, n]) => `${n.slice(0, 3)} ${h.week[d]!.join(', ')}`).join('; ') || 'always closed'}
              {h.holidays === 'us-federal' ? '; closed on US federal holidays' : ''}</span> {edit('hours', k)}</li>
          ))}</ul>
        )}
        {Object.keys(draft.sites ?? {}).length > 0 && (
          <div className="pv-row">{Object.entries(draft.sites ?? {}).map(([id, s]) => (
            <div key={id} className="ph-field">
              <label htmlFor={`pv-site-hours-${id}`}>{names[id] ?? 'Site'}: office hours</label>
              <select id={`pv-site-hours-${id}`} className="ph-input" disabled={!canBuild || saving} value={s.hours ?? ''}
                onChange={(e) => void change((d) => ({ ...d, sites: { ...d.sites, [id]: { ...d.sites![id], hours: e.target.value || null } } }))}>
                <option value="">none</option>
                {hours.map(([k]) => <option key={k} value={k}>{k}</option>)}
              </select>
            </div>
          ))}</div>
        )}
      </section>
      <section aria-label="Doors">
        <div className="ph-page-header"><h2>Doors</h2><div className="ph-actions">{add('door')}</div></div>
        {doors.length === 0 ? <p className="ph-hint">None yet. A door station is a PhotonEntry intercom: when someone presses its button, it rings who you choose, and pressing # on the call opens the door.</p> : (
          <ul className="pv-plain">{doors.map(([k, x]) => (
            <li key={k}><strong>{x.name}</strong> ({x.extension}): <span className="ph-hint">{names[x.site] ?? 'a site'}; rings {targetText(draft, x.open)}
              {x.closed ? `, after hours ${targetText(draft, x.closed)}` : ''}</span> {edit('door', k)}</li>
          ))}</ul>
        )}
      </section>
      <section aria-label="Paging">
        <div className="ph-page-header"><h2>Paging</h2><div className="ph-actions">{add('page')}</div></div>
        {pages.length === 0 ? <p className="ph-hint">None yet. A paging group speaks through several phones and overhead speakers at once: dial its extension and talk.</p> : (
          <ul className="pv-plain">{pages.map(([k, x]) => (
            <li key={k}><strong>{x.name}</strong> ({x.extension}): <span className="ph-hint">{names[x.site] ?? 'a site'};{' '}
              {x.members.map((m) => draft.users?.[m]?.name ?? m).join(', ')}</span> {edit('page', k)}</li>
          ))}</ul>
        )}
      </section>
      {editing?.kind === 'page' && <PageForm draft={draft} k={editing.key} saving={saving} error={error} onClose={() => setEditing(null)} save={save} siteNames={names} />}
      {editing?.kind === 'door' && <DoorForm draft={draft} k={editing.key} saving={saving} error={error} onClose={() => setEditing(null)} save={save} siteNames={names} />}
      {editing?.kind === 'group' && <GroupForm draft={draft} k={editing.key} saving={saving} error={error} onClose={() => setEditing(null)} save={save} />}
      {editing?.kind === 'menu' && <MenuForm draft={draft} k={editing.key} saving={saving} error={error} onClose={() => setEditing(null)} save={save} />}
      {editing?.kind === 'box' && <BoxForm draft={draft} k={editing.key} saving={saving} error={error} onClose={() => setEditing(null)} save={save} />}
      {editing?.kind === 'hours' && <HoursForm draft={draft} k={editing.key} saving={saving} error={error} onClose={() => setEditing(null)} save={save} />}
    </>
  )
}

type FormProps = { draft: Draft; k: string; saving: boolean; error: string | null; onClose: () => void; save: (fn: (d: Draft) => Draft) => Promise<void> }

/** Put `value` under `key` in a part of the draft (renaming from `was`), or remove `was` when `value` is null. */
function put<T>(part: Record<string, T> | undefined, was: string, key: string, value: T | null): Record<string, T> {
  const rest = Object.fromEntries(Object.entries(part ?? {}).filter(([k]) => k !== was))
  return value === null ? rest : { ...rest, [key]: value }
}

/** A name as typed; the document keeps its short form (shown under it when it differs). */
function NameField({ id, value, onChange, taken }: { id: string; value: string; onChange: (v: string) => void; taken: boolean }) {
  const key = slug(value)
  return (
    <div className="ph-field">
      <label htmlFor={id}>Name</label>
      <input id={id} className="ph-input" value={value} onChange={(e) => onChange(e.target.value)} aria-invalid={taken} />
      {taken ? <small className="ph-error">That name is taken.</small> : key && key !== value ? <small className="ph-hint">Saved as {key}</small> : null}
    </div>
  )
}

function Footer({ k, saving, ok, onSave, onRemove }: { k: string; saving: boolean; ok: boolean; onSave: () => void; onRemove: () => void }) {
  return (
    <div className="ph-modal-footer">
      {k && <button className="ph-btn ph-btn-danger" disabled={saving} onClick={onRemove}>Remove {k}</button>}
      <button className="ph-btn" disabled={saving || !ok} onClick={onSave}>Save</button>
    </div>
  )
}

function DoorForm({ draft, k, saving, error, onClose, save, siteNames }: FormProps & { siteNames: Record<string, string> }) {
  const was: DraftDoor | undefined = draft.doors?.[k]
  const sites = Object.keys(draft.sites ?? {})
  const [name, setName] = useState(was?.name ?? '')
  const [site, setSite] = useState(was?.site ?? sites[0] ?? '')
  const [extension, setExtension] = useState(was?.extension ?? '')
  const [open, setOpen] = useState(targetValue(was?.open))
  const [closed, setClosed] = useState(targetValue(was?.closed))
  const key = k || slug(name)
  const taken = !k && !!draft.doors?.[key]
  const used = [...Object.values(draft.users ?? {}), ...Object.entries(draft.doors ?? {}).filter(([d]) => d !== k).map(([, x]) => x)].some((x) => x.extension === extension)
  const ok = !!key && !taken && !!name.trim() && !!site && /^[1-8][0-9]{1,4}$/.test(extension) && !used && !!open
  const value: DraftDoor = { name: name.trim(), site, extension, open: toTarget(open)!, closed: toTarget(closed) }
  return (
    <Modal title={k ? `Door ${was?.name ?? k}` : 'New door'} onClose={onClose}>
      <div className="ph-field"><label htmlFor="pv-door-name">Name</label>
        <input id="pv-door-name" className="ph-input" value={name} maxLength={100} onChange={(e) => setName(e.target.value)} aria-invalid={taken} placeholder="Front door" />
        {taken && <small className="ph-error">That name is taken.</small>}</div>
      <div className="pv-row">
        <div className="ph-field"><label htmlFor="pv-door-site">Site</label>
          <select id="pv-door-site" className="ph-input" value={site} onChange={(e) => setSite(e.target.value)}>
            {sites.map((id) => <option key={id} value={id}>{siteNames[id] ?? 'Site'}</option>)}
          </select></div>
        <div className="ph-field"><label htmlFor="pv-door-ext">Extension</label>
          <input id="pv-door-ext" className="ph-input" inputMode="numeric" value={extension} onChange={(e) => setExtension(e.target.value.trim())} aria-invalid={used} />
          {used && <small className="ph-error">That extension is taken.</small>}</div>
      </div>
      <TargetPicker id="pv-door-open" label="Rings" draft={draft} value={open} onChange={setOpen} peopleOnly />
      <TargetPicker id="pv-door-closed" label="After hours (the site's office hours)" draft={draft} value={closed} onChange={setClosed} allowNone="the same" peopleOnly />
      <p className="ph-hint">The door's intercom is set up in PhotonEntry, which reads this door once the phone system is published.</p>
      <ErrorText>{error}</ErrorText>
      <Footer k={k} saving={saving} ok={ok} onSave={() => void save((d) => ({ ...d, doors: put(d.doors, k, key, value) }))}
        onRemove={() => void save((d) => ({ ...d, doors: put(d.doors, k, k, null) }))} />
    </Modal>
  )
}

function PageForm({ draft, k, saving, error, onClose, save, siteNames }: FormProps & { siteNames: Record<string, string> }) {
  const was: DraftPage | undefined = draft.pages?.[k]
  const sites = Object.keys(draft.sites ?? {})
  const [name, setName] = useState(was?.name ?? '')
  const [site, setSite] = useState(was?.site ?? sites[0] ?? '')
  const [extension, setExtension] = useState(was?.extension ?? '')
  const [members, setMembers] = useState<string[]>(was?.members ?? [])
  const key = k || slug(name)
  const taken = !k && !!draft.pages?.[key]
  const used = [...Object.values(draft.users ?? {}), ...Object.values(draft.doors ?? {}),
    ...Object.entries(draft.pages ?? {}).filter(([p]) => p !== k).map(([, x]) => x)].some((x) => x.extension === extension)
  const ok = !!key && !taken && !!name.trim() && !!site && /^[1-8][0-9]{1,4}$/.test(extension) && !used && members.length > 0
  const value: DraftPage = { name: name.trim(), site, extension, members }
  const here = Object.entries(draft.users ?? {}).filter(([, u]) => u.site === site)
  return (
    <Modal title={k ? `Paging ${was?.name ?? k}` : 'New paging group'} onClose={onClose}>
      <div className="ph-field"><label htmlFor="pv-page-name">Name</label>
        <input id="pv-page-name" className="ph-input" value={name} maxLength={100} onChange={(e) => setName(e.target.value)} aria-invalid={taken} placeholder="Warehouse paging" />
        {taken && <small className="ph-error">That name is taken.</small>}</div>
      <div className="pv-row">
        <div className="ph-field"><label htmlFor="pv-page-site">Site</label>
          <select id="pv-page-site" className="ph-input" value={site} onChange={(e) => { setSite(e.target.value); setMembers([]) }}>
            {sites.map((id) => <option key={id} value={id}>{siteNames[id] ?? 'Site'}</option>)}
          </select></div>
        <div className="ph-field"><label htmlFor="pv-page-ext">Extension to dial</label>
          <input id="pv-page-ext" className="ph-input" inputMode="numeric" value={extension} onChange={(e) => setExtension(e.target.value.trim())} aria-invalid={used} />
          {used && <small className="ph-error">That extension is taken.</small>}</div>
      </div>
      <fieldset className="ph-field"><legend>Phones and speakers it speaks through</legend>
        {here.length === 0 && <p className="ph-hint">No phones at this site yet.</p>}
        {here.map(([id, u]) => (
          <label key={id} className="ph-check"><input type="checkbox" checked={members.includes(id)}
            onChange={(e) => setMembers(e.target.checked ? [...members, id] : members.filter((m) => m !== id))} /> {u.name} ({u.extension})</label>
        ))}
      </fieldset>
      <p className="ph-hint">Each phone answers by itself on its speaker; it only listens. An overhead speaker is added as a user with its voicemail off.</p>
      <ErrorText>{error}</ErrorText>
      <Footer k={k} saving={saving} ok={ok} onSave={() => void save((d) => ({ ...d, pages: put(d.pages, k, key, value) }))}
        onRemove={() => void save((d) => ({ ...d, pages: put(d.pages, k, k, null) }))} />
    </Modal>
  )
}

function GroupForm({ draft, k, saving, error, onClose, save }: FormProps) {
  const was: DraftGroup | undefined = draft.groups?.[k]
  const [name, setName] = useState(k)
  const [members, setMembers] = useState<string[]>(was?.members ?? [])
  const [strategy, setStrategy] = useState(was?.strategy ?? 'simultaneous')
  const [seconds, setSeconds] = useState(String(was?.ring_seconds ?? 25))
  const [then, setThen] = useState(targetValue(was?.then))
  const key = slug(name)
  const taken = key !== k && !!draft.groups?.[key]
  const ok = !!key && !taken && members.length > 0 && Number(seconds) >= 10 && Number(seconds) <= 120
  const value: DraftGroup = { members, strategy, ring_seconds: Number(seconds), then: toTarget(then) }
  return (
    <Modal title={k ? `Ring group ${k}` : 'New ring group'} onClose={onClose}>
      <NameField id="pv-group-name" value={name} onChange={setName} taken={taken} />
      <fieldset className="ph-field"><legend>Who it rings</legend>
        {Object.entries(draft.users ?? {}).map(([id, u]) => (
          <label key={id} className="ph-check"><input type="checkbox" checked={members.includes(id)}
            onChange={(e) => setMembers(e.target.checked ? [...members, id] : members.filter((m) => m !== id))} /> {u.name} ({u.extension})</label>
        ))}
      </fieldset>
      <div className="pv-row">
        <div className="ph-field"><label htmlFor="pv-group-strategy">How</label>
          <select id="pv-group-strategy" className="ph-input" value={strategy} onChange={(e) => setStrategy(e.target.value as 'simultaneous' | 'sequence')}>
            <option value="simultaneous">All at once</option><option value="sequence">One after another</option>
          </select></div>
        <div className="ph-field"><label htmlFor="pv-group-seconds">{strategy === 'sequence' ? 'Ring each phone for (seconds)' : 'Ring for (seconds)'}</label>
          <input id="pv-group-seconds" className="ph-input" type="number" min={10} max={120} value={seconds} onChange={(e) => setSeconds(e.target.value)} /></div>
      </div>
      <TargetPicker id="pv-group-then" label="If nobody answers" draft={draft} value={then} onChange={setThen} allowNone="Hang up" />
      <ErrorText>{error}</ErrorText>
      <Footer k={k} saving={saving} ok={ok} onSave={() => void save((d) => rename({ ...d, groups: put(d.groups, k, key, value) }, 'group', k, key))}
        onRemove={() => void save((d) => ({ ...d, groups: put(d.groups, k, k, null) }))} />
    </Modal>
  )
}

function MenuForm({ draft, k, saving, error, onClose, save }: FormProps) {
  const was: DraftMenu | undefined = draft.menus?.[k]
  const [name, setName] = useState(k || 'main')
  const [greeting, setGreeting] = useState(was?.greeting ?? '')
  const [options, setOptions] = useState<Record<string, string>>(Object.fromEntries(Object.entries(was?.options ?? {}).map(([d, t]) => [d, targetValue(t)])))
  const [timeout, setTimeoutTarget] = useState(targetValue(was?.timeout))
  const key = slug(name)
  const taken = key !== k && !!draft.menus?.[key]
  const ok = !!key && !taken && greeting.trim().length > 0 && !!timeout
  const value: DraftMenu = { greeting, timeout: toTarget(timeout)!, options: Object.fromEntries(Object.entries(options).filter(([, v]) => v).map(([d, v]) => [d, toTarget(v)!])) }
  return (
    <Modal title={k ? `Menu ${k}` : 'New menu'} onClose={onClose} wide>
      <NameField id="pv-menu-name" value={name} onChange={setName} taken={taken} />
      <div className="ph-field"><label htmlFor="pv-menu-greeting">What callers hear</label>
        <textarea id="pv-menu-greeting" className="ph-input" maxLength={500} value={greeting} onChange={(e) => setGreeting(e.target.value)}
          placeholder="Thank you for calling. For the front desk, press 1." /></div>
      <div className="pv-row">{DIGITS.map((d) => (
        <TargetPicker key={d} id={`pv-menu-${d}`} label={`Key ${d}`} draft={draft} value={options[d] ?? ''} allowNone="nothing"
          onChange={(v) => setOptions({ ...options, [d]: v })} />
      ))}</div>
      <TargetPicker id="pv-menu-timeout" label="If no key is pressed" draft={draft} value={timeout} onChange={setTimeoutTarget} />
      <ErrorText>{error}</ErrorText>
      <Footer k={k} saving={saving} ok={ok} onSave={() => void save((d) => rename({ ...d, menus: put(d.menus, k, key, value) }, 'menu', k, key))}
        onRemove={() => void save((d) => ({ ...d, menus: put(d.menus, k, k, null) }))} />
    </Modal>
  )
}

function BoxForm({ draft, k, saving, error, onClose, save }: FormProps) {
  const was = draft.boxes?.[k]
  const [label, setLabel] = useState(was?.name ?? '')
  const [email, setEmail] = useState(was?.email ?? '')
  const key = k || slug(label)
  const ok = label.trim().length > 0 && !!key && (!!k || !draft.boxes?.[key]) && (!email || /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email))
  return (
    <Modal title={k ? `Mailbox ${was?.name}` : 'New shared mailbox'} onClose={onClose}>
      <div className="ph-field"><label htmlFor="pv-box-name">Name</label><input id="pv-box-name" className="ph-input" value={label} onChange={(e) => setLabel(e.target.value)} /></div>
      <div className="ph-field"><label htmlFor="pv-box-email">Email new messages to</label>
        <input id="pv-box-email" className="ph-input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></div>
      <p className="ph-hint">Messages arrive by email with the recording attached, and stay in the mailbox too.</p>
      <ErrorText>{error}</ErrorText>
      <Footer k={k} saving={saving} ok={ok} onSave={() => void save((d) => ({ ...d, boxes: put(d.boxes, k, key, { name: label, email: email || null }) }))}
        onRemove={() => void save((d) => ({ ...d, boxes: put(d.boxes, k, k, null) }))} />
    </Modal>
  )
}

function HoursForm({ draft, k, saving, error, onClose, save }: FormProps) {
  const was: DraftHours | undefined = draft.hours?.[k]
  const [name, setName] = useState(k || 'office')
  const [days, setDays] = useState<Record<string, string>>(Object.fromEntries(DAYS.map(([d]) => [d, (was?.week[d] ?? []).join(', ')])))
  const [holidays, setHolidays] = useState(was?.holidays ?? 'us-federal')
  const spans = (text: string) => text.split(',').map((x) => x.trim().replace(/\s+/g, '')).filter(Boolean)
  const bad = DAYS.filter(([d]) => spans(days[d]).some((x) => !SPAN.test(x))).map(([, n]) => n)
  const key = slug(name)
  const taken = key !== k && !!draft.hours?.[key]
  const ok = !!key && !taken && bad.length === 0
  const value: DraftHours = { holidays, week: Object.fromEntries(DAYS.filter(([d]) => spans(days[d]).length).map(([d]) => [d, spans(days[d])])) }
  return (
    <Modal title={k ? `Office hours ${k}` : 'New office hours'} onClose={onClose}>
      <NameField id="pv-hours-name" value={name} onChange={setName} taken={taken} />
      <p className="ph-hint">Open times per day in the site’s time zone, like “08:00-17:00” or “08:00-12:00, 13:00-17:00”. Leave a day empty when closed.</p>
      {DAYS.map(([d, n]) => (
        <div key={d} className="ph-field"><label htmlFor={`pv-hours-${d}`}>{n}</label>
          <input id={`pv-hours-${d}`} className="ph-input" value={days[d]} onChange={(e) => setDays({ ...days, [d]: e.target.value })}
            aria-invalid={spans(days[d]).some((x) => !SPAN.test(x))} /></div>
      ))}
      {bad.length > 0 && <small className="ph-error">Not a time span: {bad.join(', ')}.</small>}
      <label className="ph-check"><input type="checkbox" checked={holidays === 'us-federal'} onChange={(e) => setHolidays(e.target.checked ? 'us-federal' : 'none')} /> Closed on US federal holidays</label>
      <ErrorText>{error}</ErrorText>
      <Footer k={k} saving={saving} ok={ok} onSave={() => void save((d) => ({ ...d, hours: put(d.hours, k, key, value),
          sites: Object.fromEntries(Object.entries(d.sites ?? {}).map(([id, st]) => [id, k && st.hours === k ? { ...st, hours: key } : st])),
          numbers: Object.fromEntries(Object.entries(d.numbers ?? {}).map(([n, x]) => [n, k && x.hours === k ? { ...x, hours: key } : x])) }))}
        onRemove={() => void save((d) => ({ ...d, hours: put(d.hours, k, k, null) }))} />
    </Modal>
  )
}

/** Clone: another customer's call flows, hours, calling policy and features as a starting point (people matched by extension). */
function CloneFrom({ onDone }: { onDone: () => Promise<void> }) {
  const { api } = useAuth()
  const { current, tenants } = useTenant()
  const others = tenants.filter((t) => t.id !== current!.id && t.capabilities.includes('vox.phone_system.view'))
  const [open, setOpen] = useState(false)
  const [from, setFrom] = useState(others[0]?.id ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  if (others.length === 0) return null
  const go = async () => {
    setBusy(true); setError(null)
    try { await api.post(`/tenants/${current!.id}/phone-system/draft/clone`, { from_tenant_id: from }); setOpen(false); await onDone() }
    catch (e) { setError(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) }
  }
  return (
    <>
      <button className="ph-btn ph-btn-secondary" onClick={() => setOpen(true)}>Copy from another customer</button>
      {open && (
        <Modal title="Copy call flows from another customer" onClose={() => setOpen(false)}>
          <div className="ph-field">
            <label htmlFor="pv-clone-from">Customer</label>
            <select id="pv-clone-from" className="ph-input" value={from} onChange={(e) => setFrom(e.target.value)}>
              {others.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          </div>
          <p className="ph-hint">Their ring groups, menus, shared mailboxes, office hours, calling policy and features replace this customer’s.
            Sites, numbers and people stay; people are matched by extension, and anything that does not match is listed on the Overview to fix.</p>
          <ErrorText>{error}</ErrorText>
          <div className="ph-modal-footer"><button className="ph-btn" disabled={busy} onClick={() => void go()}>Copy</button></div>
        </Modal>
      )}
    </>
  )
}
