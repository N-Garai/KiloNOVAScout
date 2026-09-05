import { useRef, useMemo } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { Points, PointMaterial } from '@react-three/drei'
import * as THREE from 'three'

function Starfield() {
  const ref = useRef()
  
  const positions = useMemo(() => {
    const pos = new Float32Array(5000 * 3)
    for (let i = 0; i < 5000; i++) {
      pos[i * 3] = (Math.random() - 0.5) * 100
      pos[i * 3 + 1] = (Math.random() - 0.5) * 100
      pos[i * 3 + 2] = (Math.random() - 0.5) * 100
    }
    return pos
  }, [])

  useFrame((state) => {
    if (ref.current) {
      ref.current.rotation.x = state.clock.elapsedTime * 0.05
      ref.current.rotation.y = state.clock.elapsedTime * 0.03
    }
  })

  return (
    <Points ref={ref} positions={positions} stride={3} frustumCulled={false}>
      <PointMaterial
        transparent
        color="#00f5ff"
        size={0.15}
        sizeAttenuation={true}
        depthWrite={false}
        opacity={0.8}
      />
    </Points>
  )
}

export default function StarfieldBackground() {
  return (
    <div className="fixed inset-0 z-0">
      <Canvas camera={{ position: [0, 0, 10] }}>
        <Starfield />
      </Canvas>
      <div className="absolute inset-0 bg-gradient-to-b from-void/50 via-transparent to-void/80 pointer-events-none" />
    </div>
  )
}