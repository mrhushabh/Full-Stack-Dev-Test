/**
 * Mirrors the FastAPI response models.
 *
 * Money is `string`, never `number`. The server does its arithmetic in Python's
 * Decimal precisely so that cents cannot drift; parsing those values into JS
 * doubles here would hand the problem straight back. Amounts are formatted for
 * display and otherwise passed around untouched.
 *
 * Hand-written rather than generated. `openapi-typescript` against /openapi.json
 * would remove the chance of drift entirely and is the obvious next step -- see
 * the README.
 */

export type Money = string

export type JobType =
  | 'diagnostic'
  | 'repair'
  | 'install'
  | 'maintenance'
  | 'ductwork'

export type Confidence = 'high' | 'medium' | 'low'

export interface Equipment {
  id: string
  name: string
  category: string
  brand: string
  modelNumber: string
  cost: Money
}

export interface LaborRate {
  jobType: JobType
  level: string
  hourlyRate: Money
  minHours: string
  maxHours: string
}

export interface Customer {
  id: string
  name: string
  address: string
  phone: string | null
  propertyType: 'residential' | 'commercial'
  squareFootage: number
  systemType: string
  systemAge: number | null
  lastServiceDate: string | null
}

export interface Alternative {
  level: string
  reason: string
}

export interface LevelProposal {
  jobType: JobType
  level: string
  reason: string
  confidence: Confidence
  alternatives: Alternative[]
}

export interface ServiceStatus {
  status: 'unknown' | 'current' | 'due' | 'overdue'
  monthsSince: number | null
  lastServiceDate: string | null
  message: string
}

export interface CustomerGuidance {
  customer: Customer
  proposals: Record<string, LevelProposal>
  service: ServiceStatus
  requiredTons: number
  missingFields: string[]
  savedEstimates: SavedEstimateSummary[]
}

/**
 * Adding a property that isn't on file.
 *
 * The optional fields are exactly the ones missing from records in the provided
 * dataset — and exactly the ones a tech standing at an unfamiliar property is
 * least likely to know. Requiring them would require a guess.
 */
export interface NewCustomer {
  name: string
  address: string
  propertyType: 'residential' | 'commercial'
  squareFootage: number
  systemType: string
  phone?: string | null
  systemAge?: number | null
  lastServiceDate?: string | null
}

/** An estimate is only stored once the tech acts on it. */
export type EstimateStatus = 'approved' | 'held'

export interface SavedEstimateSummary {
  id: string
  customerId: string
  status: EstimateStatus
  createdAt: string
  total: Money
  lineCount: number
  summary: string
  notes: string | null
}

export interface PricingConfig {
  equipmentMarkup: string
  taxRate: string
  taxAppliesToLabor: boolean
  creditDiagnosticOnApproval: boolean
  replaceRuleMultiplier: string
  replaceCostRatio: string
  endOfLifeYears: number
  sqftPerTon: number
  sizingTolerance: string
  majorRepairCostThreshold: string
}

/* -- request shapes -------------------------------------------------------- */

export interface EquipmentLineRequest {
  equipmentId: string
  quantity: number
}

export interface LaborLineRequest {
  jobType: JobType
  level: string
  hours: string | null
}

export interface MiscLineRequest {
  description: string
  amount: string
  taxable: boolean
}

export interface EstimateRequest {
  customerId: string | null
  equipment: EquipmentLineRequest[]
  labor: LaborLineRequest[]
  misc: MiscLineRequest[]
  notes?: string | null
  config?: PricingConfig | null
}

/* -- response shapes ------------------------------------------------------- */

export interface PricedEquipmentLine {
  equipmentId: string
  name: string
  category: string
  brand: string
  modelNumber: string
  quantity: number
  unitCost: Money
  unitPrice: Money
  total: Money
}

export interface PricedLaborLine {
  jobType: JobType
  level: string
  hourlyRate: Money
  hours: string
  minHours: string
  maxHours: string
  total: Money
  totalLow: Money
  totalHigh: Money
}

export interface PricedMiscLine {
  description: string
  amount: Money
  taxable: boolean
}

export interface ScenarioTotals {
  labor: Money
  subtotal: Money
  diagnosticCredit: Money
  tax: Money
  total: Money
}

export interface EstimateTotals {
  equipment: Money
  misc: Money
  low: ScenarioTotals
  expected: ScenarioTotals
  high: ScenarioTotals
}

export interface Estimate {
  customerId: string | null
  equipmentLines: PricedEquipmentLine[]
  laborLines: PricedLaborLine[]
  miscLines: PricedMiscLine[]
  totals: EstimateTotals
  config: PricingConfig
  warnings: string[]
  notes: string | null
}

export interface SizingCheck {
  equipmentId: string
  equipmentName: string
  capacityTons: string
  requiredTons: string
  verdict: 'ok' | 'undersized' | 'oversized'
  message: string
}

export interface WarrantyFlag {
  applies: boolean
  message: string | null
}

export interface RepairVsReplace {
  triggered: boolean
  recommendation: 'replace' | 'consider' | 'repair'
  reasons: string[]
  repairTotal: Money
  replacementTotal: Money | null
  costRatio: string | null
  ageRuleValue: Money | null
  option: {
    equipmentId: string
    equipmentName: string
    estimate: Estimate
  } | null
  headline: string | null
}

export interface EstimateResponse {
  estimate: Estimate
  customer: Customer | null
  proposals: Record<string, LevelProposal>
  sizing: SizingCheck[]
  repairVsReplace: RepairVsReplace
  warranty: WarrantyFlag
}

export interface Preset {
  id: string
  name: string
  description: string
  group: string
  equipment: { equipmentId: string; quantity: number }[]
  labor: { jobType: JobType; level: string | null; hours: string | null }[]
}
