import { useState } from 'react'
import { api } from '../api'
import { money } from '../format'
import type { SavedEstimateSummary } from '../types'

/**
 * Prior estimates for this customer.
 *
 * Only ones the tech acted on appear here, which is what makes the list worth
 * reading: every row is a job that was either approved or is still open. "We
 * quoted them $3,300 in March and they held off" is exactly the context you want
 * before starting the next conversation.
 */
export default function EstimateHistory({
  estimates,
  onChanged,
}: {
  estimates: SavedEstimateSummary[]
  onChanged: () => void
}) {
  const [busy, setBusy] = useState<string | null>(null)

  if (estimates.length === 0) return null

  async function remove(id: string) {
    setBusy(id)
    try {
      await api.deleteEstimate(id)
      onChanged()
    } finally {
      setBusy(null)
    }
  }

  async function approve(id: string) {
    setBusy(id)
    try {
      await api.setEstimateStatus(id, 'approved')
      onChanged()
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="card no-print">
      <header>
        <h2>Previous estimates</h2>
        <span className="small muted">{estimates.length}</span>
      </header>

      {estimates.map((estimate) => (
        <div key={estimate.id} className="line">
          <div className="grow">
            <div className="row-between">
              <span className="t">{estimate.summary}</span>
              <span className={`tag ${estimate.status === 'approved' ? 'ok' : 'warn'}`}>
                {estimate.status === 'approved' ? 'approved' : 'on hold'}
              </span>
            </div>
            <div className="s">
              {new Date(estimate.createdAt).toLocaleDateString(undefined, {
                day: 'numeric',
                month: 'short',
                year: 'numeric',
              })}{' '}
              · {estimate.lineCount} line{estimate.lineCount === 1 ? '' : 's'}
            </div>
            {estimate.notes && <div className="s">{estimate.notes}</div>}

            <div className="qty">
              {estimate.status === 'held' && (
                <button
                  className="btn ghost"
                  disabled={busy === estimate.id}
                  onClick={() => approve(estimate.id)}
                >
                  Mark approved
                </button>
              )}
              <button
                className="btn ghost"
                style={{ marginLeft: 'auto', color: 'var(--danger)' }}
                disabled={busy === estimate.id}
                onClick={() => remove(estimate.id)}
              >
                Delete
              </button>
            </div>
          </div>
          <div className="amt">{money(estimate.total)}</div>
        </div>
      ))}
    </div>
  )
}
