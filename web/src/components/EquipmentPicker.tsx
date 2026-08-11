import { useEffect, useState } from 'react'
import { api } from '../api'
import { money } from '../format'
import type { Equipment } from '../types'

/**
 * Equipment search.
 *
 * Deliberately forgiving: search matches name, brand, category and model number,
 * because a tech types "cap" or squints at a fragment of a model number on a
 * sticker rather than composing a well-formed query.
 */
export default function EquipmentPicker({
  onAdd,
  onClose,
}: {
  onAdd: (equipmentId: string) => void
  onClose: () => void
}) {
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState('')
  const [categories, setCategories] = useState<string[]>([])
  const [results, setResults] = useState<Equipment[]>([])

  useEffect(() => {
    api.categories().then(setCategories).catch(() => setCategories([]))
  }, [])

  useEffect(() => {
    const t = setTimeout(() => {
      api
        .equipment(query || undefined, category || undefined)
        .then(setResults)
        .catch(() => setResults([]))
    }, 150)
    return () => clearTimeout(t)
  }, [query, category])

  return (
    <div className="card">
      <header>
        <h2>Add equipment</h2>
        <button className="btn ghost" onClick={onClose}>
          Done
        </button>
      </header>
      <div className="body stack-8">
        <input
          className="field"
          placeholder="Search part, brand or model number"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          autoFocus
          autoComplete="off"
        />
        <select
          className="field"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
        >
          <option value="">All categories</option>
          {categories.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </div>
      <div className="picklist">
        {results.slice(0, 40).map((item) => (
          <button
            key={item.id}
            className="pick"
            aria-label={`Add ${item.name}`}
            onClick={() => onAdd(item.id)}
          >
            <div className="row-between">
              <span className="name">{item.name}</span>
              <span className="amt">{money(item.cost)}</span>
            </div>
            <div className="meta">
              {item.category} · {item.brand} · {item.modelNumber}
            </div>
          </button>
        ))}
        {results.length === 0 && <div className="empty">No parts match.</div>}
      </div>
    </div>
  )
}
