import { useState } from 'react'
import ChatWizard from './components/ChatWizard'
import SchematicPreview from './components/SchematicPreview'
import PCBViewer3D from './components/PCBViewer3D'

export type View = 'chat' | 'schematic' | 'pcb3d'

function App() {
  const [view, setView] = useState<View>('chat')

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-neutral-700 p-4 flex items-center justify-between">
        <h1 className="text-xl font-bold">PCBlarp</h1>
        <nav className="flex gap-2">
          {(['chat', 'schematic', 'pcb3d'] as View[]).map((v) => (
            <button
              key={v}
              onClick={() => setView(v)}
              className={`px-3 py-1 rounded text-sm ${
                view === v ? 'bg-blue-600' : 'bg-neutral-800 hover:bg-neutral-700'
              }`}
            >
              {v === 'pcb3d' ? '3D PCB' : v[0].toUpperCase() + v.slice(1)}
            </button>
          ))}
        </nav>
      </header>

      <main className="flex-1 p-4">
        {view === 'chat' && <ChatWizard />}
        {view === 'schematic' && <SchematicPreview />}
        {view === 'pcb3d' && <PCBViewer3D />}
      </main>
    </div>
  )
}

export default App
