export const useApi = () => {
  const config = useRuntimeConfig()
  const { initData } = useTelegram()
  const baseUrl = config.public.apiBase

  const fetchApi = async (path: string, options: RequestInit = {}) => {
    const url = `${baseUrl}${path}`
    const headers = {
      'Content-Type': 'application/json',
      'X-Init-Data': initData,
      ...((options.headers as Record<string, string>) ?? {})
    }
    const res = await fetch(url, { ...options, headers })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }))
      throw new Error(err.detail ?? 'API error')
    }
    return res.json()
  }

  const get = (path: string) => fetchApi(path)
  const post = (path: string, body?: unknown) =>
    fetchApi(path, { method: 'POST', body: JSON.stringify(body) })
  const put = (path: string, body?: unknown) =>
    fetchApi(path, { method: 'PUT', body: JSON.stringify(body) })
  const del = (path: string) => fetchApi(path, { method: 'DELETE' })

  return { get, post, put, del }
}
