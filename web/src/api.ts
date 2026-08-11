import type {
  Customer,
  CustomerGuidance,
  Equipment,
  EstimateRequest,
  EstimateResponse,
  EstimateStatus,
  LaborRate,
  NewCustomer,
  Preset,
  PricingConfig,
  SavedEstimateSummary,
} from './types'

/**
 * Requests go to a relative /api path, proxied to FastAPI by the Vite dev server.
 * Nothing to configure, and no base URL to get wrong between environments.
 */
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })

  if (!response.ok) {
    // FastAPI puts a plain string in `detail` for our own errors and a list of
    // field errors there for schema failures. Surface whichever we got rather
    // than "[object Object]".
    let detail = `${response.status} ${response.statusText}`
    try {
      const body = await response.json()
      if (typeof body.detail === 'string') detail = body.detail
      else if (Array.isArray(body.detail)) {
        detail = body.detail
          .map((e: { loc?: string[]; msg: string }) =>
            e.loc ? `${e.loc.slice(1).join('.')}: ${e.msg}` : e.msg,
          )
          .join('; ')
      }
    } catch {
      /* non-JSON error body; keep the status line */
    }
    throw new Error(detail)
  }

  return response.json() as Promise<T>
}

export const api = {
  customers: (q?: string) =>
    request<Customer[]>(`/customers${q ? `?q=${encodeURIComponent(q)}` : ''}`),

  guidance: (customerId: string) =>
    request<CustomerGuidance>(`/customers/${customerId}/guidance`),

  equipment: (q?: string, category?: string) => {
    const params = new URLSearchParams()
    if (q) params.set('q', q)
    if (category) params.set('category', category)
    const query = params.toString()
    return request<Equipment[]>(`/equipment${query ? `?${query}` : ''}`)
  },

  categories: () => request<string[]>('/equipment/categories'),

  laborRates: () => request<LaborRate[]>('/labor-rates'),

  config: () => request<PricingConfig>('/config'),

  /** Persist the pricing assumptions for every future estimate. */
  saveConfig: (body: PricingConfig) =>
    request<PricingConfig>('/config', {
      method: 'PUT',
      body: JSON.stringify(body),
    }),

  presets: () => request<Preset[]>('/presets'),

  resolvePreset: (presetId: string, customerId: string | null) =>
    request<EstimateRequest>(
      `/presets/${presetId}/request${customerId ? `?customer_id=${customerId}` : ''}`,
    ),

  price: (body: EstimateRequest) =>
    request<EstimateResponse>('/estimates', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  createCustomer: (body: NewCustomer) =>
    request<Customer>('/customers', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  customerEstimates: (customerId: string) =>
    request<SavedEstimateSummary[]>(`/customers/${customerId}/estimates`),

  /**
   * Commits an estimate to the customer's record.
   *
   * Sends the line items, not a total: the server re-prices and stores what it
   * calculated. The browser is not the authority on what a job costs.
   */
  saveEstimate: (
    body: EstimateRequest,
    status: EstimateStatus,
    notes?: string | null,
  ) =>
    request<SavedEstimateSummary>('/estimates/save', {
      method: 'POST',
      body: JSON.stringify({ request: body, status, notes: notes ?? null }),
    }),

  setEstimateStatus: (estimateId: string, status: EstimateStatus) =>
    request<SavedEstimateSummary>(
      `/estimates/${estimateId}/status?status=${status}`,
      { method: 'PATCH' },
    ),

  deleteEstimate: async (estimateId: string) => {
    const response = await fetch(`/api/estimates/${estimateId}`, {
      method: 'DELETE',
    })
    if (!response.ok) throw new Error(`Could not delete estimate`)
  },
}
