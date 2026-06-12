import { useState } from 'react'
import { sendChat, fetchDesignSpec, generateDesign } from '../api'
import type { ChatMessage } from '../api'

export default function ChatWizard() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: 'assistant',
      content:
        'Hey! I\'m PCBlarp. Tell me about your robot — what type, motors, sensors, and power source?',
    },
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [context, setContext] = useState<Record<string, unknown> | null>(null)

  const handleSend = async () => {
    if (!input.trim()) return
    const userMsg: ChatMessage = { role: 'user', content: input }
    setMessages((m) => [...m, userMsg])
    setInput('')
    setLoading(true)

    try {
      const data = await sendChat({ messages: [...messages, userMsg], context: context || undefined })
      setMessages((m) => [...m, { role: 'assistant', content: data.reply }])
      if (data.context) setContext(data.context)
    } catch (err) {
      setMessages((m) => [
        ...m,
        { role: 'assistant', content: `Error: ${(err as Error).message}` },
      ])
    } finally {
      setLoading(false)
    }
  }

  const handleGenerate = async () => {
    if (!context) return
    setLoading(true)
    try {
      const spec = await fetchDesignSpec(context)
      const design = await generateDesign(context, spec)
      setMessages((m) => [
        ...m,
        { role: 'assistant', content: `Generated! Status: ${design.status}` },
      ])
    } catch (err) {
      setMessages((m) => [
        ...m,
        { role: 'assistant', content: `Error: ${(err as Error).message}` },
      ])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-2xl mx-auto flex flex-col h-[80vh]">
      <div className="flex-1 overflow-y-auto space-y-3 p-4 bg-neutral-800 rounded">
        {messages.map((m, i) => (
          <div
            key={i}
            className={`p-3 rounded max-w-[80%] ${
              m.role === 'user' ? 'bg-blue-700 ml-auto' : 'bg-neutral-700'
            }`}
          >
            {m.content}
          </div>
        ))}
        {loading && <div className="text-neutral-400">Thinking...</div>}
      </div>

      <div className="mt-4 flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSend()}
          placeholder="Describe your robot..."
          className="flex-1 p-2 rounded bg-neutral-800 border border-neutral-700 focus:outline-none focus:border-blue-500"
        />
        <button
          onClick={handleSend}
          disabled={loading}
          className="px-4 py-2 bg-blue-600 rounded disabled:opacity-50"
        >
          Send
        </button>
        <button
          onClick={handleGenerate}
          disabled={loading || !context}
          className="px-4 py-2 bg-green-600 rounded disabled:opacity-50"
        >
          Generate
        </button>
      </div>
    </div>
  )
}
