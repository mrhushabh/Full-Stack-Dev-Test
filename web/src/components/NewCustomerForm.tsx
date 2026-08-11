import { useState } from 'react'
import { api } from '../api'
import type { Customer, NewCustomer } from '../types'

/**
 * "This property isn't on file."
 *
 * Only five fields are required. Phone, system age and last service date are
 * optional — the same three that are missing from real records in the provided
 * dataset, and the three a tech at an unfamiliar property is least likely to
 * know. Forcing a value would force a guess, and a guessed system age silently
 * drives the repair-vs-replace advice.
 *
 * The tool already handles those gaps gracefully: it says what it doesn't know
 * and withholds the advice that depended on it.
 */
export default function NewCustomerForm({
  initialName,
  onCreated,
  onCancel,
}: {
  initialName: string
  onCreated: (customer: Customer) => void
  onCancel: () => void
}) {
  const [form, setForm] = useState<NewCustomer>({
    name: initialName,
    address: '',
    propertyType: 'residential',
    squareFootage: 0,
    systemType: '',
    phone: '',
    systemAge: null,
    lastServiceDate: null,
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const set = <K extends keyof NewCustomer>(key: K, value: NewCustomer[K]) =>
    setForm((f) => ({ ...f, [key]: value }))

  const ready =
    form.name.trim() &&
    form.address.trim() &&
    form.systemType.trim() &&
    form.squareFootage > 0

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setSaving(true)
    setError(null)
    try {
      onCreated(
        await api.createCustomer({
          ...form,
          name: form.name.trim(),
          address: form.address.trim(),
          systemType: form.systemType.trim(),
          phone: form.phone?.trim() || null,
          systemAge: form.systemAge ?? null,
          lastServiceDate: form.lastServiceDate || null,
        }),
      )
    } catch (e) {
      setError((e as Error).message)
      setSaving(false)
    }
  }

  return (
    <form className="card" onSubmit={submit}>
      <header>
        <h2>New customer</h2>
        <button type="button" className="btn ghost" onClick={onCancel}>
          Cancel
        </button>
      </header>

      <div className="body stack-12">
        {error && <div className="banner">{error}</div>}

        <label className="stack">
          Name
          <input
            className="field"
            value={form.name}
            onChange={(e) => set('name', e.target.value)}
            placeholder="Name or business"
            autoFocus
          />
        </label>

        <label className="stack">
          Address
          <input
            className="field"
            value={form.address}
            onChange={(e) => set('address', e.target.value)}
            placeholder="Street, city, state, ZIP"
          />
        </label>

        <div className="grid2">
          <label className="stack">
            Property type
            <select
              className="field"
              value={form.propertyType}
              onChange={(e) =>
                set('propertyType', e.target.value as NewCustomer['propertyType'])
              }
            >
              <option value="residential">Residential</option>
              <option value="commercial">Commercial</option>
            </select>
          </label>

          <label className="stack">
            Square footage
            <input
              className="field"
              type="number"
              min="1"
              inputMode="numeric"
              value={form.squareFootage || ''}
              onChange={(e) => set('squareFootage', Number(e.target.value))}
              placeholder="2000"
            />
          </label>
        </div>

        <label className="stack">
          System type
          <input
            className="field"
            value={form.systemType}
            onChange={(e) => set('systemType', e.target.value)}
            placeholder="e.g. Central AC + Gas Furnace"
          />
          <span className="tiny muted">
            Drives the labour rate. Include “Mini-Split” if that's what it is.
          </span>
        </label>

        <div className="tiny muted" style={{ marginTop: 4 }}>
          Everything below is optional — leave it blank if you don't know.
        </div>

        <label className="stack">
          Phone
          <input
            className="field"
            type="tel"
            value={form.phone ?? ''}
            onChange={(e) => set('phone', e.target.value)}
            placeholder="(217) 555-0100"
          />
        </label>

        <div className="grid2">
          <label className="stack">
            System age (years)
            <input
              className="field"
              type="number"
              min="0"
              max="100"
              inputMode="numeric"
              value={form.systemAge ?? ''}
              onChange={(e) =>
                set('systemAge', e.target.value === '' ? null : Number(e.target.value))
              }
              placeholder="unknown"
            />
          </label>

          <label className="stack">
            Last serviced
            <input
              className="field"
              type="date"
              value={form.lastServiceDate ?? ''}
              onChange={(e) => set('lastServiceDate', e.target.value || null)}
            />
          </label>
        </div>

        <button className="btn primary block" type="submit" disabled={!ready || saving}>
          {saving ? 'Saving…' : 'Add customer'}
        </button>
      </div>
    </form>
  )
}
