import { useCallback, useEffect, useRef, useState } from 'react'

export interface Loaded<T> {
  data: T | null
  error: string | null
  loading: boolean
  reload: () => Promise<void>
}

/** Runs `fn` on mount and whenever `deps` change; ignores results that arrive after a newer request. */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[]): Loaded<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const seq = useRef(0)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(fn, deps)

  const reload = useCallback(async () => {
    const mine = ++seq.current
    setLoading(true)
    try {
      const v = await run()
      if (mine === seq.current) { setData(v); setError(null) }
    } catch (e) {
      if (mine === seq.current) setError(e instanceof Error ? e.message : String(e))
    } finally {
      if (mine === seq.current) setLoading(false)
    }
  }, [run])

  useEffect(() => { void reload() }, [reload])
  return { data, error, loading, reload }
}
