import { dollars, percent } from '../format'
import type { EstimateResponse } from '../types'

/**
 * Inline advice: warranty, sizing, and the repair-vs-replace comparison.
 *
 * These sit in the build flow rather than on a screen of their own, so the tech
 * meets them while still able to act on them. Each one states the arithmetic it
 * used -- advice a tech cannot check is advice a tech will stop trusting the
 * first time it is wrong in front of a customer.
 */
export default function Advisories({ result }: { result: EstimateResponse }) {
  const { repairVsReplace: rvr, sizing, warranty } = result
  const problems = sizing.filter((s) => s.verdict !== 'ok')

  return (
    <>
      {warranty.applies && (
        <div className="advice warn">
          <h3>Check the warranty first</h3>
          <p>{warranty.message}</p>
        </div>
      )}

      {problems.map((check) => (
        <div key={check.equipmentId} className="advice warn">
          <h3>
            {check.verdict === 'oversized' ? 'Oversized' : 'Undersized'} for this
            property
          </h3>
          <p>{check.message}</p>
        </div>
      ))}

      {rvr.triggered && rvr.option && (
        <div className={`advice ${rvr.recommendation === 'replace' ? 'replace' : 'consider'}`}>
          <h3>
            {rvr.recommendation === 'replace'
              ? 'Replacement is likely the better value'
              : 'Worth discussing replacement'}
          </h3>
          <p>{rvr.headline}</p>

          <div className="compare">
            <div>
              <div className="k">Repair</div>
              <div className="v">{dollars(rvr.repairTotal)}</div>
              <div className="n">Fix the current system</div>
            </div>
            <div>
              <div className="k">Replace</div>
              <div className="v">{dollars(rvr.replacementTotal)}</div>
              <div className="n">{rvr.option.equipmentName}</div>
            </div>
          </div>

          <ul style={{ marginTop: 10 }}>
            {rvr.reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </div>
      )}

      {/*
        Worth saying out loud when the comparison ran and repair won: it lets a
        tech tell a customer "I checked, and fixing it is the better value",
        which is a stronger position than not having looked.
      */}
      {!rvr.triggered && rvr.replacementTotal && (
        <div className="advice info">
          <h3>Repair is the better value</h3>
          <p className="muted small" style={{ margin: 0 }}>
            This repair is {percent(rvr.costRatio)} of the{' '}
            {dollars(rvr.replacementTotal)} cost of replacing the system, and the
            equipment is not near end of life.
          </p>
        </div>
      )}
    </>
  )
}
