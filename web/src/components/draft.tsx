import { useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import { useTenant } from '../auth/TenantContext'
import { ApiError } from '../api/client'
import type { Draft, PhoneSystemSummary, Site } from '../api/types'
import { useLoad } from '../lib/useLoad'

/** A target in the document ({user: id} | {group} | {menu} | {voicemail}) as one string for a <select>: "user:u-ada". */
export type TargetValue = string
export type Target = Record<string, string>

export const targetValue = (t?: Target | null): TargetValue => (t ? `${Object.keys(t)[0]}:${Object.values(t)[0]}` : '')
export const toTarget = (v: TargetValue): Target | null => {
  const [kind, ...rest] = v.split(':')
  return kind && rest.length ? { [kind]: rest.join(':') } : null
}

/** A short name the document accepts (`^[a-z0-9][a-z0-9_-]{0,39}$`) from what a person typed. */
export const slug = (text: string): string => text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40)

/** The phone system's draft, loaded and saved whole: the API checks the shape (422 with each field's error) and reports problems, which
 *  stop publishing but never saving. `change` applies a change to a copy and saves it; the result (or the error) is what the page shows. */
export function useDraft() {
  const { api } = useAuth()
  const { current, can } = useTenant()
  const base = `/tenants/${current!.id}`
  const ps = useLoad(async () => {
    try { return await api.get<PhoneSystemSummary>(`${base}/phone-system`) } catch (e) {
      if (e instanceof ApiError && e.data?.code === 'no_phone_system') return null
      throw e
    }
  }, [api, base])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const change = async (fn: (d: Draft) => Draft): Promise<boolean> => {
    if (!ps.data) return false
    setSaving(true); setError(null)
    try {
      await api.put(`${base}/phone-system/draft`, { document: fn(structuredClone(ps.data.draft)) })
      await ps.reload()
      return true
    } catch (e) {
      const errs = e instanceof ApiError ? (e.data?.errors as { path: string; message: string }[] | undefined) : undefined
      setError(errs?.length ? errs.map((x) => `${x.path}: ${x.message}`).join('; ') : e instanceof Error ? e.message : String(e))
      return false
    } finally { setSaving(false) }
  }
  return { ps, draft: ps.data?.draft ?? null, change, saving, error, canBuild: can('vox.phone_system.build'), base }
}

/** Where a call goes: a user, a ring group, a menu or a mailbox from this draft. */
export function TargetPicker({ id, label, draft, value, onChange, allowNone, peopleOnly }:
  { id: string; label: string; draft: Draft; value: TargetValue; onChange: (v: TargetValue) => void; allowNone?: string; peopleOnly?: boolean }) {
  const users = Object.entries(draft.users ?? {})
  const boxes = Object.entries((draft.boxes ?? {}) as Record<string, { name: string }>)
  return (
    <div className="ph-field">
      <label htmlFor={id}>{label}</label>
      <select id={id} className="ph-input" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{allowNone ?? 'Choose…'}</option>
        {users.length > 0 && <optgroup label="People">{users.map(([k, u]) => <option key={k} value={`user:${k}`}>{u.name} ({u.extension})</option>)}</optgroup>}
        {Object.keys(draft.groups ?? {}).length > 0 && <optgroup label="Ring groups">{Object.keys(draft.groups ?? {}).map((k) => <option key={k} value={`group:${k}`}>{k}</option>)}</optgroup>}
        {!peopleOnly && Object.keys((draft.menus ?? {}) as object).length > 0 && <optgroup label="Menus">{Object.keys(draft.menus as object).map((k) => <option key={k} value={`menu:${k}`}>{k}</option>)}</optgroup>}
        {!peopleOnly && <optgroup label="Voicemail">
          {boxes.map(([k, b]) => <option key={k} value={`voicemail:${k}`}>{b.name}</option>)}
          {users.map(([k, u]) => <option key={`vm-${k}`} value={`voicemail:${k}`}>{u.name}’s voicemail</option>)}
        </optgroup>}
      </select>
    </div>
  )
}

/** A target in words, for tables. */
export function targetText(draft: Draft, t?: Target | null): string {
  if (!t) return '—'
  const [kind, key] = [Object.keys(t)[0], Object.values(t)[0]]
  if (kind === 'user') return draft.users?.[key]?.name ?? key
  if (kind === 'group') return `Ring group ${key}`
  if (kind === 'menu') return `Menu ${key}`
  const box = (draft.boxes as Record<string, { name: string }> | undefined)?.[key]
  return box ? box.name : `${draft.users?.[key]?.name ?? key}’s voicemail`
}

/** Site id -> name, from the directory's copy (the draft holds ids only). */
export function useSiteNames(): Record<string, string> {
  const { api } = useAuth()
  const { current } = useTenant()
  const sites = useLoad(() => api.get<Site[]>(`/tenants/${current!.id}/sites`), [api, current?.id])
  return Object.fromEntries((sites.data ?? []).map((x) => [x.id, x.name]))
}

/** After renaming a ring group, menu or mailbox, every target that named it follows (numbers, groups' next step, menus' keys and timeout). */
export function rename(d: Draft, kind: 'group' | 'menu' | 'voicemail', from: string, to: string): Draft {
  if (from === to || !from) return d
  const fix = (t?: Record<string, string> | null) => (t && t[kind] === from ? { [kind]: to } : t)
  return {
    ...d,
    numbers: Object.fromEntries(Object.entries(d.numbers ?? {}).map(([k, n]) => [k, { ...n, open: fix(n.open)!, ...(n.closed ? { closed: fix(n.closed) } : {}) }])),
    groups: Object.fromEntries(Object.entries(d.groups ?? {}).map(([k, g]) => [k, { ...g, ...(g.then ? { then: fix(g.then) } : {}) }])),
    menus: Object.fromEntries(Object.entries(d.menus ?? {}).map(([k, m]) => [k, { ...m, ...(m.timeout ? { timeout: fix(m.timeout)! } : {}),
      options: Object.fromEntries(Object.entries(m.options).map(([o, t]) => [o, fix(t)!])) }])),
    ...(d.doors ? { doors: Object.fromEntries(Object.entries(d.doors).map(([k, x]) => [k, { ...x, open: fix(x.open)!, ...(x.closed ? { closed: fix(x.closed) } : {}) }])) } : {}),
  }
}
