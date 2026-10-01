export type User = { id: number; email: string; display_name: string; role: 'admin' | 'recruiter'; active: boolean; ai_enabled: boolean; csrf_token: string }

export function candidateDisplay(candidate: { id: number; name?: string | null; external_id?: string | null }) {
  return candidate.name?.trim() || `Candidate ${candidate.external_id || candidate.id}`
}

let csrfToken = ''
export function setCsrf(value: string) { csrfToken = value }

export async function request<T>(url: string, options: RequestInit = {}): Promise<T> {
  const method = (options.method || 'GET').toUpperCase()
  const headers = new Headers(options.headers)
  if (!['GET', 'HEAD'].includes(method) && csrfToken && !url.startsWith('/api/auth/signin') && !url.startsWith('/api/auth/signup')) {
    headers.set('X-CSRF-Token', csrfToken)
  }
  const response = await fetch(url, { ...options, headers, credentials: 'same-origin' })
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`
    try { const payload = await response.json(); message = typeof payload.detail === 'string' ? payload.detail : message } catch { /* non-JSON response */ }
    throw new Error(message)
  }
  return response.json() as Promise<T>
}

export const json = (value: unknown, method = 'POST'): RequestInit => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value) })
