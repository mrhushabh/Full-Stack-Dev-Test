import { useState } from 'react'
import { api } from '../api'
import { hours as fmtHours, jobLabel, money } from '../format'
import type {
  CustomerGuidance,
  EquipmentLineRequest,
  EstimateResponse,
  JobType,
  LaborLineRequest,
  PricingConfig,
} from '../types'
import Advisories from './Advisories'
import EquipmentPicker from './EquipmentPicker'
import EstimateHistory from './EstimateHistory'
import LaborEditor from './LaborEditor'
import PresetPicker from './PresetPicker'
import SettingsPanel from './SettingsPanel'

/** Step 3 -- build the line items. */
export default function BuildStep({
  customerId,
  guidance,
  result,
  config,
  equipment,
  labor,
  onEquipmentChange,
  onLaborChange,
  onConfigChange,
  onHistoryChanged,
}: {
  customerId: string | null
  guidance: CustomerGuidance | null
  result: EstimateResponse | null
  config: PricingConfig
  equipment: EquipmentLineRequest[]
  labor: LaborLineRequest[]
  onEquipmentChange: (lines: EquipmentLineRequest[]) => void
  onLaborChange: (lines: LaborLineRequest[]) => void
  onConfigChange: (config: PricingConfig) => void
  onHistoryChanged: () => void
}) {
  const [adding, setAdding] = useState<'equipment' | 'labor' | null>(null)

  async function applyPreset(presetId: string) {
    const request = await api.resolvePreset(presetId, customerId)
    onEquipmentChange(request.equipment)
    onLaborChange(request.labor)
    setAdding(null)
  }

  function addEquipment(equipmentId: string) {
    const existing = equipment.find((l) => l.equipmentId === equipmentId)
    onEquipmentChange(
      existing
        ? equipment.map((l) =>
            l.equipmentId === equipmentId ? { ...l, quantity: l.quantity + 1 } : l,
          )
        : [...equipment, { equipmentId, quantity: 1 }],
    )
  }

  function setQuantity(equipmentId: string, quantity: number) {
    if (quantity < 1) {
      onEquipmentChange(equipment.filter((l) => l.equipmentId !== equipmentId))
      return
    }
    onEquipmentChange(
      equipment.map((l) => (l.equipmentId === equipmentId ? { ...l, quantity } : l)),
    )
  }

  const estimate = result?.estimate
  const service = guidance?.service
  const missing = guidance?.missingFields ?? []

  if (adding === 'equipment') {
    return <EquipmentPicker onAdd={addEquipment} onClose={() => setAdding(null)} />
  }

  if (adding === 'labor') {
    return (
      <LaborEditor
        proposals={result?.proposals ?? guidance?.proposals ?? {}}
        onAdd={(jobType: JobType, level: string) => {
          onLaborChange([...labor, { jobType, level, hours: null }])
          setAdding(null)
        }}
        onClose={() => setAdding(null)}
      />
    )
  }

  return (
    <>
      {guidance && (
        <div className="card">
          <div className="body stack-8">
            <div className="wrap">
              <span className="tag">{guidance.customer.propertyType}</span>
              <span className="tag">
                {guidance.customer.squareFootage.toLocaleString()} sq ft
              </span>
              {guidance.customer.systemAge !== null && (
                <span
                  className={`tag ${
                    guidance.customer.systemAge >= config.endOfLifeYears ? 'warn' : ''
                  }`}
                >
                  {guidance.customer.systemAge} yr old
                </span>
              )}
              {service && service.status !== 'unknown' && (
                <span
                  className={`tag ${
                    service.status === 'overdue'
                      ? 'danger'
                      : service.status === 'due'
                        ? 'warn'
                        : 'ok'
                  }`}
                >
                  service {service.status}
                </span>
              )}
            </div>
            <div className="small muted">{guidance.customer.systemType}</div>
            {service && <div className="small muted">{service.message}</div>}
            {missing.length > 0 && (
              <div className="tiny muted">
                Not on file: {missing.join(', ')}. Advice that depends on those is
                withheld rather than guessed.
              </div>
            )}
          </div>
        </div>
      )}

      {guidance && (
        <EstimateHistory
          estimates={guidance.savedEstimates}
          onChanged={onHistoryChanged}
        />
      )}

      <PresetPicker customerId={customerId} onApply={applyPreset} />

      <div className="card">
        <header>
          <h2>Parts</h2>
          <button className="btn ghost" onClick={() => setAdding('equipment')}>
            + Add
          </button>
        </header>
        {estimate && estimate.equipmentLines.length > 0 ? (
          estimate.equipmentLines.map((line) => (
            <div key={line.equipmentId} className="line">
              <div className="grow">
                <div className="t">{line.name}</div>
                <div className="s">
                  {line.brand} · {line.modelNumber}
                </div>
                <div className="qty">
                  <button
                    className="btn icon"
                    aria-label="Decrease quantity"
                    onClick={() => setQuantity(line.equipmentId, line.quantity - 1)}
                  >
                    −
                  </button>
                  <input
                    type="number"
                    min="0"
                    value={line.quantity}
                    onChange={(e) =>
                      setQuantity(line.equipmentId, Number(e.target.value))
                    }
                  />
                  <button
                    className="btn icon"
                    aria-label="Increase quantity"
                    onClick={() => setQuantity(line.equipmentId, line.quantity + 1)}
                  >
                    +
                  </button>
                </div>
              </div>
              <div className="amt">{money(line.total)}</div>
            </div>
          ))
        ) : (
          <div className="empty">No parts on this estimate.</div>
        )}
      </div>

      <div className="card">
        <header>
          <h2>Labour</h2>
          <button className="btn ghost" onClick={() => setAdding('labor')}>
            + Add
          </button>
        </header>
        {estimate && estimate.laborLines.length > 0 ? (
          estimate.laborLines.map((line, index) => (
            <div key={`${line.jobType}-${line.level}-${index}`} className="line">
              <div className="grow">
                <div className="t">{jobLabel(line.jobType, line.level)}</div>
                <div className="s">
                  {money(line.hourlyRate, false)}/hr · allowed{' '}
                  {fmtHours(line.minHours)}–{fmtHours(line.maxHours)}h
                </div>
                <div className="qty">
                  <input
                    type="number"
                    step="0.5"
                    min="0"
                    value={line.hours}
                    aria-label="Hours"
                    onChange={(e) =>
                      onLaborChange(
                        labor.map((l, i) =>
                          i === index ? { ...l, hours: e.target.value } : l,
                        ),
                      )
                    }
                  />
                  <span className="small muted" style={{ marginLeft: 6 }}>
                    hours
                  </span>
                  <button
                    className="btn ghost"
                    style={{ marginLeft: 'auto' }}
                    onClick={() =>
                      onLaborChange(labor.filter((_, i) => i !== index))
                    }
                  >
                    Remove
                  </button>
                </div>
              </div>
              <div className="amt">{money(line.total)}</div>
            </div>
          ))
        ) : (
          <div className="empty">No labour on this estimate.</div>
        )}
      </div>

      {result && <Advisories result={result} />}

      {estimate && estimate.warnings.length > 0 && (
        <div className="card no-print">
          <header>
            <h2>Notes for you</h2>
          </header>
          <div className="body">
            <ul className="small muted" style={{ margin: 0, paddingLeft: 18 }}>
              {estimate.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      <SettingsPanel config={config} onChange={onConfigChange} />
    </>
  )
}
