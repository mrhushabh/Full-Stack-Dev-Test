import { useState } from 'react'
import type { PricingConfig } from '../types'

/**
 * The assumptions, on screen and editable.
 *
 * Nothing in the provided dataset states a margin, a tax rate or a replacement
 * threshold, so every one of these is a judgement call. Burying them as constants
 * would make the tool look more certain than it is; putting them here means a
 * reviewer can disagree with any of them and change it in five seconds.
 */
export default function SettingsPanel({
  config,
  onChange,
}: {
  config: PricingConfig
  onChange: (config: PricingConfig) => void
}) {
  const [open, setOpen] = useState(false)
  const set = <K extends keyof PricingConfig>(key: K, value: PricingConfig[K]) =>
    onChange({ ...config, [key]: value })

  const markupAtCost = Number(config.equipmentMarkup) === 1
  const taxOff = Number(config.taxRate) === 0

  return (
    <div className="card no-print">
      <header>
        <h2>Pricing assumptions</h2>
        <button className="btn ghost" onClick={() => setOpen(!open)}>
          {open ? 'Hide' : 'Edit'}
        </button>
      </header>

      {!open && (
        <div className="body wrap">
          {/* Formatted rather than printed raw: the value arrives as "1" or
              "1.4" depending on the backend's decimal scale. */}
          <span className={`tag ${markupAtCost ? 'warn' : 'brand'}`}>
            markup {Number(config.equipmentMarkup).toFixed(2)}×
          </span>
          <span className={`tag ${taxOff ? 'warn' : 'brand'}`}>
            tax {(Number(config.taxRate) * 100).toFixed(2)}%
          </span>
          <span className={`tag ${config.creditDiagnosticOnApproval ? 'ok' : ''}`}>
            diagnostic {config.creditDiagnosticOnApproval ? 'waived' : 'billed'}
          </span>
        </div>
      )}

      {open && (
        <div className="body stack-12">
          <div className="grid2">
            <label className="stack">
              Equipment markup
              <input
                className="field"
                type="number"
                step="0.05"
                min="1"
                max="5"
                value={config.equipmentMarkup}
                onChange={(e) => set('equipmentMarkup', e.target.value)}
              />
            </label>
            <label className="stack">
              Sales tax %
              <input
                className="field"
                type="number"
                step="0.25"
                min="0"
                max="25"
                value={(Number(config.taxRate) * 100).toFixed(2)}
                onChange={(e) =>
                  set('taxRate', String(Number(e.target.value) / 100))
                }
              />
            </label>
          </div>

          <p className="tiny muted" style={{ margin: 0 }}>
            The catalog field is named <code>baseCost</code>, which reads as a
            wholesale figure, while the labour rates are described as what the
            company charges. The two are priced on different bases. Markup defaults
            to 1.0× so the tool never quietly inflates a bill on a guess — set it
            to the real number and every estimate updates.
          </p>

          <div>
            <div className="switch">
              <span>Waive diagnostic when the repair is approved</span>
              <input
                type="checkbox"
                checked={config.creditDiagnosticOnApproval}
                onChange={(e) =>
                  set('creditDiagnosticOnApproval', e.target.checked)
                }
              />
            </div>
            <div className="switch">
              <span>Apply tax to labour</span>
              <input
                type="checkbox"
                checked={config.taxAppliesToLabor}
                onChange={(e) => set('taxAppliesToLabor', e.target.checked)}
              />
            </div>
          </div>

          <div className="grid2">
            <label className="stack">
              End of life (years)
              <input
                className="field"
                type="number"
                min="5"
                max="40"
                value={config.endOfLifeYears}
                onChange={(e) => set('endOfLifeYears', Number(e.target.value))}
              />
            </label>
            <label className="stack">
              Replace at % of new
              <input
                className="field"
                type="number"
                step="5"
                min="10"
                max="100"
                value={Math.round(Number(config.replaceCostRatio) * 100)}
                onChange={(e) =>
                  set('replaceCostRatio', String(Number(e.target.value) / 100))
                }
              />
            </label>
          </div>
        </div>
      )}
    </div>
  )
}
