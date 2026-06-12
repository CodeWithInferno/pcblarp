import { useEffect, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { SignedIn, SignedOut, SignInButton, UserButton } from '@clerk/clerk-react'
import './Dashboard.css'

const CLERK_ENABLED = Boolean(import.meta.env.VITE_CLERK_PUBLISHABLE_KEY)

const GREETING = {
  role: 'assistant',
  content:
    "Hey! I'm your PCB agent. Describe the robot you want to build — motors, sensors, power, form factor — and I'll spec the board.",
}

const SUGGESTIONS = [
  'A line-following car with 2 DC motors and an ESP32',
  'Quadruped with 12 servos and a Pi 5',
  'Drone flight controller with a BMI270 IMU',
]

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
  const [loading, setLoading] = useState(false)
  const logRef = useRef(null)
  const seeded = useRef(false)

  // auto-scroll to newest
  useEffect(() => {
    const el = logRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, loading])

  async function sendText(text) {
    const content = text.trim()
    if (!content || loading) return

    const convo = [...messages, { role: 'user', content }]
    // user message + empty assistant placeholder to stream into
    setMessages([...convo, { role: 'assistant', content: '' }])
    setDraft('')
    setLoading(true)

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: convo.map(({ role, content }) => ({ role, content })),
        }),
      })

      if (!res.ok || !res.body) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.error || `Server error (${res.status})`)
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let acc = ''
      // eslint-disable-next-line no-constant-condition
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        acc += decoder.decode(value, { stream: true })
        setMessages((m) => {
          const copy = [...m]
          copy[copy.length - 1] = { role: 'assistant', content: acc }
          return copy
        })
      }
    } catch (err) {
      setMessages((m) => {
        const copy = [...m]
        copy[copy.length - 1] = {
          role: 'assistant',
          content: `⚠️ ${err.message}`,
          error: true,
        }
        return copy
      })
    } finally {
      setLoading(false)
    }
  }

  // seed the first message from the landing prompt, if any
  useEffect(() => {
    if (seeded.current) return
    seeded.current = true
    const p = location.state?.prompt
    if (p && p.trim()) sendText(p)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const onSubmit = (e) => {
    e.preventDefault()
    sendText(draft)
  }

  const waiting =
    loading && messages[messages.length - 1]?.content === ''

  return (
    <div className="dash">
      <header className="dash-top">
        <div className="dash-brand">
          <Link to="/" className="dash-home">
            <ChipIcon />
            <span className="dash-name">PCBlarp</span>
          </Link>
          <span className="dash-sep">/</span>
          <span className="dash-proj">untitled-board</span>
          <span className="dash-badge">demo</span>
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
        {/* left: AI chat */}
        <aside className="chat">
          <div className="chat-head">
            <ChipIcon />
            <div className="chat-head-meta">
              <span className="chat-title">PCB Agent</span>
              <span className="chat-status">
                <span className="chat-dot" /> online · OpenAI
              </span>
            </div>
          </div>

          <div className="chat-log" ref={logRef}>
            {messages.map((m, i) => {
              const isAgent = m.role === 'assistant'
              const isLast = i === messages.length - 1
              const showTyping = isAgent && isLast && waiting
              return (
                <div key={i} className={`msg msg-${isAgent ? 'agent' : 'user'}`}>
                  {isAgent && <ChipIcon className="msg-avatar" />}
                  {showTyping ? (
                    <div className="bubble typing">
                      <span />
                      <span />
                      <span />
                    </div>
                  ) : (
                    <div className={`bubble ${m.error ? 'bubble-error' : ''}`}>
                      {m.content}
                    </div>
                  )}
                </div>
              )
            })}
          </div>

          {messages.length <= 1 && (
            <div className="chat-suggest">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  className="suggest"
                  onClick={() => sendText(s)}
                  disabled={loading}
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
              placeholder={loading ? 'Thinking…' : 'Describe your robot…'}
              spellCheck={false}
              aria-label="Message the PCB agent"
              disabled={loading}
            />
            <button
              type="submit"
              className="chat-send"
              aria-label="Send"
              disabled={loading || !draft.trim()}
            >
              →
            </button>
          </form>
        </aside>

        {/* right: canvas */}
        <main className="canvas">
          <div className="canvas-bar">
            <div className="tool-group">
              <button className="tool active" type="button" title="Select">
                ✛
              </button>
              <button className="tool" type="button" title="Pan">
                ✋
              </button>
            </div>
            <div className="tool-group">
              <button className="tool" type="button" title="Zoom out">
                −
              </button>
              <span className="zoom">100%</span>
              <button className="tool" type="button" title="Zoom in">
                +
              </button>
              <button className="tool" type="button" title="Toggle grid">
                ▦
              </button>
              <button className="tool" type="button" title="Fit to screen">
                ⤢
              </button>
            </div>
          </div>

          <div className="canvas-surface">
            <div className="board-ghost" aria-hidden />
            <div className="canvas-empty">
              <ChipIcon className="empty-icon" />
              <h2 className="empty-title">Canvas</h2>
              <p className="empty-sub">
                Your schematic &amp; 2-layer board will render here.
              </p>
              <p className="empty-hint">
                Describe your robot in the chat to generate it.
              </p>
            </div>
          </div>

          <div className="canvas-status">
            <span>2-layer · 100 × 80 mm</span>
            <span className="status-right">0 components · 0 nets · DRC —</span>
          </div>
        </main>
      </div>
    </div>
  )
}

export default Dashboard
