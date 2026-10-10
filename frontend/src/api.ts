import type {
  EngineHealth,
  EngineCapabilities,
  EngineProfile,
  GenerationArtifact,
  GenerationJob,
  GenerationOutput,
  GenerationRequest,
  GenerationValidation,
  JobStatus,
  JobMetadata,
  OperationKind,
  TransformSpec,
  UploadedFile,
} from './types'

const configuredBase = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/+$/, '')
const apiBase = configuredBase.endsWith('/api') ? configuredBase : `${configuredBase}/api`
const assetBase = configuredBase.endsWith('/api') ? configuredBase.slice(0, -4) : configuredBase
type JsonRecord = Record<string, unknown>

export class ApiError extends Error {
  constructor(message: string, public readonly status?: number) {
    super(message)
  }
}

function asRecord(value: unknown): JsonRecord {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as JsonRecord) : {}
}
function asString(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value : undefined
}
function asNumber(value: unknown, fallback = 0): number {
  const parsed = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}
function asBoolean(value: unknown): boolean | undefined {
  return typeof value === 'boolean' ? value : undefined
}
function asStatus(value: unknown): JobStatus {
  const status = String(value || 'queued').toLowerCase()
  return ['queued', 'running', 'completed', 'failed', 'cancelled'].includes(status) ? status as JobStatus : 'queued'
}
function endpoint(path: string): string {
  return `${apiBase}${path.startsWith('/') ? path : `/${path}`}`
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(endpoint(path), {
      ...init,
      headers: {
        Accept: 'application/json',
        ...(init?.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
        ...(init?.headers || {}),
      },
    })
  } catch {
    throw new ApiError('Não foi possível alcançar a API configurada. Confira o backend, o endereço do túnel e tente novamente.')
  }
  const rawBody = await response.text()
  let body: unknown = null
  try { body = rawBody ? JSON.parse(rawBody) : null } catch { body = rawBody }
  if (!response.ok) {
    const record = asRecord(body)
    const detail = asString(record.detail) || asString(record.message)
    if (response.status === 401 || response.status === 403) {
      throw new ApiError(
        `A API recusou o acesso (HTTP ${response.status}). Confira autenticação do túnel/API.${detail ? ` ${detail}` : ''}`,
        response.status,
      )
    }
    throw new ApiError(detail || `A API retornou erro ${response.status}.`, response.status)
  }
  return body as T
}

function normalizeProfile(raw: unknown, index: number): EngineProfile {
  const value = asRecord(raw)
  const id = asString(value.id) || asString(value.key) || `profile-${index + 1}`
  const vramGb = asNumber(value.vram_gb, 0)
  return {
    id,
    label: asString(value.label) || asString(value.name) || `Perfil ${id}`,
    vramLabel: asString(value.vram) || asString(value.vram_label) || (vramGb ? `${vramGb} GB VRAM` : id.replace(/gb/i, ' GB')),
    description: asString(value.description) || 'Perfil local otimizado para geração 3D.',
    badge: asString(value.badge),
    recommended: value.recommended === true,
  }
}

function normalizeOutput(raw: unknown): GenerationOutput | null {
  const value = asRecord(raw)
  if (!Object.keys(value).length) return null
  const format = asString(value.format)?.toLowerCase()
  return {
    filename: asString(value.filename) || asString(value.name),
    url: asString(value.url) || asString(value.download_url) || asString(value.path),
    format: format === 'obj' || format === 'glb' ? format : undefined,
  }
}

function normalizeValidation(raw: unknown): GenerationValidation | null {
  const value = asRecord(raw)
  if (!Object.keys(value).length) return null
  const meshes = asNumber(value.meshes || value.mesh_count, 0) || undefined
  const pbrMaterials = asNumber(value.pbr_materials || value.pbrMaterials, 0)
  const status = asString(value.status)
  const warningList = Array.isArray(value.warnings) ? value.warnings.filter((item): item is string => typeof item === 'string') : []
  const errorList = Array.isArray(value.errors) ? value.errors.filter((item): item is string => typeof item === 'string') : []
  return {
    valid: asBoolean(value.valid) ?? asBoolean(value.passed),
    glbValid: asBoolean(value.glb_valid) ?? asBoolean(value.glbValid) ?? (asNumber(value.glb_version, 0) === 2 ? true : undefined),
    hasMesh: asBoolean(value.has_mesh) ?? asBoolean(value.hasMesh) ?? Boolean(meshes),
    hasUv: asBoolean(value.has_uv) ?? asBoolean(value.has_uvs) ?? asBoolean(value.hasUv),
    hasTexture: asBoolean(value.has_texture) ?? asBoolean(value.hasTexture),
    hasPbrMaterial: asBoolean(value.has_pbr_material) ?? asBoolean(value.hasPbrMaterial) ?? (pbrMaterials > 0 ? true : undefined),
    hasNormalMap: asBoolean(value.has_normal_map) ?? asBoolean(value.hasNormalMap),
    hasOcclusionMap: asBoolean(value.has_occlusion_texture) ?? asBoolean(value.has_occlusion_map) ?? asBoolean(value.hasOcclusionTexture) ?? asBoolean(value.hasOcclusionMap),
    hasMetallicRoughnessMap: asBoolean(value.has_metallic_roughness_texture) ?? asBoolean(value.has_metallic_roughness_map) ?? asBoolean(value.hasMetallicRoughnessTexture) ?? asBoolean(value.hasMetallicRoughnessMap),
    materialReport: Object.keys(asRecord(value.material_report || value.materialReport)).length
      ? asRecord(value.material_report || value.materialReport) as Record<string, boolean | number | string>
      : undefined,
    meshes,
    vertices: asNumber(value.vertices || value.vertex_count, 0) || undefined,
    triangles: asNumber(value.triangles || value.triangle_count, 0) || undefined,
    images: asNumber(value.images || value.image_count, 0) || undefined,
    materials: asNumber(value.materials || value.material_count, 0) || undefined,
    message: asString(value.message) || asString(value.detail) || errorList[0] || warningList[0]
      || (status === 'valid_untextured' ? 'GLB válido, mas malha sem textura PBR incorporada.' : undefined),
  }
}

function normalizeArtifact(raw: unknown): GenerationArtifact {
  const value = asRecord(raw)
  return {
    id: asString(value.id),
    name: asString(value.name) || asString(value.filename),
    label: asString(value.label),
    type: asString(value.type) || asString(value.kind),
    url: asString(value.url) || asString(value.path),
    sizeBytes: asNumber(value.size_bytes || value.sizeBytes || value.size, 0) || undefined,
  }
}

function normalizeJob(raw: unknown): GenerationJob {
  const value = asRecord(raw)
  const artifacts = Array.isArray(value.artifacts) ? value.artifacts.map(normalizeArtifact) : []
  const input = asRecord(value.input)
  const metadata = asRecord(value.metadata)
  return {
    id: asString(value.id) || asString(value.job_id) || 'unknown-job',
    status: asStatus(value.status),
    progress: Math.max(0, Math.min(100, asNumber(value.progress))),
    stage: asString(value.stage),
    currentStage: asString(value.current_stage) || asString(value.currentStage),
    currentTool: asString(value.current_tool) || asString(value.currentTool),
    pipelineMode: asString(value.pipeline_mode) || asString(value.pipelineMode),
    profile: asString(value.profile),
    prompt: asString(value.prompt),
    createdAt: asString(value.created_at) || asString(value.createdAt),
    stageStartedAt: asString(value.stage_started_at) || asString(value.stageStartedAt),
    elapsedSeconds: asNumber(value.elapsed_seconds ?? value.elapsedSeconds, 0) || undefined,
    etaSeconds: asNumber(value.eta_seconds ?? value.etaSeconds, 0) || undefined,
    etaConfidence: asString(value.eta_confidence) || asString(value.etaConfidence),
    queuePosition: asNumber(value.queue_position ?? value.queuePosition, 0) || undefined,
    error: asString(value.error) || asString(value.detail),
    output: normalizeOutput(value.output),
    validation: normalizeValidation(value.validation),
    artifacts,
    warnings: Array.isArray(value.warnings) ? value.warnings.filter((item): item is string => typeof item === 'string') : undefined,
    fallbackReason: asString(value.fallback_reason) || asString(value.fallbackReason),
    events: Array.isArray(value.events) ? value.events.map((item) => {
      const event = asRecord(item)
      return {
        at: asString(event.at), stage: asString(event.stage), message: asString(event.message),
        progress: asNumber(event.progress, 0), tool: asString(event.tool), indeterminate: asBoolean(event.indeterminate),
      }
    }) : undefined,
    logs: Array.isArray(value.logs) ? value.logs.map((item) => {
      const log = asRecord(item)
      return { at: asString(log.at), source: asString(log.source), message: asString(log.message) }
    }) : undefined,
    inputUploadId: asString(input.upload_id) || asString(input.uploadId),
    inputFilename: asString(input.filename),
    favorite: asBoolean(value.favorite),
    metadata: Object.keys(metadata).length ? {
      title: asString(metadata.title),
      tags: Array.isArray(metadata.tags) ? metadata.tags.filter((item): item is string => typeof item === 'string') : undefined,
      notes: asString(metadata.notes),
    } : undefined,
    jobKind: asString(value.job_kind) as GenerationJob['jobKind'],
    parentJobId: asString(value.parent_job_id) || asString(value.parentJobId),
    operationTargetTriangles: asNumber(value.operation_target_triangles ?? value.operationTargetTriangles, 0) || undefined,
  }
}

function normalizeCapabilities(raw: unknown): EngineCapabilities {
  const root = asRecord(raw)
  const pipeline = asRecord(root.pipeline || root)
  const trellis = asRecord(pipeline.trellis || root.trellis)
  const activeProfile = asRecord(pipeline.active_profile || root.active_profile)
  const rawQualities = Array.isArray(trellis.qualities)
    ? trellis.qualities
    : Array.isArray(activeProfile.trellis_qualities)
      ? activeProfile.trellis_qualities
      : Array.isArray(root.qualities) ? root.qualities : []
  const refiners = Array.isArray(pipeline.refiners) ? pipeline.refiners : Array.isArray(root.refiners) ? root.refiners : []
  const ultra = asRecord(refiners.find((candidate) => String(asRecord(candidate).id || '').toLowerCase().includes('ultrashape')))
  const faithc = asRecord(refiners.find((candidate) => String(asRecord(candidate).id || '').toLowerCase() === 'faithc'))
  const supportedFaithCResolutions = [128, 256, 512] as const
  const reportedFaithCResolutions = Array.isArray(faithc.resolutions)
    ? faithc.resolutions.filter((value): value is 128 | 256 | 512 => supportedFaithCResolutions.includes(value as 128 | 256 | 512))
    : []
  const faithcResolutions = reportedFaithCResolutions.length ? reportedFaithCResolutions : [...supportedFaithCResolutions]
  const reportedFaithCDefault = asNumber(faithc.recommended_resolution, 256)
  const faithcRecommendedResolution = supportedFaithCResolutions.includes(reportedFaithCDefault as 128 | 256 | 512)
    ? reportedFaithCDefault as 128 | 256 | 512
    : 256
  const operations = asRecord(pipeline.operations || root.operations)
  const operationNames: OperationKind[] = ['split', 'simplify', 'remesh', 'retexture', 'transform']
  const rawByOperation = asRecord(operations.by_operation || operations.byOperation)
  const operationCapabilities = Object.fromEntries(operationNames.map((kind) => {
    const item = asRecord(rawByOperation[kind])
    return [kind, {
      available: item.available === true,
      detail: asString(item.detail),
      preservesPbr: item.preserves_pbr === true || item.preservesPbr === true,
    }]
  })) as EngineCapabilities['operationCapabilities']
  const advertisedOperations = Array.isArray(operations.operations)
    ? operations.operations.filter((kind): kind is OperationKind => typeof kind === 'string' && operationNames.includes(kind as OperationKind))
    : operationNames.filter((kind) => operationCapabilities[kind]?.available)
  return {
    trellisQualities: rawQualities.map((candidate, index) => {
      const value = asRecord(candidate)
      const id = asString(value.id) || `quality-${index + 1}`
      const resolution = asNumber(value.resolution, 0) || undefined
      const atlas = asNumber(value.atlas, 0) || undefined
      const textureResolution = asNumber(value.texture_resolution || value.textureResolution, 0) || undefined
      return {
        id,
        label: asString(value.label) || (resolution ? `${resolution}px` : id),
        description: asString(value.description) || asString(value.detail),
        resolution,
        atlas,
        textureResolution,
        available: value.available !== false,
        reason: asString(value.reason),
      }
    }),
    modelSet: asString(trellis.model_set) || asString(activeProfile.model_set) || asString(asRecord(activeProfile.installed_gguf).id) || asString(root.model_set),
    ultrashapeAvailable: ultra.available === true,
    ultrashapeDetail: asString(ultra.detail) || asString(ultra.reason),
    ultrashapeModes: Array.isArray(ultra.modes) ? ultra.modes.filter((mode): mode is string => typeof mode === 'string') : [],
    faithc: {
      configured: faithc.configured === true,
      available: faithc.available === true,
      detail: asString(faithc.detail),
      probeState: asString(faithc.probe_state) || asString(faithc.probeState),
      resolutions: faithcResolutions,
      recommendedResolution: faithcRecommendedResolution,
      limitations: Array.isArray(faithc.limitations) ? faithc.limitations.filter((item): item is string => typeof item === 'string') : [],
    },
    operationsAvailable: operations.available === true || advertisedOperations.length > 0,
    operationKinds: advertisedOperations,
    operationsDetail: asString(operations.detail),
    operationCapabilities,
  }
}
function jobEnvelope(raw: unknown): GenerationJob {
  const envelope = asRecord(raw)
  return normalizeJob(envelope.job || envelope)
}

export interface JobPage {
  jobs: GenerationJob[]
  total: number
  limit: number
  offset: number
  nextOffset: number | null
}

export interface JobsQuery {
  limit?: number
  offset?: number
  search?: string
  status?: JobStatus
  favorite?: boolean
}

function jobsEnvelope(raw: unknown): JobPage {
  const envelope = asRecord(raw)
  const pagination = asRecord(envelope.pagination)
  const jobs = Array.isArray(envelope.jobs) ? envelope.jobs.map(normalizeJob) : []
  const nextOffsetValue = pagination.next_offset ?? pagination.nextOffset
  const total = asNumber(pagination.total, jobs.length)
  const limit = asNumber(pagination.limit, jobs.length)
  const offset = asNumber(pagination.offset, 0)
  const calculatedNextOffset = jobs.length && offset + jobs.length < total ? offset + jobs.length : null
  return {
    jobs,
    total,
    limit,
    offset,
    nextOffset: typeof nextOffsetValue === 'number' && Number.isFinite(nextOffsetValue)
      ? nextOffsetValue
      : calculatedNextOffset,
  }
}

export type JobStreamState = 'disabled' | 'connecting' | 'live' | 'polling'

export const localApi = {
  baseUrl: assetBase,
  async health(): Promise<EngineHealth> {
    const raw = await request<unknown>('/health')
    const value = asRecord(raw)
    const queue = asRecord(value.queue)
    const hardware = asRecord(value.hardware)
    return {
      status: asString(value.status) || 'ready',
      demoMode: value.demo_mode === true || value.demoMode === true || value.demo_fallback === true,
      queue: asNumber(queue.pending, asNumber(value.queue, 0)),
      activeProfile: Object.keys(asRecord(value.active_profile)).length ? normalizeProfile(value.active_profile, 0) : undefined,
      hardware: {
        detected: hardware.detected === true,
        name: asString(hardware.name),
        memoryTotalMiB: asNumber(hardware.memory_total_mib, 0) || undefined,
        detail: asString(hardware.detail),
      },
    }
  },
  async capabilities(): Promise<EngineCapabilities> {
    return normalizeCapabilities(await request<unknown>('/capabilities'))
  },
  async upload(file: File): Promise<UploadedFile> {
    const formData = new FormData()
    formData.append('file', file)
    const raw = await request<unknown>('/uploads', { method: 'POST', body: formData })
    const upload = asRecord(asRecord(raw).upload || raw)
    const id = asString(upload.id) || asString(upload.upload_id)
    if (!id) throw new ApiError('A API aceitou o upload, mas não retornou um identificador de arquivo.')
    return { id, filename: asString(upload.filename) || file.name, url: asString(upload.url) }
  },
  async createJob(payload: GenerationRequest): Promise<GenerationJob> {
    const raw = await request<unknown>('/jobs', {
      method: 'POST',
      body: JSON.stringify({
        upload_id: payload.uploadId,
        prompt: payload.prompt || undefined,
        output_format: payload.outputFormat,
        adapter: payload.adapter,
        pipeline_mode: payload.pipelineMode,
        options: payload.options,
      }),
    })
    return jobEnvelope(raw)
  },
  async job(jobId: string): Promise<GenerationJob> { return jobEnvelope(await request<unknown>(`/jobs/${encodeURIComponent(jobId)}`)) },
  async jobs(query: JobsQuery = {}): Promise<JobPage> {
    const params = new URLSearchParams()
    params.set('limit', String(Math.max(1, Math.min(query.limit ?? 50, 200))))
    params.set('offset', String(Math.max(0, Math.floor(query.offset ?? 0))))
    if (query.search?.trim()) params.set('search', query.search.trim())
    if (query.status) params.set('status', query.status)
    if (query.favorite !== undefined) params.set('favorite', String(query.favorite))
    return jobsEnvelope(await request<unknown>(`/jobs?${params.toString()}`))
  },
  async cancel(jobId: string): Promise<GenerationJob> { return jobEnvelope(await request<unknown>(`/jobs/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' })) },
  async patchJob(jobId: string, payload: { favorite?: boolean; metadata?: JobMetadata }): Promise<GenerationJob> {
    return jobEnvelope(await request<unknown>(`/jobs/${encodeURIComponent(jobId)}`, { method: 'PATCH', body: JSON.stringify(payload) }))
  },
  async deleteJob(jobId: string): Promise<void> { await request<unknown>(`/jobs/${encodeURIComponent(jobId)}`, { method: 'DELETE' }) },
  async createOperation(jobId: string, payload: { kind: OperationKind; targetTriangles?: number; transform?: TransformSpec }): Promise<GenerationJob> {
    return jobEnvelope(await request<unknown>(`/jobs/${encodeURIComponent(jobId)}/operations`, {
      method: 'POST', body: JSON.stringify({ kind: payload.kind, target_triangles: payload.targetTriangles, transform: payload.transform }),
    }))
  },
  downloadUrl(jobId: string): string { return endpoint(`/jobs/${encodeURIComponent(jobId)}/download`) },
  uploadUrl(uploadId?: string): string | undefined { return uploadId ? endpoint(`/uploads/${encodeURIComponent(uploadId)}/download`) : undefined },
  subscribeJob(jobId: string, onJob: (job: GenerationJob) => void, onState: (state: JobStreamState) => void): (() => void) | undefined {
    if (typeof EventSource === 'undefined') {
      onState('disabled')
      return undefined
    }
    const stream = new EventSource(endpoint(`/jobs/${encodeURIComponent(jobId)}/events`))
    onState('connecting')
    stream.onopen = () => onState('live')
    const receiveSnapshot = (event: MessageEvent) => {
      try { onJob(jobEnvelope(JSON.parse(event.data))) } catch { /* Ignore malformed external stream events. */ }
    }
    stream.addEventListener('snapshot', receiveSnapshot)
    stream.addEventListener('terminal', receiveSnapshot)
    stream.onerror = () => { onState('polling'); stream.close() }
    return () => stream.close()
  },
  resolveAssetUrl(value?: string): string | undefined {
    if (!value) return undefined
    if (/^https?:\/\//i.test(value) || value.startsWith('blob:')) return value
    return `${assetBase}${value.startsWith('/') ? value : `/${value}`}`
  },
}
