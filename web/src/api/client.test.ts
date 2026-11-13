import { describe, expect, it, vi } from 'vitest'
import { ApiError, createApi, describeError } from './client'

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status })

function api(fetchImpl: typeof fetch, token: string | null = 'tok', onUnauthorized = vi.fn()) {
  return { onUnauthorized, a: createApi({ baseUrl: 'https://x.test', getToken: async () => token, onUnauthorized, fetchImpl }) }
}

describe('describeError', () => {
  it('uses a string detail as is', () => expect(describeError(422, { detail: 'Slot is taken' })).toBe('Slot is taken'))
  it('uses the sentence the API wrote for a coded error', () =>
    expect(describeError(403, { detail: { code: 'outranked', detail: 'You can only limit people with a lower role than yours.' } })).toMatch(/lower role/))
  it('flattens FastAPI validation errors to field: message', () =>
    expect(describeError(422, { detail: [{ loc: ['body', 'width'], msg: 'must be > 0' }, { loc: ['body'], msg: 'bad' }] }))
      .toBe('width: must be > 0; bad'))
  it('falls back to friendly text by status', () => {
    expect(describeError(403, null)).toMatch(/permission/)
    expect(describeError(404, {})).toBe('Not found.')
    expect(describeError(429, {})).toMatch(/Too many/)
    expect(describeError(500, {})).toBe('Request failed (HTTP 500).')
  })
})

describe('createApi', () => {
  it('sends the bearer token and JSON body, and parses the response', async () => {
    const f = vi.fn(async () => json(200, { ok: 1 }))
    const { a } = api(f as unknown as typeof fetch)
    expect(await a.post('/things', { a: 1 })).toEqual({ ok: 1 })
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('https://x.test/things')
    expect(init.method).toBe('POST')
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer tok')
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json')
    expect(init.body).toBe('{"a":1}')
  })

  it('omits Authorization with no token and handles 204', async () => {
    const f = vi.fn(async () => new Response(null, { status: 204 }))
    const { a } = api(f as unknown as typeof fetch, null)
    expect(await a.put('/x')).toBeUndefined()
    await a.del('/x')
    expect(((f.mock.calls[0] as unknown as [string, RequestInit])[1].headers as Record<string, string>).Authorization).toBeUndefined()
  })

  it('on 401 calls onUnauthorized and throws a friendly error', async () => {
    const { a, onUnauthorized } = api((async () => json(401, {})) as unknown as typeof fetch)
    await expect(a.get('/me')).rejects.toMatchObject({ status: 401, detail: expect.stringMatching(/sign in again/) })
    expect(onUnauthorized).toHaveBeenCalledOnce()
  })

  it('turns API errors into ApiError with a readable detail', async () => {
    const { a } = api((async () => json(409, { detail: 'That slot is already booked' })) as unknown as typeof fetch)
    const err = await a.post('/b', {}).catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({ status: 409, message: 'That slot is already booked' })
  })

  it('tolerates a non-JSON error body', async () => {
    const { a } = api((async () => new Response('<html>', { status: 502 })) as unknown as typeof fetch)
    await expect(a.get('/x')).rejects.toMatchObject({ detail: 'Request failed (HTTP 502).' })
  })

  it('reports network failures plainly', async () => {
    const { a } = api((async () => { throw new TypeError('failed to fetch') }) as unknown as typeof fetch)
    await expect(a.get('/x')).rejects.toMatchObject({ status: 0, detail: expect.stringMatching(/Can’t reach the server/) })
  })

  it('blobUrl returns an object URL for protected files', async () => {
    URL.createObjectURL = vi.fn(() => 'blob:abc')
    const { a } = api((async () => new Response(new Blob(['x']), { status: 200 })) as unknown as typeof fetch)
    expect(await a.blobUrl('/img')).toBe('blob:abc')
  })

  it('handles an empty 200 body', async () => {
    const { a } = api((async () => new Response('', { status: 200 })) as unknown as typeof fetch)
    expect(await a.get('/x')).toBeUndefined()
  })
})
