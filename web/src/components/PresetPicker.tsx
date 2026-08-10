import { useEffect, useState } from 'react'
import { api } from '../api'
import { titleCase } from '../format'
import type { Preset } from '../types'

const GROUP_ORDER = ['repair', 'install', 'maintenance', 'diagnostic']

/**
 * Step 2 -- the common jobs, one tap each.
 *
 * A tech does the same handful of jobs repeatedly; a failed run capacitor is the
 * most common no-cooling call in the trade. Rebuilding that estimate from a blank
 * form several times a day is where the time actually goes, and this is the least
 * clever, highest-value part of the tool.
 *
 * Levels are resolved server-side against the selected customer, so the same
 * "AC replacement" preset produces residential, commercial or mini-split labour
 * without the button having to know anything about the property.
 */
export default function PresetPicker({
  customerId,
  onApply,
}: {
  customerId: string | null
  onApply: (presetId: string) => void
}) {
  const [presets, setPresets] = useState<Preset[]>([])
  const [open, setOpen] = useState(true)

  useEffect(() => {
    api.presets().then(setPresets).catch(() => setPresets([]))
  }, [])

  const groups = GROUP_ORDER.filter((g) => presets.some((p) => p.group === g))

  return (
    <div className="card">
      <header>
        <h2>Common jobs</h2>
        <button className="btn ghost" onClick={() => setOpen(!open)}>
          {open ? 'Hide' : 'Show'}
        </button>
      </header>
      {open && (
        <div className="body">
          {groups.map((group) => (
            <div className="preset-group" key={group}>
              <h3>{titleCase(group)}</h3>
              <div className="preset-grid">
                {presets
                  .filter((p) => p.group === group)
                  .map((preset) => (
                    <button
                      key={preset.id}
                      className="preset"
                      aria-label={preset.name}
                      onClick={() => onApply(preset.id)}
                    >
                      <div className="t">{preset.name}</div>
                      <div className="d">{preset.description}</div>
                    </button>
                  ))}
              </div>
            </div>
          ))}
          {presets.length === 0 && <div className="empty">No presets available.</div>}
          <p className="tiny muted" style={{ marginBottom: 0, marginTop: 12 }}>
            {customerId
              ? 'Labour levels are matched to this property automatically.'
              : 'No customer selected — levels default to residential.'}
          </p>
        </div>
      )}
    </div>
  )
}
