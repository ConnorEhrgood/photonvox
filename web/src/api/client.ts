import { RenewalError } from '../ph-auth/signin'

/** PhotonID could not be reached to renew the session (`RenewalError`): the session is kept, so this is a request to retry, never "signed out". */
export const RENEWAL_FAILED = 'Can’t reach PhotonID to renew your session. Check your connection and try again.'

export class ApiError extends Error {
  status: number
  detail: string
  /** Structured detail for errors the UI reacts to (e.g. `{code: 'insufficient_funds', balance_cents, price_cents}`). */
  data: Record<string, unknown> | null
  constructor(status: number, detail: string, data: Record<string, unknown> | null = null) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.data = data
  }
}

export interface Api {
  get<T>(path: string): Promise<T>
  post<T>(path: string, body?: unknown): Promise<T>
  put<T>(path: string, body?: unknown): Promise<T>
  patch<T>(path: string, body?: unknown): Promise<T>
  del(path: string): Promise<void>
  /** Fetches a protected file and returns an object URL for <img src>; the caller revokes it. */
  blobUrl(path: string): Promise<string>
}

export interface ApiOptions {
  baseUrl: string
  getToken: () => Promise<string | null>
  /** Called on 401 so the app can send the person back to sign in. */
  onUnauthorized: () => void
  fetchImpl?: typeof fetch
}

/** FastAPI errors are either `{detail: "text"}` or `{detail: [{loc, msg}, ...]}`; show people one sentence. */
export function describeError(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    const sentence = (detail as { detail?: unknown }).detail
    if (typeof sentence === 'string') return sentence    // {code, detail}: the API wrote a sentence for people
  }
  if (Array.isArray(detail) && detail.length > 0) {
    return detail
      .map((d: { loc?: unknown[]; msg?: string }) => {
        const field = Array.isArray(d.loc) ? d.loc.filter((p) => p !== 'body').join('.') : ''
        return field ? `${field}: ${d.msg ?? 'invalid'}` : (d.msg ?? 'invalid')
      })
      .join('; ')
  }
  if (status === 403) return 'You don’t have permission to do that.'
  if (status === 404) return 'Not found.'
  if (status === 429) return 'Too many attempts. Try again in a minute.'
  return `Request failed (HTTP ${status}).`
}

export function createApi(opts: ApiOptions): Api {
  const doFetch = opts.fetchImpl ?? ((...a: Parameters<typeof fetch>) => fetch(...a))

  async function raw(method: string, path: string, body?: BodyInit | null, json = false): Promise<Response> {
    let token: string | null
    try {
      token = await opts.getToken()
    } catch (e) {
      if (e instanceof RenewalError) throw new ApiError(0, RENEWAL_FAILED)
      throw e
    }
    const headers: Record<string, string> = {}
    if (token) headers.Authorization = `Bearer ${token}`
    if (json) headers['Content-Type'] = 'application/json'
    let res: Response
    try {
      res = await doFetch(`${opts.baseUrl}${path}`, { method, headers, body })
    } catch {
      throw new ApiError(0, 'Can’t reach the server. Check your connection and try again.')
    }
    if (res.status === 401) {
      opts.onUnauthorized()
      throw new ApiError(401, 'Your session has ended. Please sign in again.')
    }
    if (!res.ok) {
      let parsed: unknown = null
      try { parsed = await res.json() } catch { /* not JSON */ }
      const d = (parsed as { detail?: unknown } | null)?.detail
      throw new ApiError(res.status, describeError(res.status, parsed), d && typeof d === 'object' && !Array.isArray(d) ? (d as Record<string, unknown>) : null)
    }
    return res
  }

  async function parse<T>(res: Response): Promise<T> {
    if (res.status === 204) return undefined as T
    const text = await res.text()
    return (text ? JSON.parse(text) : undefined) as T
  }

  return {
    get: async (p) => parse(await raw('GET', p)),
    post: async (p, b) => parse(await raw('POST', p, b === undefined ? null : JSON.stringify(b), true)),
    put: async (p, b) => parse(await raw('PUT', p, b === undefined ? null : JSON.stringify(b), true)),
    patch: async (p, b) => parse(await raw('PATCH', p, b === undefined ? null : JSON.stringify(b), true)),
    del: async (p) => { await raw('DELETE', p) },
    blobUrl: async (p) => URL.createObjectURL(await (await raw('GET', p)).blob()),
  }
}
