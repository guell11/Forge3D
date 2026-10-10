export type ConnectionState = 'checking' | 'ready' | 'offline'

export type JobStatus =
  | 'queued'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'uploading'

export type OutputFormat = 'glb' | 'obj'
export type PipelineMode = 'smart_textured' | 'trellis_detail'

export interface EngineProfile {
  id: string
  label: string
  vramLabel: string
  description: string
  badge?: string
  recommended?: boolean
}

export interface EngineHealth {
  status: string
  demoMode: boolean
  queue?: number
  activeProfile?: EngineProfile
  hardware?: {
    detected: boolean
    name?: string
    memoryTotalMiB?: number
    detail?: string
  }
}

export interface TrellisQuality {
  id: string
  label: string
  description?: string
  resolution?: number
  atlas?: number
  textureResolution?: number
  available?: boolean
  reason?: string
}

export interface EngineCapabilities {
  trellisQualities: TrellisQuality[]
  modelSet?: string
  ultrashapeAvailable: boolean
  ultrashapeDetail?: string
  ultrashapeModes: string[]
  faithc: FaithCCapability
  operationsAvailable: boolean
  operationKinds: OperationKind[]
  operationsDetail?: string
  operationCapabilities: Partial<Record<OperationKind, OperationCapability>>
}

export interface FaithCCapability {
  configured: boolean
  available: boolean
  detail?: string
  probeState?: string
  resolutions: Array<128 | 256 | 512>
  recommendedResolution: 128 | 256 | 512
  limitations: string[]
}

export type OperationKind = 'split' | 'simplify' | 'remesh' | 'retexture' | 'transform'

export interface OperationCapability {
  available: boolean
  detail?: string
  preservesPbr?: boolean
}

export interface JobMetadata {
  title?: string
  tags?: string[]
  notes?: string
}

export interface GenerationOutput {
  filename?: string
  url?: string
  format?: OutputFormat
}

export interface GenerationValidation {
  valid?: boolean
  glbValid?: boolean
  hasMesh?: boolean
  hasUv?: boolean
  hasTexture?: boolean
  hasPbrMaterial?: boolean
  hasNormalMap?: boolean
  hasOcclusionMap?: boolean
  hasMetallicRoughnessMap?: boolean
  materialReport?: Record<string, boolean | number | string>
  meshes?: number
  vertices?: number
  triangles?: number
  images?: number
  materials?: number
  message?: string
}

export interface GenerationArtifact {
  id?: string
  name?: string
  label?: string
  type?: string
  url?: string
  sizeBytes?: number
}

export interface GenerationEvent {
  at?: string
  stage?: string
  message?: string
  progress?: number
  tool?: string
  indeterminate?: boolean
}

export interface GenerationLog {
  at?: string
  source?: string
  message?: string
}

export interface GenerationJob {
  id: string
  status: JobStatus
  progress: number
  stage?: string
  currentStage?: string
  currentTool?: string
  pipelineMode?: string
  profile?: string
  prompt?: string
  createdAt?: string
  stageStartedAt?: string
  elapsedSeconds?: number
  etaSeconds?: number
  etaConfidence?: string
  queuePosition?: number
  error?: string
  output?: GenerationOutput | null
  validation?: GenerationValidation | null
  artifacts?: GenerationArtifact[]
  warnings?: string[]
  fallbackReason?: string
  events?: GenerationEvent[]
  logs?: GenerationLog[]
  inputUploadId?: string
  inputFilename?: string
  favorite?: boolean
  metadata?: JobMetadata
  jobKind?: 'generation' | OperationKind
  parentJobId?: string
  operationTargetTriangles?: number
}

export interface GenerationRequest {
  uploadId: string
  prompt?: string
  outputFormat: OutputFormat
  adapter: 'auto' | 'demo' | 'trellis' | 'trellis-cli'
  pipelineMode?: PipelineMode
  options: {
    resolution?: number
    texture_resolution: number
    target_triangles?: number
    mesh_quality: 'balanced' | 'high'
    trellis_quality_id?: string
    trellis_background_removal?: 'auto' | 'birefnet' | 'threshold'
    trellis_uv_mode?: 'xatlas' | 'box'
    trellis_max_tokens?: number
    trellis_remesh_band?: number
    trellis_decimation_grid?: number
    trellis_webp?: boolean
    trellis_gss?: number
    trellis_gsh?: number
    trellis_flash_attention?: boolean
    trellis_f32?: boolean
    ultrashape?: 'auto' | 'off'
    ultrashape_quality?: 'economy' | 'full'
    ultrashape_steps?: number
    ultrashape_num_latents?: number
    ultrashape_chunk_size?: number
    ultrashape_octree_resolution?: number
    ultrashape_scale?: number
    ultrashape_low_vram?: boolean
    faithc?: 'off' | 'geometry'
    faithc_resolution?: 128 | 256 | 512
    seed?: number
  }
}

export interface TransformSpec {
  translation: [number, number, number]
  rotation_degrees: [number, number, number]
  scale: [number, number, number]
}

export interface UploadedFile {
  id: string
  filename: string
  url?: string
}
