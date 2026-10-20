async function decode(response) {
  if (!response.ok) {
    let message = `HTTP ${response.status}`
    try { const body = await response.json(); message = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail || body) }
    catch { /* Keep the HTTP status if the server did not return JSON. */ }
    throw new Error(message)
  }
  return response.json()
}
function queryString(params = {}) {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') query.set(key, String(value))
  })
  return query.toString()
}
async function request(path, params = {}) {
  return decode(await fetch(`/api${path}?${queryString(params)}`))
}
export const api = {
  health: () => request('/health'), syncStatus: () => request('/sync/status'), filters: () => request('/filters'),
  overview: (params) => request('/overview', params), documents: (params) => request('/documents', params),
  trace: (params) => request('/trace', params), suppliers: (params) => request('/suppliers', params),
  governance: () => request('/governance'), catalog: (params) => request('/catalog', params),
  previewCatalog: async (file, token, sheet = '') => decode(await fetch(`/api/catalog/preview?${queryString({ filename: file.name, sheet })}`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: file })),
  saveNote: async (data, token) => decode(await fetch('/api/documents/note', { method: 'PUT', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }, body: JSON.stringify(data) })),
  importCatalog: async (data, token) => decode(await fetch('/api/catalog/import', { method: 'POST', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }, body: JSON.stringify(data) })),
  exportUrl: (params) => `/api/export?${queryString(params)}`,
  catalogExportUrl: (params) => `/api/catalog/export?${queryString(params)}`,
}
