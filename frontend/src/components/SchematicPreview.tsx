import { useState } from 'react'

export default function SchematicPreview() {
  const [file, setFile] = useState<File | null>(null)

  return (
    <div className="max-w-3xl mx-auto">
      <h2 className="text-2xl font-bold mb-4">Schematic Preview</h2>
      <p className="text-neutral-400 mb-4">
        Upload a generated <code>.kicad_sch</code> file or view the latest one here.
      </p>
      <input
        type="file"
        accept=".kicad_sch"
        onChange={(e) => setFile(e.target.files?.[0] || null)}
        className="block mb-4"
      />
      <div className="bg-neutral-800 p-8 rounded text-center min-h-[300px] flex items-center justify-center">
        {file ? (
          <p>Loaded: {file.name}</p>
        ) : (
          <p className="text-neutral-500">No schematic loaded yet.</p>
        )}
      </div>
    </div>
  )
}
