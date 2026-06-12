import express from 'express'
import cors from 'cors'
import OpenAI from 'openai'
import dotenv from 'dotenv'

// Load secrets (gitignored). .env.local first, then .env as fallback.
dotenv.config({ path: '.env.local' })
dotenv.config()

const apiKey = process.env.OPENAI_API_KEY
const model = process.env.OPENAI_MODEL || 'gpt-4o-mini'
const port = process.env.SERVER_PORT || 8787

const SYSTEM_PROMPT = `You are PCBlarp, an expert PCB design agent for robots.
You help users turn plain-English robot descriptions into manufacturable PCBs.
Be concise and friendly. Ask focused clarifying questions about motors, sensors,
power source, and form factor. When you have enough detail, suggest concrete
components (motor drivers, regulators, MCUs, connectors) and explain why.
Talk like a helpful engineer, not a manual. Keep replies short unless asked.`

const app = express()
app.use(cors())
app.use(express.json({ limit: '1mb' }))

app.get('/api/health', (_req, res) => {
  res.json({ ok: true, hasKey: Boolean(apiKey), model })
})

app.post('/api/chat', async (req, res) => {
  if (!apiKey) {
    return res
      .status(500)
      .json({ error: 'OPENAI_API_KEY is not set in .env.local on the server.' })
  }

  const { messages = [] } = req.body || {}
  const client = new OpenAI({ apiKey })

  try {
    const stream = await client.chat.completions.create({
      model,
      stream: true,
      temperature: 0.5,
      messages: [
        { role: 'system', content: SYSTEM_PROMPT },
        ...messages
          .filter((m) => m && m.role && m.content)
          .map((m) => ({ role: m.role, content: String(m.content) })),
      ],
    })

    res.setHeader('Content-Type', 'text/plain; charset=utf-8')
    res.setHeader('Cache-Control', 'no-cache')
    res.setHeader('X-Accel-Buffering', 'no')

    for await (const chunk of stream) {
      const delta = chunk.choices?.[0]?.delta?.content
      if (delta) res.write(delta)
    }
    res.end()
  } catch (err) {
    console.error('[chat] error:', err.message)
    if (!res.headersSent) {
      res.status(500).json({ error: err.message || 'OpenAI request failed' })
    } else {
      res.end()
    }
  }
})

app.listen(port, () => {
  console.log(`\nPCBlarp chat server → http://localhost:${port}`)
  console.log(`  model: ${model}`)
  console.log(`  OPENAI_API_KEY: ${apiKey ? 'set ✓' : 'MISSING ✗ (add it to .env.local)'}\n`)
})
