import { Canvas } from '@react-three/fiber'

function Board() {
  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]}>
      <boxGeometry args={[4, 3, 0.05]} />
      <meshStandardMaterial color="#2e7d32" />
    </mesh>
  )
}

function Traces() {
  return (
    <group>
      <mesh position={[-0.5, 0.03, 0]}>
        <boxGeometry args={[2, 0.02, 0.01]} />
        <meshStandardMaterial color="#fbbf24" />
      </mesh>
      <mesh position={[0.8, -0.5, 0]}>
        <boxGeometry args={[0.02, 1.5, 0.01]} />
        <meshStandardMaterial color="#fbbf24" />
      </mesh>
    </group>
  )
}

export default function PCBViewer3D() {
  return (
    <div className="h-[80vh]">
      <h2 className="text-2xl font-bold mb-2">3D PCB Preview</h2>
      <p className="text-neutral-400 mb-4">Powered by Three.js + Nebius backend rendering (WIP).</p>
      <Canvas camera={{ position: [0, 0, 6] }} className="bg-neutral-950 rounded">
        <ambientLight intensity={0.5} />
        <pointLight position={[10, 10, 10]} />
        <Board />
        <Traces />
      </Canvas>
    </div>
  )
}
