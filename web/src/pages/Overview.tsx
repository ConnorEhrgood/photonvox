import { useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import { useTenant } from '../auth/TenantContext'
import { ApiError } from '../api/client'
import type { EmergencyState, PhoneSystemStatus, PhoneSystemSummary, Version } from '../api/types'
import { ErrorText, Loading, PageHeader, StatusBadge } from '../components/ui'
import { ago } from '../lib/format'
import { useLoad } from '../lib/useLoad'
import { SetupWizard } from './Setup'

const STATUS: Record<PhoneSystemStatus, { tone: 'ok' | 'info' | 'warning' | 'error'; text: string }> = {
  new: { tone: 'info', text: 'Not published yet' },
  publishing: { tone: 'info', text: 'Publishing…' },
  ready: { tone: 'ok', text: 'Ready' },
  failed: { tone: 'error', text: 'Last publish failed' },
  changed: { tone: 'warning', text: 'Changed outside PhotonVox' },
}

const NUMBER_STATUS = { confirmed: ['ok', '911 address confirmed'], requested: ['info', '911 address sent to the carrier'], unconfirmed: ['warning', '911 address unconfirmed'] } as const

/** One customer: its phone system at a glance, publishing it, its versions (undo), and its numbers' 911 addresses with the carrier. */
export function OverviewPage() {
  const { api } = useAuth()
  const { current, can } = useTenant()
  const base = `/tenants/${current!.id}`
  const ps = useLoad(async () => {
    try { return await api.get<PhoneSystemSummary>(`${base}/phone-system`) } catch (e) {
      if (e instanceof ApiError && e.data?.code === 'no_phone_system') return null
      throw e
    }
  }, [api, base])
  const versions = useLoad(() => (ps.data ? api.get<Version[]>(`${base}/phone-system/versions`) : Promise.resolve([])), [api, base, ps.data?.id, ps.data?.status])
  const e911 = useLoad(() => (ps.data ? api.get<EmergencyState>(`${base}/emergency`) : Promise.resolve(null)), [api, base, ps.data?.id, ps.data?.status])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [wizard, setWizard] = useState(false)
  const build = can('vox.phone_system.build')

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true); setError(null)
    try { await fn(); await ps.reload(); await versions.reload() } catch (e) { setError(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) }
  }
  const start = () => act(async () => { await api.post(`${base}/phone-system`); setWizard(true) })

  if (ps.loading && ps.data === null && !ps.error) return <><PageHeader title={current!.name} /><Loading what="the phone system" /></>
  if (ps.data === null) return (
    <>
      <PageHeader title={current!.name} />
      <ErrorText>{ps.error ?? error}</ErrorText>
      <div className="ph-empty pv-notyet">
        <p>{current!.name} has no phone system yet. Set it up from a template in a few minutes: a site and its emergency address, the main number, and the people.</p>
        {build ? <button className="ph-btn" disabled={busy} onClick={() => void start()}>Set up the phone system</button>
          : <p className="ph-hint">Your partner or an administrator sets it up.</p>}
      </div>
    </>
  )
  const p = ps.data
  const empty = !p.draft.users || Object.keys(p.draft.users).length === 0
  const s = STATUS[p.status]
  const inFlight = versions.data?.some((v) => v.state === 'queued' || v.state === 'publishing')
  return (
    <>
      <PageHeader title={current!.name}>
        {build && <button className="ph-btn ph-btn-secondary" onClick={() => setWizard(true)}>{empty ? 'Set up from a template' : 'Start again from a template'}</button>}
        {build && !empty && (
          <button className="ph-btn" disabled={busy || p.problems.length > 0 || inFlight} onClick={() => void act(() => api.post(`${base}/phone-system/publish`))}>Publish</button>
        )}
      </PageHeader>
      <ErrorText>{error}</ErrorText>
      <dl className="ph-kv">
        <dt>Phone system</dt><dd><StatusBadge tone={s.tone}>{s.text}</StatusBadge>{p.published_version ? <span className="ph-hint"> version {p.published_version} running</span> : null}</dd>
        <dt>Users</dt><dd>{Object.keys(p.draft.users ?? {}).length}</dd>
        <dt>Numbers</dt><dd>{Object.keys(p.draft.numbers ?? {}).length}</dd>
        <dt>Engine</dt><dd className="ph-hint">{p.domain}</dd>
      </dl>
      {p.status === 'changed' && (
        <div className="ph-banner ph-banner-warning" role="status">
          Someone changed this phone system on the engine by hand ({p.drift.changed} change{p.drift.changed === 1 ? '' : 's'}{p.drift.missing ? `, ${p.drift.missing} removed` : ''}).
          The next publish puts PhotonVox’s version back.
        </div>
      )}
      {p.drift.extra.length > 0 && (
        <p className="ph-hint">Added on the engine by hand, and left alone: {p.drift.extra.map((x) => x.label).join(', ')}.</p>
      )}
      {!empty && p.problems.length > 0 && (
        <section aria-label="Before it can be published">
          <h2>Before it can be published</h2>
          <ul>{p.problems.map((x) => <li key={x.path + x.code}>{x.message} <small className="ph-hint">({x.path})</small></li>)}</ul>
        </section>
      )}
      {e911.data && e911.data.numbers.length > 0 && (
        <section aria-label="911 addresses">
          <h2>911 addresses with the carrier</h2>
          <ul className="pv-plain">
            {e911.data.numbers.map((n) => {
              const [tone, text] = NUMBER_STATUS[n.status]
              return <li key={n.number}>{n.number} <StatusBadge tone={tone}>{text}</StatusBadge></li>
            })}
          </ul>
        </section>
      )}
      <Versions versions={versions.data ?? []} build={build} busy={busy || !!inFlight}
        restore={(n) => void act(() => api.post(`${base}/phone-system/versions/${n}/restore`))} />
      {wizard && <SetupWizard onClose={() => setWizard(false)} onDone={async () => { setWizard(false); await ps.reload() }} />}
    </>
  )
}

const VERSION_STATE: Record<Version['state'], { tone: 'ok' | 'info' | 'warning' | 'error'; text: string }> = {
  queued: { tone: 'info', text: 'Waiting' }, publishing: { tone: 'info', text: 'Publishing' }, ready: { tone: 'ok', text: 'Running' },
  failed: { tone: 'error', text: 'Failed' }, superseded: { tone: 'info', text: 'Earlier' },
}

/** A test call's finding in words: "reached group-desk" → "group-desk", "emergency <gateway> 911" → "out the emergency route, dialing 911". */
const said = (x: string) => {
  const [what, ...rest] = x.split(' ')
  if (what === 'reached') return rest.join(' ')
  if (what === 'blocked') return `blocked (${rest.join(' ')})`
  return `out the ${what} route, dialing ${rest[1] ?? '—'}`
}

function Versions({ versions, build, busy, restore }: { versions: Version[]; build: boolean; busy: boolean; restore: (n: number) => void }) {
  if (versions.length === 0) return null
  return (
    <section aria-label="Versions">
      <h2>Versions</h2>
      <div className="ph-table-wrap">
        <table className="ph-table pv-table">
          <thead><tr><th>Version</th><th>State</th><th>By</th><th>Check</th><th><span className="ph-sr-only">Undo</span></th></tr></thead>
          <tbody>
            {versions.map((v) => {
              const st = VERSION_STATE[v.state]
              return (
                <tr key={v.number}>
                  <td data-label="Version" className="pv-who"><strong>Version {v.number}</strong>{v.note && <><br /><small className="ph-hint">{v.note}</small></>}</td>
                  <td data-label="State"><StatusBadge tone={st.tone}>{st.text}</StatusBadge>{v.error && <><br /><small className="ph-error">{v.error}</small></>}</td>
                  <td data-label="By">{v.created_by}<br /><small className="ph-hint">{ago(v.published_at ?? v.created_at)}</small></td>
                  <td data-label="Check">{v.checks.total ? `${v.checks.passed} of ${v.checks.total} test calls passed` : '—'}
                    {v.checks.failed.map((f) => <div key={f.number}><small className="ph-error">{f.number}: should {f.kind === 'inbound' ? 'reach' : 'go'} {f.expected.map(said).join(' or ')}; {f.kind === 'inbound' ? 'reached' : 'went'} {f.got ? said(f.got) : 'nowhere'}</small></div>)}</td>
                  <td data-label="">{build && v.state === 'superseded' && (
                    <button className="ph-btn ph-btn-secondary ph-btn-sm" disabled={busy} onClick={() => restore(v.number)}>Go back to version {v.number}</button>)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}
