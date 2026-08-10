import { useEffect, useState } from 'react'
import { api } from '../api'
import type { Customer } from '../types'
import NewCustomerForm from './NewCustomerForm'

/**
 * Step 1 -- who is this for.
 *
 * Every subsequent default in the tool derives from this choice, so it comes
 * first. Two escape hatches when the property isn't on file: add it properly
 * (it becomes a real customer with history), or quote as a walk-up without
 * stopping to enter anything. Blocking on data entry at the door would defeat
 * the point of the tool.
 */
export default function CustomerStep({
  onSelect,
}: {
  onSelect: (id: string | null) => void
}) {
  const [query, setQuery] = useState('')
  const [customers, setCustomers] = useState<Customer[]>([])
  const [adding, setAdding] = useState(false)

  useEffect(() => {
    const t = setTimeout(() => {
      api.customers(query || undefined).then(setCustomers).catch(() => setCustomers([]))
    }, 150)
    return () => clearTimeout(t)
  }, [query])

  if (adding) {
    return (
      <NewCustomerForm
        initialName={query}
        onCreated={(customer) => onSelect(customer.id)}
        onCancel={() => setAdding(false)}
      />
    )
  }

  return (
    <>
      <input
        className="field"
        placeholder="Search name, address or phone"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        autoComplete="off"
      />

      <div className="card">
        <div className="picklist">
          {customers.map((c) => (
            <button
              key={c.id}
              className="pick"
              // The visible label is assembled from several divs, which leaves the
              // button with no accessible name of its own.
              aria-label={`${c.name}, ${c.address}`}
              onClick={() => onSelect(c.id)}
            >
              <div className="row-between">
                <span className="name">{c.name}</span>
                <span className={`tag ${c.propertyType === 'commercial' ? 'brand' : ''}`}>
                  {c.propertyType}
                </span>
              </div>
              <div className="meta">{c.address}</div>
              <div className="meta">
                {c.systemType} · {c.squareFootage.toLocaleString()} sq ft
                {c.systemAge !== null ? ` · ${c.systemAge} yr` : ' · age unknown'}
              </div>
            </button>
          ))}

          {customers.length === 0 && (
            <div className="empty">
              {query
                ? `Nobody matches “${query}”.`
                : 'No customers yet.'}
            </div>
          )}
        </div>
      </div>

      <button className="btn primary block" onClick={() => setAdding(true)}>
        + Add new customer
      </button>

      <button className="btn block" onClick={() => onSelect(null)}>
        Walk-up — quote without saving
      </button>
    </>
  )
}
