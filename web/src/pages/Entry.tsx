import { useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import { useTenant } from '../auth/TenantContext'
import type { EntryToken } from '../api/types'
import { ErrorText, Loading } from '../components/ui'
import { useLoad } from '../lib/useLoad'

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : 'never')

/** The PhotonEntry connection (photonaccess docs/VOX.md): a token PhotonEntry uses to read this organization's door stations (with their SIP
 *  accounts) and who answered a door's call. Shown once, kept by PhotonVox only as a hash; revoking it disconnects PhotonEntry at once. */
export function EntryPage() {
  const { api } = useAuth()
  const { current } = useTenant()
  const base = `/tenants/${current!.id}/integrations/entry-tokens`
  const tokens = useLoad(() => api.get<EntryToken[]>(base), [api, base])
  const [made, setMade] = useState<EntryToken | null>(null)
  const [copied, setCopied] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const run = async (fn: () => Promise<void>) => {
    setBusy(true); setError(null)
    try { await fn() } catch (e) { setError(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) }
  }
  const make = () => run(async () => { setCopied(false); setMade(await api.post<EntryToken>(base, { label: 'PhotonEntry' })); await tokens.reload() })
  const revoke = (t: EntryToken) => run(async () => {
    if (!window.confirm('Revoke this token? PhotonEntry stops reading the doors until it is given a new one; the intercoms keep working.')) return
    await api.del(`${base}/${t.id}`); await tokens.reload()
  })
  const live = (tokens.data ?? []).filter((t) => !t.revoked_at)
  return (
    <section aria-label="PhotonEntry connection">
      <h2>PhotonEntry connection</h2>
      <p>PhotonEntry reads this organization’s doors (Call flows → Doors) to set up their intercoms, and asks who answered a door’s call so its
        log can say who opened the door. Make a token here and paste it into PhotonEntry (Settings → PhotonVox).</p>
      <ErrorText>{tokens.error ?? error}</ErrorText>
      {tokens.loading && !tokens.data && <Loading what="tokens" />}
      {made?.token && (
        <div className="ph-card pv-token" role="status">
          <p><strong>Copy this token now.</strong> PhotonVox does not keep it and cannot show it again.</p>
          <code className="pv-secret">{made.token}</code>
          <div className="ph-actions">
            <button className="ph-btn ph-btn-secondary ph-btn-sm" onClick={() => void navigator.clipboard?.writeText(made.token!).then(() => setCopied(true))}>
              {copied ? 'Copied' : 'Copy'}</button>
            <button className="ph-btn ph-btn-secondary ph-btn-sm" onClick={() => setMade(null)}>Done</button>
          </div>
        </div>
      )}
      {tokens.data && (live.length === 0 ? <p className="ph-hint">Not connected.</p> : (
        <ul className="pv-plain">{live.map((t) => (
          <li key={t.id}><strong>{t.label}</strong> <span className="ph-hint">…{t.hint}, made {when(t.created_at)}, last used {when(t.last_used_at)}</span>{' '}
            <button className="ph-btn ph-btn-danger ph-btn-sm" disabled={busy} onClick={() => void revoke(t)}>Revoke</button></li>
        ))}</ul>
      ))}
      <button className="ph-btn" disabled={busy || !tokens.data} onClick={() => void make()}>{live.length ? 'Make another token' : 'Make a token'}</button>
    </section>
  )
}
