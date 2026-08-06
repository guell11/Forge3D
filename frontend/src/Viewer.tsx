import { Bounds, Center, ContactShadows, Grid, OrbitControls, useGLTF } from '@react-three/drei'
import { Canvas } from '@react-three/fiber'
import { Component, forwardRef, Suspense, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'

export interface ViewerHandle {
  center: () => void
  capture: () => boolean
}

interface ViewerProps {
  modelUrl?: string
  cacheKey?: string
  view: 'perspective' | 'front' | 'side'
  onError?: (message: string) => void
  onLoaded?: () => void
}

class ModelBoundary extends Component<{ children: ReactNode; onError?: (message: string) => void }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  componentDidCatch(error: unknown) {
    const detail = error instanceof Error ? error.message : 'O arquivo 3D não pôde ser aberto no viewport.'
    this.props.onError?.(detail)
  }
  render() { return this.state.failed ? null : this.props.children }
}

function GeneratedModel({ url, onLoaded }: { url: string; onLoaded?: () => void }) {
  const { scene } = useGLTF(url)
  const clone = useMemo(() => scene.clone(true), [scene])
  useEffect(() => { onLoaded?.() }, [onLoaded, url])
  return <primitive object={clone} castShadow receiveShadow />
}

function LoadingGeometry() {
  return <mesh rotation={[0.2, 0.5, 0]}><torusKnotGeometry args={[0.6, 0.08, 80, 10]} /><meshStandardMaterial color="#8068ec" emissive="#6045bf" emissiveIntensity={0.4} roughness={0.32} /></mesh>
}

function cameraFor(view: ViewerProps['view']): [number, number, number] {
  if (view === 'front') return [0, 0.3, 6.2]
  if (view === 'side') return [6.2, 0.3, 0]
  return [4.6, 2.8, 5.2]
}

const Viewer = forwardRef<ViewerHandle, ViewerProps>(function Viewer({ modelUrl, cacheKey, view, onError, onLoaded }, ref) {
  const [frame, setFrame] = useState(0)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)

  useEffect(() => {
    if (modelUrl) useGLTF.preload(modelUrl)
  }, [modelUrl])

  useImperativeHandle(ref, () => ({
    // Recreating the camera/Bounds is deliberate: it fits the complete model
    // again after the user has orbited, panned or switched a history entry.
    center: () => setFrame((value) => value + 1),
    capture: () => {
      const canvas = canvasRef.current
      if (!canvas) return false
      try {
        const link = document.createElement('a')
        link.download = `forge3d-${cacheKey || 'viewport'}.png`
        link.href = canvas.toDataURL('image/png')
        link.click()
        return true
      } catch (error) {
        onError?.(error instanceof Error ? `Não foi possível capturar o viewport: ${error.message}` : 'Não foi possível capturar o viewport.')
        return false
      }
    },
  }), [cacheKey, onError])

  return (
    <Canvas
      key={`${cacheKey || modelUrl || 'empty'}:${view}:${frame}`}
      camera={{ position: cameraFor(view), fov: 40 }}
      dpr={[1, 1.5]}
      shadows
      gl={{ antialias: true, powerPreference: 'high-performance', alpha: false, preserveDrawingBuffer: true }}
      onCreated={({ gl }) => { canvasRef.current = gl.domElement }}
    >
      <color attach="background" args={['#26282d']} />
      <fog attach="fog" args={['#26282d', 9, 19]} />
      <ambientLight intensity={1.15} />
      <hemisphereLight args={['#dce0ed', '#17202a', 0.85]} />
      <directionalLight castShadow position={[4.8, 7, 4]} intensity={2.25} color="#fff3df" shadow-mapSize={[1024, 1024]} />
      <pointLight position={[-4, 1.5, -3]} color="#665dd1" intensity={9} distance={9} />
      <pointLight position={[3, 0, 3]} color="#41afbc" intensity={3} distance={7} />
      <Suspense fallback={<LoadingGeometry />}>
        {modelUrl && <Bounds fit clip observe margin={1.25}><Center><ModelBoundary key={modelUrl} onError={onError}><GeneratedModel url={modelUrl} onLoaded={onLoaded} /></ModelBoundary></Center></Bounds>}
      </Suspense>
      {modelUrl && <ContactShadows position={[0, -1.12, 0]} opacity={0.36} color="#05070a" scale={7} blur={2.4} far={4} />}
      <Grid position={[0, -1.13, 0]} args={[14, 14]} cellSize={0.5} cellThickness={0.42} cellColor="#454950" sectionSize={2} sectionThickness={0.85} sectionColor="#565b64" fadeDistance={11} fadeStrength={1.55} infiniteGrid />
      <OrbitControls makeDefault enablePan enableDamping dampingFactor={0.08} minDistance={2.6} maxDistance={12} maxPolarAngle={Math.PI / 2.02} />
    </Canvas>
  )
})

export default Viewer
