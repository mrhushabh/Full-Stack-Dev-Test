import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'
import BuildStep from './components/BuildStep'
import CustomerStep from './components/CustomerStep'
import PresentStep from './components/PresentStep'
import { dollars } from './format'
import { type Theme, useTheme } from './theme'
import type {
  CustomerGuidance,
  EquipmentLineRequest,
  EstimateResponse,
  EstimateStatus,
  LaborLineRequest,
  PricingConfig,
} from './types'

type Step = 'customer' | 'build' | 'present'

const STEPS: Step[] = ['customer', 'build', 'present']

/* Light for daylight and roofs, dark for basements and evening calls. */
const THEME_LABEL: Record<Theme, string> = {
  light: 'Daylight',
  dark: 'Low light',
  system: 'Follow device',
}

const THEME_GLYPH: Record<Theme, string> = {
  light: '☀',
  dark: '☾',
  system: '◐',
}

export default function App() {
  const { theme, cycle } = useTheme()
  const [step, setStep] = useState<Step>('customer')
  const [customerId, setCustomerId] = useState<string | null>(null)
  const [guidance, setGuidance] = useState<CustomerGuidance | null>(null)

  const [equipment, setEquipment] = useState<EquipmentLineRequest[]>([])
  const [labor, setLabor] = useState<LaborLineRequest[]>([])
  const [config, setConfig] = useState<PricingConfig | null>(null)

  const [result, setResult] = useState<EstimateResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.config().then(setConfig).catch(() => {
      setError('Cannot reach the API. Is the server running on port 8000?')
    })
  }, [])

  /**
   * Assumption changes are applied locally first so every total updates as the
   * tech drags a number, then persisted. Without the write they would revert on
   * refresh, leaving the figure on screen disagreeing with what the server would
   * quote.
   */
  const saveTimer = useRef<number | undefined>(undefined)
  const changeConfig = useCallback((next: PricingConfig) => {
    setConfig(next)
    // Debounced: these are number inputs, and a write per keystroke would be a
    // write per digit of "1.45".
    window.clearTimeout(saveTimer.current)
    saveTimer.current = window.setTimeout(() => {
      api
        .saveConfig(next)
        .catch((e) => setError(`Could not save settings: ${(e as Error).message}`))
    }, 600)
  }, [])

  /*
   * Pricing is recalculated server-side on every edit rather than mirrored in the
   * client. Markup, the diagnostic credit and the replacement thresholds are
   * business rules; a second implementation living in the browser would be a
   * second implementation to keep in step, and a set of margins a customer could
   * edit with devtools open.
   *
   * Debounced because quantity and hours are typed a character at a time.
   */
  const seq = useRef(0)
  const reprice = useCallback(async () => {
    if (!config) return
    const mine = ++seq.current
    try {
      const response = await api.price({
        customerId,
        equipment,
        labor,
        misc: [],
        config,
      })
      // Drop responses that arrive out of order behind a newer edit.
      if (mine === seq.current) {
        setResult(response)
        setError(null)
      }
    } catch (e) {
      if (mine === seq.current) setError((e as Error).message)
    }
  }, [config, customerId, equipment, labor])

  useEffect(() => {
    const t = setTimeout(reprice, 150)
    return () => clearTimeout(t)
  }, [reprice])

  const loadGuidance = useCallback(async (id: string | null) => {
    if (!id) {
      setGuidance(null)
      return
    }
    try {
      setGuidance(await api.guidance(id))
    } catch {
      /* guidance is contextual; the estimate still works without it */
    }
  }, [])

  /**
   * Every step change goes through here so it lands in browser history.
   *
   * Without it, the phone's own back gesture -- the most-used control on a
   * mobile device -- leaves the app entirely, because nothing ever pushed a
   * history entry to go back to.
   */
  const goTo = useCallback((next: Step) => {
    setStep(next)
    window.history.pushState({ step: next }, '')
  }, [])

  useEffect(() => {
    window.history.replaceState({ step: 'customer' }, '')
    const onPop = (event: PopStateEvent) => {
      setStep((event.state?.step as Step) ?? 'customer')
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  async function selectCustomer(id: string | null) {
    // Switching to a different customer would leave line items attached to the
    // wrong property, so ask first. Returning to the same one keeps the work.
    if ((equipment.length > 0 || labor.length > 0) && id !== customerId) {
      const ok = window.confirm(
        'Start a new estimate for this customer? The current one will be cleared.',
      )
      if (!ok) return
      setEquipment([])
      setLabor([])
      setResult(null)
    }
    setCustomerId(id)
    setGuidance(null)
    goTo('build')
    await loadGuidance(id)
  }

  async function saveEstimate(status: EstimateStatus) {
    if (!config) return
    await api.saveEstimate(
      { customerId, equipment, labor, misc: [], config },
      status,
    )
    // Refresh so the new record is already in the history when the tech returns.
    await loadGuidance(customerId)
  }

  /** Clear the line items but stay with this customer -- the usual next move. */
  function startAnother() {
    setEquipment([])
    setLabor([])
    setResult(null)
    goTo('build')
  }

  /** Explicit "Clear" only. Going back must never throw work away. */
  function reset() {
    setCustomerId(null)
    setGuidance(null)
    setEquipment([])
    setLabor([])
    setResult(null)
    goTo('customer')
  }

  const customer = result?.customer ?? guidance?.customer ?? null
  const hasLines = equipment.length > 0 || labor.length > 0
  const totals = result?.estimate.totals

  return (
    <div className="app">
      <div className="topbar">
        {step !== 'customer' && (
          <button
            className="btn icon"
            aria-label="Back"
            // Goes through history rather than setting the step directly, so the
            // on-screen button and the phone's back gesture behave identically.
            // It used to clear the whole estimate, which meant tapping back to
            // check an address threw the job away.
            onClick={() => window.history.back()}
          >
            ‹
          </button>
        )}
        <h1>
          {customer ? customer.name : 'Field Estimate'}
          <span className="sub">
            {customer
              ? customer.address
              : step === 'customer'
                ? 'Select a customer to begin'
                : 'Walk-up — not on file'}
          </span>
        </h1>
        {step === 'build' && hasLines && (
          <button className="btn ghost" onClick={reset}>
            Clear
          </button>
        )}
        <button
          className="btn icon"
          onClick={cycle}
          title={THEME_LABEL[theme]}
          aria-label={`Display: ${THEME_LABEL[theme]}. Tap to change.`}
        >
          {THEME_GLYPH[theme]}
        </button>
      </div>

      <div className="steps" aria-hidden="true">
        {STEPS.map((s) => (
          <span key={s} className={STEPS.indexOf(step) >= STEPS.indexOf(s) ? 'on' : ''} />
        ))}
      </div>

      <div className="content">
        {error && <div className="banner">{error}</div>}

        {step === 'customer' && <CustomerStep onSelect={selectCustomer} />}

        {step === 'build' && config && (
          <BuildStep
            customerId={customerId}
            guidance={guidance}
            result={result}
            config={config}
            equipment={equipment}
            labor={labor}
            onEquipmentChange={setEquipment}
            onLaborChange={setLabor}
            onConfigChange={changeConfig}
            onHistoryChanged={() => loadGuidance(customerId)}
          />
        )}

        {step === 'present' && result && (
          <PresentStep
            result={result}
            onSave={saveEstimate}
            onDone={startAnother}
          />
        )}
      </div>

      {step === 'build' && (
        <div className="dock">
          <div className="dock-inner">
            <div className="fig">
              <div className="k">Estimate</div>
              <div className="v">{dollars(totals?.expected.total ?? '0')}</div>
              {hasLines && totals && (
                <div className="r">
                  Range {dollars(totals.low.total)} – {dollars(totals.high.total)}
                </div>
              )}
            </div>
            <button
              className="btn primary"
              disabled={!hasLines}
              onClick={() => goTo('present')}
            >
              Show customer
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
