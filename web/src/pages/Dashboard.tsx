import { useEffect, useMemo } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { useOrgPath, useTenant } from '../auth/TenantContext'
import { ApiError } from '../api/client'
import type { CallKind, Dashboard, HourMix } from '../api/types'
import { ErrorText, Loading, PageHeader, StatusBadge } from '../components/ui'
import { useLoad } from '../lib/useLoad'

/** How often the page asks again (the API caches ten seconds, so a wall of open dashboards asks the engine once). */
export const REFRESH_MS = 10_000

const KIND: Record<CallKind, string> = { inbound: 'Incoming', outbound: 'Outgoing', internal: 'Inside' }
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

const plural = (n: number, one: string, many = `${one}s`) => `${n.toLocaleString()} ${n === 1 ? one : many}`
const length = (s: number) => (s < 60 ? `${s}s` : s < 3600 ? `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}` : `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`)
const hourName = (h: number) => (h === 0 ? '12 am' : h < 12 ? `${h} am` : h === 12 ? '12 pm' : `${h - 12} pm`)
const timeIn = (iso: string | null | undefined, tz?: string) =>
  iso ? new Date(iso).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: tz }) : null
/** A time today as "3:10 PM"; an earlier one says which day ("yesterday 6:28 PM", "Nov 10, 6:28 PM"), in the site's time zone. */
export function whenIn(iso: string | null | undefined, tz?: string, now: Date = new Date()): string | null {
  if (!iso) return null
  const day = (d: Date) => d.toLocaleDateString('en-CA', { timeZone: tz })
  const t = new Date(iso)
  const time = timeIn(iso, tz)
  if (day(t) === day(now)) return time
  if (day(t) === day(new Date(now.getTime() - 864e5))) return `yesterday ${time}`
  return `${t.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: tz })}, ${time}`
}
const phone = (n: string) => {
  const d = n.replace(/\D/g, '').slice(-10)
  return d.length === 10 ? `(${d.slice(0, 3)}) ${d.slice(3, 6)}-${d.slice(6)}` : n
}

/** "about the same as a usual Thursday by now", or "12 more than …": today against the last four of the same weekday up to this time. */
export function versus(today: number, usual: number | null | undefined, weekday: string, unit = ''): string | null {
  if (usual === null || usual === undefined) return null
  const diff = Math.round(today - usual)
  const near = Math.max(2, Math.round(usual * 0.15))
  if (Math.abs(diff) <= near) return `About the same as a usual ${weekday} by now`
  return `${Math.abs(diff).toLocaleString()}${unit} ${diff > 0 ? 'more' : 'fewer'} than a usual ${weekday} by now`
}

/** The customer dashboard: what is going on in the phone system right now and today, for the whole organization or one site. */
export function DashboardPage() {
  const { api } = useAuth()
  const { current, can } = useTenant()
  const at = useOrgPath()
  const [params, setParams] = useSearchParams()
  const site = params.get('site')
  const base = `/tenants/${current!.id}`
  const d = useLoad(async () => {
    try { return await api.get<Dashboard>(`${base}/dashboard${site ? `?site=${encodeURIComponent(site)}` : ''}`) } catch (e) {
      if (e instanceof ApiError && e.data?.code === 'no_phone_system') return { published: false, site: null, sites: [] } as Dashboard
      throw e
    }
  }, [api, base, site])
  useEffect(() => {
    const t = window.setInterval(() => { if (document.visibilityState === 'visible') void d.reload() }, REFRESH_MS)
    return () => window.clearInterval(t)
  }, [d.reload]) // eslint-disable-line react-hooks/exhaustive-deps

  const data = d.data
  const siteName = data?.sites.find((s) => s.id === data.site)?.name
  const title = siteName ?? current!.name
  if (!data) return <><PageHeader title={title} />{d.error ? <ErrorText>{d.error}</ErrorText> : <Loading what="the dashboard" />}</>
  if (!data.published) {
    return (
      <>
        <PageHeader title={title} />
        <div className="ph-empty pv-notyet">
          <p>The dashboard fills in once the phone system is running: calls, phones and voicemail, live.</p>
          {can('vox.phone_system.build') && <Link className="ph-btn" to={at('/phone-system')}>Set up the phone system</Link>}
        </div>
      </>
    )
  }
  const tz = data.timezone
  const missing = new Set(data.unavailable ?? [])
  return (
    <div className="pv-dash">
      <PageHeader title={title}>
        <span className="ph-hint" aria-live="polite">Updated {timeIn(data.as_of, tz)}</span>
      </PageHeader>
      {data.sites.length > 1 && (
        <nav className="ph-tabs pv-dash-sites" aria-label="Sites">
          {[{ id: '', slug: '', name: 'All sites' }, ...data.sites].map((s) => (
            <button key={s.id} type="button" className={(site ?? '') === s.slug ? 'active' : ''} aria-current={(site ?? '') === s.slug ? 'page' : undefined}
              onClick={() => setParams(s.slug ? { site: s.slug } : {})}>{s.name}</button>
          ))}
        </nav>
      )}
      <ErrorText>{d.error}</ErrorText>
      <Emergency data={data} />

      <section aria-labelledby="now" className="pv-dash-section">
        <h2 id="now" className="pv-dash-h">Right now</h2>
        <div className="pv-dash-now">
          <CallsNow data={data} unavailable={missing.has('live')} />
          <div className="pv-dash-side">
            <Phones data={data} unavailable={missing.has('live')} />
            <Lines data={data} unavailable={missing.has('live')} />
            <Trunk data={data} />
          </div>
        </div>
      </section>

      <section aria-labelledby="today" className="pv-dash-section">
        <h2 id="today" className="pv-dash-h">Today</h2>
        <Today data={data} voicemailMissing={missing.has('voicemail')} />
        {data.today && data.typical && <ByHour today={data.today.by_hour} usual={data.typical.by_hour} weekday={data.typical.weekday} days={data.typical.days} />}
        <div className="pv-dash-pair">
          {data.today && data.week && <Mix today={data.today} week={data.week} />}
          <Voicemail data={data} unavailable={missing.has('voicemail')} />
        </div>
      </section>

      {data.busiest && (
        <section aria-labelledby="busiest" className="pv-dash-section">
          <h2 id="busiest" className="pv-dash-h">Busiest hours <small className="ph-hint">the last four weeks</small></h2>
          <Busiest grid={data.busiest.grid} top={data.busiest.top} />
        </section>
      )}

      <section aria-labelledby="numbers" className="pv-dash-section">
        <h2 id="numbers" className="pv-dash-h">Numbers</h2>
        <Numbers data={data} />
      </section>

      {data.phone_system && (
        <p className="ph-hint pv-dash-foot">
          Phone system {data.phone_system.status === 'ready' ? 'up to date' : data.phone_system.status === 'changed' ? 'changed outside PhotonVox' : data.phone_system.status},
          version {data.phone_system.version}.{' '}
          {can('vox.phone_system.view') && <Link to={at('/phone-system')}>Phone system details</Link>}
        </p>
      )}
    </div>
  )
}

function Emergency({ data }: { data: Dashboard }) {
  if (!data.emergency || data.emergency.length === 0) return null
  return (
    <section className="ph-banner ph-banner-error pv-dash-emergency" role="alert" aria-label="Emergency calls today">
      <h2 className="pv-dash-h">{data.emergency.length === 1 ? 'An emergency call today' : `${data.emergency.length} emergency calls today`}</h2>
      <ul className="pv-plain">
        {data.emergency.map((e) => (
          <li key={e.at + e.dialed}>
            <strong>{timeIn(e.at, data.timezone)}</strong>: {e.who ? `${e.who}${e.extension ? ` (${e.extension})` : ''}` : 'a phone'} dialed {e.dialed}
            {e.site && <> at {e.site}</>}. {e.answered ? `Connected for ${length(e.seconds)}.` : 'It did not connect.'}
            {e.address && <><br /><span className="ph-hint">The location given to 911: {e.address}</span></>}
          </li>
        ))}
      </ul>
    </section>
  )
}

function CallsNow({ data, unavailable }: { data: Dashboard; unavailable: boolean }) {
  const now = data.now
  return (
    <div className="ph-card pv-dash-card pv-dash-calls">
      <div className="pv-dash-big"><b>{now ? now.count : '—'}</b><span>{now && now.count === 1 ? 'call in progress' : 'calls in progress'}</span></div>
      {unavailable && <p className="ph-hint">The live view of this phone system isn’t switched on yet.</p>}
      {now && now.calls.length === 0 && <p className="ph-hint">Nobody is on the phone.</p>}
      {now && now.calls.length > 0 && (
        <ul className="pv-dash-list">
          {now.calls.slice(0, 8).map((c, i) => (
            <li key={i}>
              <span className={`pv-dash-kind pv-dash-${c.kind}`}>{KIND[c.kind]}</span>
              <span className="pv-dash-who">
                {c.who[0] ? `${c.who[0].name}` : c.kind === 'inbound' ? 'Ringing in' : 'A phone'}
                <span className="ph-hint">
                  {c.kind === 'internal' ? (c.other ? ` with ${c.other}` : '') : c.other ? ` ${c.kind === 'inbound' ? 'from' : 'to'} ${c.other}` : ''}
                  {c.number ? ` on ${phone(c.number)}` : ''}
                </span>
              </span>
              <span className="pv-dash-time">{c.state === 'ringing' ? 'ringing' : length(c.seconds)}</span>
            </li>
          ))}
        </ul>
      )}
      {now && now.calls.length > 8 && <p className="ph-hint">and {now.calls.length - 8} more</p>}
    </div>
  )
}

function Phones({ data, unavailable }: { data: Dashboard; unavailable: boolean }) {
  const p = data.phones
  const all = p && p.total > 0 && p.online === p.total
  return (
    <div className="ph-card pv-dash-card">
      <div className="pv-dash-big pv-dash-small"><b>{p ? `${p.online} of ${p.total}` : '—'}</b><span>phones online</span></div>
      {unavailable && <p className="ph-hint">Not available yet.</p>}
      {p && p.total > 0 && <Meter value={p.online} max={p.total} tone={all ? 'ok' : p.online / p.total >= 0.8 ? 'warning' : 'error'} label={`${p.online} of ${p.total} phones online`} />}
      {p && p.offline.length > 0 && (
        <p className="ph-hint pv-dash-offline">Offline: {p.offline.slice(0, 6).map((o) => `${o.name} (${o.extension})`).join(', ')}{p.offline.length > 6 ? ` and ${p.offline.length - 6} more` : ''}</p>
      )}
      {all && <p className="ph-hint">Every phone is connected.</p>}
    </div>
  )
}

function Lines({ data, unavailable }: { data: Dashboard; unavailable: boolean }) {
  return (
    <div className="ph-card pv-dash-card">
      <div className="pv-dash-big pv-dash-small"><b>{data.now && !unavailable ? data.now.lines : '—'}</b><span>outside lines in use</span></div>
      {data.today && <p className="ph-hint">Most at once today: {data.today.peak_lines}</p>}
    </div>
  )
}

function Trunk({ data }: { data: Dashboard }) {
  const t = data.trunk
  if (!t) return null
  const tone = t.state === 'ok' ? 'ok' : t.state === 'trouble' ? 'error' : 'info'
  return (
    <div className={`ph-card pv-dash-card pv-dash-trunk pv-dash-trunk-${t.state}`}>
      <StatusBadge tone={tone}>{t.state === 'ok' ? 'Working' : t.state === 'trouble' ? 'Trouble' : 'Unknown'}</StatusBadge>
      <p className="pv-dash-words">{t.words.replace(/since (\S+Z)/, (_m, iso: string) => `since ${timeIn(iso, data.timezone)}`)}</p>
      <p className="ph-hint">
        {t.last_in ? `Last answered call in: ${whenIn(t.last_in, data.timezone)}` : 'No answered call in yet'}
        {' · '}
        {t.last_out ? `out: ${whenIn(t.last_out, data.timezone)}` : 'none out yet'}
      </p>
    </div>
  )
}

function Meter({ value, max, tone, label }: { value: number; max: number; tone: 'ok' | 'warning' | 'error'; label: string }) {
  return (
    <div className="pv-meter" role="meter" aria-valuemin={0} aria-valuemax={max} aria-valuenow={value} aria-label={label}>
      <span className={`pv-meter-fill pv-tone-${tone}`} style={{ width: `${max ? (100 * value) / max : 0}%` }} />
    </div>
  )
}

function Today({ data, voicemailMissing }: { data: Dashboard; voicemailMissing: boolean }) {
  const t = data.today
  const ty = data.typical
  const wd = ty?.weekday ?? 'day'
  if (!t) return <p className="ph-hint">Today’s calls can’t be read right now.</p>
  const quiet = t.calls === 0
  return (
    <>
      <div className="pv-dash-tiles">
        <Tile value={t.calls.toLocaleString()} label={t.calls === 1 ? 'call' : 'calls'} note={versus(t.calls, ty?.calls_so_far, wd)} />
        <Tile value={t.minutes.toLocaleString()} label={t.minutes === 1 ? 'minute on the phone' : 'minutes on the phone'} note={versus(t.minutes, ty?.minutes_so_far, wd, ' min')} />
        <Tile value={t.missed.toLocaleString()} label={t.missed === 1 ? 'missed call' : 'missed calls'} tone={t.missed > 0 ? 'warning' : undefined}
          note={t.calls ? `${t.to_voicemail ? `${plural(t.to_voicemail, 'caller')} left voicemail · ` : ''}${Math.round((100 * t.answered) / t.calls)}% answered` : null} />
        <Tile value={data.voicemail ? data.voicemail.new.toLocaleString() : '—'} label={data.voicemail?.new === 1 ? 'voicemail waiting' : 'voicemails waiting'}
          tone={data.voicemail && data.voicemail.new > 0 ? 'info' : undefined} note={voicemailMissing ? 'Not available yet' : data.voicemail?.new ? 'not listened to yet' : 'All listened to'} />
      </div>
      {quiet && <p className="ph-hint">A quiet day so far.</p>}
    </>
  )
}

function Tile({ value, label, note, tone }: { value: string; label: string; note?: string | null; tone?: 'warning' | 'info' }) {
  return (
    <div className={`ph-stat pv-dash-tile${tone ? ` ph-edge ph-edge-${tone}` : ''}`}>
      <b>{value}</b><span>{label}</span>
      {note && <small className="ph-hint">{note}</small>}
    </div>
  )
}

/** Calls by hour today, stacked by kind, with a usual-day line; the hours shown run from the first to the last with any calls (at least 7 to 19). */
function ByHour({ today, usual, weekday, days }: { today: HourMix[]; usual: number[]; weekday: string; days: number }) {
  const totals = today.map((h) => h.inbound + h.outbound + h.internal)
  const busy = totals.map((v, i) => (v || usual[i] ? i : -1)).filter((i) => i >= 0)
  const from = Math.min(7, ...busy), to = Math.max(19, ...busy)
  const hours = Array.from({ length: to - from + 1 }, (_, i) => from + i)
  const max = Math.max(4, ...hours.map((h) => Math.max(totals[h], usual[h])))
  const W = 100 / hours.length
  const y = (v: number) => 100 - (90 * v) / max
  const line = hours.map((h, i) => `${i === 0 ? 'M' : 'L'}${(i + 0.5) * W},${y(usual[h])}`).join(' ')
  const peak = hours.reduce((a, h) => (totals[h] > totals[a] ? h : a), hours[0])
  const summary = `Calls by hour today: ${totals.reduce((a, b) => a + b, 0)} in all${totals[peak] ? `, the most at ${hourName(peak)} (${totals[peak]})` : ''}.`
  return (
    <figure className="ph-card pv-dash-card pv-chart">
      <figcaption className="pv-chart-head">
        <span>Calls by hour</span>
        <span className="pv-legend">
          <span><i className="pv-dash-inbound" />Incoming</span><span><i className="pv-dash-outbound" />Outgoing</span><span><i className="pv-dash-internal" />Inside</span>
          {days > 0 && <span><i className="pv-legend-line" />A usual {weekday}</span>}
        </span>
      </figcaption>
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="pv-chart-svg" role="img" aria-label={summary}>
        {[0.25, 0.5, 0.75].map((f) => <line key={f} x1="0" x2="100" y1={y(max * f)} y2={y(max * f)} className="pv-grid" />)}
        {hours.map((h, i) => {
          let base = 100
          return (['inbound', 'outbound', 'internal'] as CallKind[]).map((k) => {
            const hgt = (90 * today[h][k]) / max
            base -= hgt
            return hgt > 0 ? <rect key={`${h}${k}`} x={i * W + W * 0.15} width={W * 0.7} y={base} height={hgt} className={`pv-dash-${k}`} /> : null
          })
        })}
        {days > 0 && <path d={line} className="pv-usual" vectorEffect="non-scaling-stroke" />}
      </svg>
      <div className="pv-chart-axis" aria-hidden="true">
        {hours.map((h) => <span key={h}>{h % 3 === 0 ? hourName(h).replace(' ', '') : ''}</span>)}
      </div>
    </figure>
  )
}

function Mix({ today, week }: { today: HourMix; week: HourMix }) {
  const row = (label: string, m: HourMix) => {
    const all = m.inbound + m.outbound + m.internal
    return (
      <div className="pv-mix-row">
        <span className="pv-mix-label">{label}</span>
        <div className="pv-mix-bar" role="img" aria-label={`${label}: ${m.inbound} incoming, ${m.outbound} outgoing, ${m.internal} inside`}>
          {all === 0 ? <span className="pv-mix-none">no calls</span> : (['inbound', 'outbound', 'internal'] as CallKind[]).map((k) =>
            m[k] ? <span key={k} className={`pv-dash-${k}`} style={{ width: `${(100 * m[k]) / all}%` }}>{(100 * m[k]) / all >= 12 ? m[k] : ''}</span> : null)}
        </div>
      </div>
    )
  }
  return (
    <div className="ph-card pv-dash-card">
      <h3 className="pv-dash-h3">Incoming, outgoing and inside</h3>
      {row('Today', today)}
      {row('7 days', week)}
      <p className="pv-legend"><span><i className="pv-dash-inbound" />Incoming</span><span><i className="pv-dash-outbound" />Outgoing</span><span><i className="pv-dash-internal" />Inside (phone to phone)</span></p>
    </div>
  )
}

function Voicemail({ data, unavailable }: { data: Dashboard; unavailable: boolean }) {
  const v = data.voicemail
  return (
    <div className="ph-card pv-dash-card">
      <h3 className="pv-dash-h3">Voicemail waiting</h3>
      {unavailable && <p className="ph-hint">Not available yet.</p>}
      {v && v.boxes.length === 0 && <p className="ph-hint">No new messages.</p>}
      {v && v.boxes.length > 0 && (
        <ul className="pv-dash-list">
          {v.boxes.slice(0, 6).map((b) => (
            <li key={b.box}>
              <span className="pv-dash-who">{b.name}<span className="ph-hint"> {b.box}</span></span>
              <span className="pv-dash-time">{plural(b.new, 'new', 'new')}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Busiest({ grid, top }: { grid: number[][]; top: { weekday: number; hour: number; calls: number } | null }) {
  const hours = useMemo(() => {
    const used = Array.from({ length: 24 }, (_, h) => grid.some((d) => d[h] > 0) ? h : -1).filter((h) => h >= 0)
    const from = Math.min(7, ...used), to = Math.max(19, ...used)
    return Array.from({ length: to - from + 1 }, (_, i) => from + i)
  }, [grid])
  const max = Math.max(1, ...grid.flat())
  if (!top) return <p className="ph-hint">Not enough calls yet to show a pattern.</p>
  return (
    <div className="ph-card pv-dash-card">
      <p className="pv-dash-words">Busiest: <strong>{['Mondays', 'Tuesdays', 'Wednesdays', 'Thursdays', 'Fridays', 'Saturdays', 'Sundays'][top.weekday]} around {hourName(top.hour)}</strong>{' '}
        <span className="ph-hint">({top.calls} calls in that hour on average)</span></p>
      <div className="pv-heat" style={{ gridTemplateColumns: `2.5rem repeat(${hours.length}, minmax(0, 1fr))` }} role="img"
        aria-label={`Calls by weekday and hour over the last four weeks; busiest ${DAYS[top.weekday]} at ${hourName(top.hour)}`}>
        <span />
        {hours.map((h) => <span key={h} className="pv-heat-hour">{h % 3 === 0 ? hourName(h).replace(' ', '') : ''}</span>)}
        {DAYS.map((day, di) => [
          <span key={day} className="pv-heat-day">{day}</span>,
          ...hours.map((h) => (
            <span key={`${day}${h}`} className="pv-heat-cell" title={`${day} ${hourName(h)}: ${grid[di][h]} calls on average`}
              style={{ opacity: grid[di][h] ? 0.15 + (0.85 * grid[di][h]) / max : 1 }} data-empty={grid[di][h] ? undefined : ''} />
          )),
        ])}
      </div>
    </div>
  )
}

function Numbers({ data }: { data: Dashboard }) {
  const ns = data.numbers ?? []
  if (ns.length === 0) return <p className="ph-hint">No numbers at this site.</p>
  return (
    <div className="ph-table-wrap">
      <table className="ph-table pv-table">
        <thead><tr><th>Number</th><th>Rings</th><th>Calls today</th><th>Last call</th></tr></thead>
        <tbody>
          {ns.map((n) => (
            <tr key={n.number}>
              <td data-label="Number" className="pv-who"><strong>{phone(n.number)}</strong>{n.site && data.sites.length > 1 && !data.site && <><br /><small className="ph-hint">{n.site}</small></>}</td>
              <td data-label="Rings">{n.rings}{n.closed && <><br /><small className="ph-hint">after hours: {n.closed}</small></>}</td>
              <td data-label="Calls today">{n.calls_today}</td>
              <td data-label="Last call">{timeIn(n.last_call, data.timezone) ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
