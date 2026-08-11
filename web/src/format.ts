import type { Money } from './types'

/**
 * Money arrives from the API as a decimal string and is formatted straight to
 * display text. `Number()` appears here only at the final rendering step, where a
 * sub-cent representation error cannot propagate into any further arithmetic.
 */
export function money(value: Money | null | undefined, cents = true): string {
  if (value === null || value === undefined) return '--'
  return Number(value).toLocaleString('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: cents ? 2 : 0,
    maximumFractionDigits: cents ? 2 : 0,
  })
}

/** Whole dollars -- for headline figures a customer reads at arm's length. */
export function dollars(value: Money | null | undefined): string {
  return money(value, false)
}

export function percent(ratio: string | null | undefined): string {
  if (ratio === null || ratio === undefined) return '--'
  return `${Math.round(Number(ratio) * 100)}%`
}

/** Trims trailing zeros: "1.50" -> "1.5", "2.00" -> "2". */
export function hours(value: string): string {
  const n = Number(value)
  return Number.isInteger(n) ? String(n) : String(n).replace(/0+$/, '')
}

export function titleCase(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1)
}

export function jobLabel(jobType: string, level: string): string {
  return `${titleCase(jobType)} · ${titleCase(level)}`
}
