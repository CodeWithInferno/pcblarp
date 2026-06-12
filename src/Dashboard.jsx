import { useEffect, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { SignedIn, SignedOut, SignInButton, UserButton } from '@clerk/clerk-react'
import './Dashboard.css'

const CLERK_ENABLED = Boolean(import.meta.env.VITE_CLERK_PUBLISHABLE_KEY)

const GREETING = {
  role: 'assistant',
  content:
    "Hey! Describe the device you want to build — motors, sensors, power, form factor — and I'll run it through the PCB pipeline.",
}

const SUGGESTIONS = [
  'A line-following car with 2 DC motors and an ESP32',
  'A wearable that records audio and sends it over BLE',
  'A desk sensor: temp, humidity, OLED, USB-C',
]

const STAGE_LABEL = {
  spec: 'Spec',
  parts: 'Parts',
  schematic: 'Schematic',
  layout: 'Layout',
  export: 'Export',
}

const TERMINAL = new Set(['done', 'partial', 'failed'])

function ChipIcon({ className = '' }) {
  return (
    <span className={`chip-icon ${className}`} aria-hidden>
      <span className="chip-core" />
    </span>
  )
}

function Dashboard() {
  const location = useLocation()
  const [messages, setMessages] = useState([GREETING])
  const [draft, setDraft] = useState('')
  const [run, setRun] = useState(null)
  const [running, setRunning] = useState(false)
  const logRef = useRef(null)
  const pollRef = useRef(null)
  const seeded = useRef(false)

  useEffect(() => {
    const el = logRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, running])

  useEffect(() => () => clearInterval(pollRef.current), [])

  function pushAgent(content, extra = {}) {
    setMessages((m) => [...m, { role: 'assistant', content, ...extra }])
  }

  async function poll(runId) {
    try {
      const res = await fetch(`/api/runs/${runId}`)
      if (!res.ok) throw new Error(`status ${res.status}`)
      const state = await res.json()
      setRun(state)
      if (TERMINAL.has(state.status)) {
        clearInterval(pollRef.current)
        setRunning(false)
        const okStages = state.stages.filter((s) => s.status === 'ok').length
        if (state.status === 'failed') {
          pushAgent('⚠️ The pipeline failed. Check the stages on the canvas.', {
            error: true,
          })
        } else {
          const verb = state.status === 'partial' ? 'Partly done' : 'Done'
          const name = state.spec?.project?.name
          pushAgent(
            `${verb} — ${okStages}/${state.stages.length} stages passed${
              name ? ` for “${name}”` : ''
            }. Spec, board stages, and downloads are on the canvas →`
          )
        }
      }
    } catch (err) {
      clearInterval(pollRef.current)
      setRunning(false)
      pushAgent(`⚠️ Lost the run: ${err.message}`, { error: true })
    }
  }

  async function startRun(idea) {
    const text = idea.trim()
    if (!text || running) return

    setMessages((m) => [...m, { role: 'user', content: text }])
    setDraft('')
    setRunning(true)
    setRun(null)

    try {
      const res = await fetch('/api/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ idea: text }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail || `Server error (${res.status})`)
      }
      const { run_id } = await res.json()
      pushAgent('On it — running the pipeline. Watch the stages on the canvas.')
      clearInterval(pollRef.current)
      pollRef.current = setInterval(() => poll(run_id), 900)
      poll(run_id)
    } catch (err) {
      setRunning(false)
      pushAgent(`⚠️ ${err.message}`, { error: true })
    }
  }

  useEffect(() => {
    if (seeded.current) return
    seeded.current = true
    const p = location.state?.prompt
    if (p && p.trim()) startRun(p)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const onSubmit = (e) => {
    e.preventDefault()
    startRun(draft)
  }

  const artifacts = run
    ? run.stages.flatMap((s) =>
        Object.entries(s.artifacts || {}).map(([name, url]) => ({ name, url }))
      )
    : []
  const blocks = run?.spec?.blocks || []
  const componentCount = run?.bom?.rows?.length ?? blocks.length

  return (
    <div className="dash">
      <header className="dash-top">
        <div className="dash-brand">
          <Link to="/" className="dash-home">
            <ChipIcon />
            <span className="dash-name">PCBlarp</span>
          </Link>
          <span className="dash-sep">/</span>
          <span className="dash-proj">
            {run?.spec?.project?.name || 'untitled-board'}
          </span>
          {run && <span className={`dash-badge st-${run.status}`}>{run.status}</span>}
        </div>
        <div className="dash-actions">
          <button className="dash-btn ghost" type="button">
            Export
          </button>
          <button className="dash-btn" type="button">
            Share
          </button>
          {CLERK_ENABLED && (
            <>
              <SignedOut>
                <SignInButton mode="modal">
                  <button className="dash-btn ghost" type="button">
                    Log in
                  </button>
                </SignInButton>
              </SignedOut>
              <SignedIn>
                <UserButton afterSignOutUrl="/" />
              </SignedIn>
            </>
          )}
        </div>
      </header>

      <div className="dash-body">
        {/* left: chat that drives the pipeline */}
        <aside className="chat">
          <div className="chat-head">
            <ChipIcon />
            <div className="chat-head-meta">
              <span className="chat-title">PCB Agent</span>
              <span className="chat-status">
                <span className="chat-dot" /> {running ? 'building…' : 'ready'}
              </span>
            </div>
          </div>

          <div className="chat-log" ref={logRef}>
            {messages.map((m, i) => {
              const isAgent = m.role === 'assistant'
              return (
                <div key={i} className={`msg msg-${isAgent ? 'agent' : 'user'}`}>
                  {isAgent && <ChipIcon className="msg-avatar" />}
                  <div className={`bubble ${m.error ? 'bubble-error' : ''}`}>
                    {m.content}
                  </div>
                </div>
              )
            })}
            {running && (
              <div className="msg msg-agent">
                <ChipIcon className="msg-avatar" />
                <div className="bubble typing">
                  <span />
                  <span />
                  <span />
                </div>
              </div>
            )}
          </div>

          {messages.length <= 1 && !running && (
            <div className="chat-suggest">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  className="suggest"
                  onClick={() => startRun(s)}
                >
                  {s}
                </button>
              ))}
            </div>
          )}

          <form className="chat-input" onSubmit={onSubmit}>
            <span className="chat-prefix">›</span>
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder={running ? 'Building…' : 'Describe your device…'}
              spellCheck={false}
              aria-label="Describe your device"
              disabled={running}
            />
            <button
              type="submit"
              className="chat-send"
              aria-label="Build"
              disabled={running || !draft.trim()}
            >
              →
            </button>
          </form>
        </aside>

        {/* right: live pipeline + spec + downloads */}
        <main className="canvas">
          <div className="canvas-bar">
            <div className="tool-group">
              <span className="canvas-label">Pipeline</span>
            </div>
            <div className="tool-group">
              {run && (
                <span className={`run-status st-${run.status}`}>{run.status}</span>
              )}
            </div>
          </div>

          <div className="canvas-surface run-surface">
            {!run ? (
              <div className="canvas-empty">
                <ChipIcon className="empty-icon" />
                <h2 className="empty-title">Canvas</h2>
                <p className="empty-sub">
                  Your spec, board stages &amp; fab files will appear here.
                </p>
                <p className="empty-hint">
                  Describe a device in the chat to start a build.
                </p>
              </div>
            ) : (
              <div className="run-view">
                {/* stages */}
                <section className="run-card">
                  <h3 className="run-h">Stages</h3>
                  <div className="stages">
                    {run.stages.map((s) => (
                      <div className="stage-row" key={s.name}>
                        <span className="stage-name">
                          {STAGE_LABEL[s.name] || s.name}
                        </span>
                        <span className={`stage-badge bg-${s.status}`}>
                          {s.status}
                        </span>
                        <span className="stage-meta">
                          {s.attempts > 1 ? `${s.attempts}× · ` : ''}
                          {s.duration_ms ? `${Math.round(s.duration_ms)}ms` : ''}
                        </span>
                        {s.error && <span className="stage-err">{s.error}</span>}
                      </div>
                    ))}
                  </div>
                </section>

                {/* spec */}
                {run.spec && (
                  <section className="run-card">
                    <h3 className="run-h">Spec</h3>
                    <p className="run-summary">{run.spec.project?.summary}</p>
                    {!!blocks.length && (
                      <div className="block-chips">
                        {blocks.map((b, i) => (
                          <span className="block-chip" key={b.id || i}>
                            {b.id || b.name || 'block'}
                          </span>
                        ))}
                      </div>
                    )}
                    {run.spec.power?.source && (
                      <p className="run-line">
                        power: <b>{run.spec.power.source}</b>
                      </p>
                    )}
                  </section>
                )}

                {/* downloads */}
                {!!artifacts.length && (
                  <section className="run-card">
                    <h3 className="run-h">Downloads</h3>
                    <div className="dl-list">
                      {artifacts.map((a, i) => (
                        <a
                          key={i}
                          className="dl"
                          href={a.url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          ↓ {a.name}
                        </a>
                      ))}
                    </div>
                  </section>
                )}
              </div>
            )}
          </div>

          <div className="canvas-status">
            <span>{run?.spec?.project?.name || '2-layer · 100 × 80 mm'}</span>
            <span className="status-right">
              {componentCount} components · {artifacts.length} files ·{' '}
              {run ? run.status : 'idle'}
            </span>
          </div>
        </main>
      </div>
    </div>
  )
}

export default Dashboard
