import { useState, useEffect, useRef } from 'react'
import './App.css'

const EXAMPLES = [
  'A quadruped robot with 12 servos, IMU, and a Raspberry Pi 5',
  'Line-following car with 2 DC motors, IR array, and ESP32',
  'Drone flight controller, 4 ESC PWM outputs, BMI270 IMU',
  'Hexapod with 18 MG996R servos powered from a 3S LiPo',
]

const STEPS = [
  {
    k: '01',
    t: 'Chat intake',
    d: 'Tell the agent about motors, sensors, power and form factor.',
  },
  {
    k: '02',
    t: 'LLM design spec',
    d: 'A Nebius-hosted model fills missing details and picks real parts.',
  },
  {
    k: '03',
    t: 'KiCad gen',
    d: 'Python emits real .kicad_sch and .kicad_pcb S-expressions.',
  },
  {
    k: '04',
    t: '3D + export',
    d: 'Inspect the board in WebGL, download Gerbers and BOM.',
  },
]

const STACK = ['Nebius AI', 'KiCad', 'React 19', 'FastAPI', 'Three.js', 'Vite']

function App() {
  const [prompt, setPrompt] = useState('')
  const [placeholder, setPlaceholder] = useState('')
  const [tick, setTick] = useState(0)
  const [scrolled, setScrolled] = useState(false)
  const inputRef = useRef(null)

  // Translucent-on-scroll header
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  const focusPrompt = () => {
    inputRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    inputRef.current?.focus({ preventScroll: true })
  }

  // Typewriter placeholder
  useEffect(() => {
    const target = EXAMPLES[tick % EXAMPLES.length]
    let i = 0
    setPlaceholder('')
    const id = setInterval(() => {
      i++
      setPlaceholder(target.slice(0, i))
      if (i >= target.length) {
        clearInterval(id)
        setTimeout(() => setTick((t) => t + 1), 2600)
      }
    }, 30)
    return () => clearInterval(id)
  }, [tick])

  const onSubmit = (e) => {
    e.preventDefault()
    if (!prompt.trim()) return
    alert(`Generating PCB for: ${prompt}`)
  }

  return (
    <div className="page">
      <header className={`nav ${scrolled ? 'scrolled' : ''}`}>
        <a className="brand" href="#top">
          <span className="brand-chip" aria-hidden>
            <span className="chip-dot" />
          </span>
          <span className="brand-name">PCBlarp</span>
        </a>
        <nav className="links">
          <a href="#how">How it works</a>
          <a href="#stack">Stack</a>
          <a href="https://github.com" target="_blank" rel="noreferrer">
            GitHub ↗
          </a>
        </nav>
        <a className="cta-pill" href="#start">
          Generate a PCB →
        </a>
      </header>

      <main id="top">
        {/* ---------- HERO ---------- */}
        <section className="hero" id="start">
          {/* The image IS the hero — full-bleed, edge to edge. */}
          <div className="hero-art">
            <img
              src="/hero.png"
              alt="PCBlarp — describe a robot, get a manufacturable PCB"
              className="hero-img"
            />
            <div className="frame-fx" aria-hidden>
                <span className="fx-cloud fc1" />
                <span className="fx-cloud fc2" />
                <span className="fx-cloud fc3" />
                <span className="fx-glow" />
                <span className="fx-spark sp1" />
                <span className="fx-spark sp2" />
                <span className="fx-spark sp3" />
                <span className="fx-spark sp4" />
                <span className="fx-spark sp5" />
              </div>
            <div className="hero-copy">
              <h1 className="hero-title">Describe a robot. Get a PCB.</h1>
              <p className="hero-sub">
                Schematic · 2-layer layout · Gerbers · BOM
              </p>
            </div>
            <button
              type="button"
              className="hero-btn hero-btn-green"
              onClick={focusPrompt}
            >
              Generate a PCB
            </button>
            <a className="hero-btn hero-btn-white" href="#how">
              See the launch
            </a>
          </div>

          <div className="hero-tools">
            <form className="prompt" onSubmit={onSubmit}>
              <div className="prompt-bar">
                <span className="prompt-prefix">›</span>
                <input
                  ref={inputRef}
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  placeholder={placeholder + '▍'}
                  spellCheck={false}
                  aria-label="Describe your robot"
                />
                <button type="submit" className="btn-generate">
                  Generate <span className="arrow">→</span>
                </button>
              </div>
              <div className="chips">
                <span className="chips-label">Try</span>
                {EXAMPLES.slice(0, 3).map((ex) => (
                  <button
                    key={ex}
                    type="button"
                    className="chip"
                    onClick={() => setPrompt(ex)}
                  >
                    {ex.split(',')[0]}
                  </button>
                ))}
              </div>
            </form>

            <div className="metrics">
              <Metric value="< 60s" label="spec → schematic" />
              <Metric value="2-layer" label="manufacturable" />
              <Metric value="Gerber + BOM" label="ready for JLCPCB" />
              <Metric value="Three.js" label="live 3D preview" />
            </div>
          </div>
        </section>

        {/* ---------- HOW ---------- */}
        <section id="how" className="how">
          <Sparkles className="how-sparks" />
          <div className="section-head">
            <span className="eyebrow">04 steps</span>
            <h2>From prompt to fab file.</h2>
            <p>
              The LLM never writes KiCad files directly — it outputs structured
              JSON, and Python generates the precise S-expressions.
            </p>
          </div>
          <div className="steps-wrap">
            <div className="trace" aria-hidden>
              <span className="trace-pulse" />
            </div>
            <div className="steps">
              {STEPS.map((s) => (
                <article className="step" key={s.k}>
                  <div className="step-k">{s.k}</div>
                  <h3 className="step-t">{s.t}</h3>
                  <p className="step-d">{s.d}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        {/* ---------- STACK ---------- */}
        <section id="stack" className="stack">
          <Clouds />
          <div className="stack-inner">
            <span className="eyebrow">Powered by</span>
            <div className="logos">
              {STACK.map((s) => (
                <span className="logo" key={s}>
                  {s}
                </span>
              ))}
            </div>
          </div>
        </section>
      </main>

      <footer className="foot">
        <span className="foot-stars" aria-hidden>
          <span className="star st1" />
          <span className="star st2" />
          <span className="star st3" />
          <span className="star st4" />
        </span>
        <span className="foot-brand">
          <span className="brand-chip small" aria-hidden>
            <span className="chip-dot" />
          </span>
          PCBlarp · Team Mahek · Kanha · Manay · Pratham
        </span>
        <span className="status">
          <span className="status-dot" /> backend offline · demo mode
        </span>
      </footer>
    </div>
  )
}

function Metric({ value, label }) {
  return (
    <div className="metric">
      <div className="metric-v">{value}</div>
      <div className="metric-l">{label}</div>
    </div>
  )
}

function Clouds() {
  return (
    <div className="clouds" aria-hidden>
      <span className="cloud c1" />
      <span className="cloud c2" />
      <span className="cloud c3" />
    </div>
  )
}

function Sparkles({ className = '' }) {
  return (
    <div className={`sparks ${className}`} aria-hidden>
      <span className="spark k1" />
      <span className="spark k2" />
      <span className="spark k3" />
      <span className="spark k4" />
      <span className="spark k5" />
      <span className="spark k6" />
    </div>
  )
}

export default App
