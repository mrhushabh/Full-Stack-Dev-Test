import { useEffect, useState } from 'react'
import { api } from '../api'
import { hours as fmtHours, money, titleCase } from '../format'
import type { JobType, LaborRate, LevelProposal } from '../types'

/**
 * Adds a labour line, leading with what the tool thinks the answer is.
 *
 * The whole argument of this screen: minor versus major repair is $110/h over
 * 0.5-2h against $135/h over 2-6h -- a fifteen-fold spread behind one dropdown.
 * Asking a tech to pick blind invites an arbitrary answer to a question worth
 * hundreds of dollars. So the tool proposes, shows why, and puts the alternative
 * one tap away. It never decides: the tech is the expert on site and carries the
 * liability.
 */
export default function LaborEditor({
  proposals,
  onAdd,
  onClose,
}: {
  proposals: Record<string, LevelProposal>
  onAdd: (jobType: JobType, level: string) => void
  onClose: () => void
}) {
  const [rates, setRates] = useState<LaborRate[]>([])

  useEffect(() => {
    api.laborRates().then(setRates).catch(() => setRates([]))
  }, [])

  const jobTypes = [...new Set(rates.map((r) => r.jobType))]

  return (
    <div className="card">
      <header>
        <h2>Add labour</h2>
        <button className="btn ghost" onClick={onClose}>
          Done
        </button>
      </header>
      <div className="body stack-12">
        {jobTypes.map((jobType) => {
          const levels = rates.filter((r) => r.jobType === jobType)
          const proposal = proposals[jobType]
          return (
            <div key={jobType} className="stack-8">
              <div className="row-between">
                <strong style={{ fontSize: 15 }}>{titleCase(jobType)}</strong>
                {proposal && (
                  <span
                    className={`tag ${
                      proposal.confidence === 'high'
                        ? 'ok'
                        : proposal.confidence === 'low'
                          ? 'warn'
                          : ''
                    }`}
                  >
                    {proposal.confidence} confidence
                  </span>
                )}
              </div>

              {proposal && (
                <div className="proposal">
                  <div className="head">
                    <span className="tag brand">
                      Suggested · {titleCase(proposal.level)}
                    </span>
                  </div>
                  <div className="why">{proposal.reason}</div>
                  {proposal.alternatives.length > 0 && (
                    <div className="alts">
                      {proposal.alternatives.map((alt) => (
                        <div key={alt.level} className="tiny muted">
                          <strong>{titleCase(alt.level)}:</strong> {alt.reason}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              <div className="stack-8">
                {levels.map((rate) => {
                  const suggested = proposal?.level === rate.level
                  return (
                    <button
                      key={rate.level}
                      className={`btn block ${suggested ? 'primary' : ''}`}
                      style={{ justifyContent: 'space-between' }}
                      onClick={() => onAdd(jobType as JobType, rate.level)}
                    >
                      <span>{titleCase(rate.level)}</span>
                      <span className="small">
                        {money(rate.hourlyRate, false)}/hr ·{' '}
                        {fmtHours(rate.minHours)}–{fmtHours(rate.maxHours)}h
                      </span>
                    </button>
                  )
                })}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
