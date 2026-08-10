import { useState } from 'react'
import { dollars, jobLabel, money } from '../format'
import type { EstimateResponse, EstimateStatus } from '../types'

/**
 * Step 4 -- the screen the tech turns around.
 *
 * The README complains twice about presentation, not arithmetic: writing it up
 * "in a way the customer can actually read", and a wait that "makes the whole
 * experience feel less professional". So this is a deliberate boundary, not a
 * print stylesheet -- internal warnings, cost prices, markup and the confidence
 * ratings all stop here.
 *
 * It leads with one number rather than a range. "$1,400 to $2,900" reads to a
 * customer as "the tech does not know"; the range is still shown underneath,
 * because hiding it would be dishonest the moment the job runs long.
 */
export default function PresentStep({
  result,
  onSave,
  onDone,
}: {
  result: EstimateResponse
  onSave: (status: EstimateStatus) => Promise<void>
  onDone: () => void
}) {
  const { estimate, customer } = result
  const { totals } = estimate
  const spread = totals.low.total !== totals.high.total

  const [saving, setSaving] = useState<EstimateStatus | null>(null)
  const [saved, setSaved] = useState<EstimateStatus | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function save(status: EstimateStatus) {
    setSaving(status)
    setError(null)
    try {
      await onSave(status)
      setSaved(status)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(null)
    }
  }

  return (
    <>
      <div className="present">
        <div className="head">
          <div className="who">{customer?.name ?? 'Service estimate'}</div>
          {customer && <div className="where">{customer.address}</div>}
        </div>

        <div className="hero">
          <div className="k">Estimated total</div>
          <div className="v">{dollars(totals.expected.total)}</div>
          {spread && (
            <div className="r">
              Typically {dollars(totals.low.total)} – {dollars(totals.high.total)}{' '}
              depending on what we find
            </div>
          )}
        </div>

        {estimate.equipmentLines.length > 0 && (
          <div className="sec">
            <h3>Parts &amp; equipment</h3>
            {estimate.equipmentLines.map((line) => (
              <div key={line.equipmentId} className="row">
                <span>
                  {line.name}
                  {line.quantity > 1 && ` × ${line.quantity}`}
                </span>
                <span className="amt">{money(line.total)}</span>
              </div>
            ))}
          </div>
        )}

        {estimate.laborLines.length > 0 && (
          <div className="sec">
            <h3>Labour</h3>
            {estimate.laborLines.map((line, index) => (
              <div key={index} className="row">
                <span>
                  {jobLabel(line.jobType, line.level)}
                  <span className="muted"> · {line.hours} hrs</span>
                </span>
                <span className="amt">{money(line.total)}</span>
              </div>
            ))}
          </div>
        )}

        {estimate.miscLines.length > 0 && (
          <div className="sec">
            <h3>Materials</h3>
            {estimate.miscLines.map((line) => (
              <div key={line.description} className="row">
                <span>{line.description}</span>
                <span className="amt">{money(line.amount)}</span>
              </div>
            ))}
          </div>
        )}

        <div className="sec">
          <div className="row">
            <span>Subtotal</span>
            <span className="amt">{money(totals.expected.subtotal)}</span>
          </div>

          {Number(totals.expected.diagnosticCredit) > 0 && (
            <div className="row credit">
              <span>Diagnostic fee waived</span>
              <span className="amt">
                −{money(totals.expected.diagnosticCredit)}
              </span>
            </div>
          )}

          {Number(totals.expected.tax) > 0 && (
            <div className="row">
              <span>Tax</span>
              <span className="amt">{money(totals.expected.tax)}</span>
            </div>
          )}

          <div className="row total">
            <span>Total</span>
            <span className="amt">{money(totals.expected.total)}</span>
          </div>
        </div>

        <div className="fine">
          {spread &&
            'Final cost depends on the hours the job actually takes; the range above is the expected span. '}
          {Number(totals.expected.diagnosticCredit) > 0 &&
            'The diagnostic fee is waived because the work was approved today. '}
          {Number(totals.expected.tax) === 0 && 'Tax is not included. '}
          This estimate is valid for 30 days.
        </div>
      </div>

      <button className="btn block no-print" onClick={() => window.print()}>
        Print / save as PDF
      </button>

      {/*
        What happens next. Nothing has been stored up to this point -- most
        quotes are conversations, not records, and a history cluttered with every
        number ever shown on a doorstep is a history nobody reads. The estimate
        only reaches the database when the tech says it went somewhere.
      */}
      <div className="card no-print">
        <header>
          <h2>What did they say?</h2>
        </header>
        <div className="body stack-8">
          {error && <div className="banner">{error}</div>}

          {saved ? (
            <>
              <div className="row-between">
                <span className={`tag ${saved === 'approved' ? 'ok' : 'warn'}`}>
                  {saved === 'approved' ? 'Approved' : 'On hold'}
                </span>
                <span className="small muted">Saved to their record</span>
              </div>
              <button className="btn primary block" onClick={onDone}>
                Done
              </button>
            </>
          ) : !customer ? (
            <>
              <p className="small muted" style={{ margin: 0 }}>
                This is a walk-up quote, so there's no record to save it to. Add
                the property as a customer if you want to keep it.
              </p>
              <button className="btn block" onClick={onDone}>
                Done
              </button>
            </>
          ) : (
            <>
              <button
                className="btn primary block"
                disabled={saving !== null}
                onClick={() => save('approved')}
              >
                {saving === 'approved' ? 'Saving…' : 'Going ahead — save it'}
              </button>
              <button
                className="btn block"
                disabled={saving !== null}
                onClick={() => save('held')}
              >
                {saving === 'held' ? 'Saving…' : 'Thinking about it — hold'}
              </button>
              <button className="btn ghost block" onClick={onDone}>
                Not interested — discard
              </button>
            </>
          )}
        </div>
      </div>
    </>
  )
}
