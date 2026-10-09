from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from .profiles import ProfileId


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExportFormat(str, Enum):
    GLB = "glb"
    OBJ = "obj"


class PipelineMode(str, Enum):
    """Generation workflow selected for a job.

    TRELLIS is now the default local pipeline. ``smart_textured`` remains only
    as a backwards-compatible API value and is mapped to TRELLIS as well.
    """

    SMART_TEXTURED = "smart_textured"
    TRELLIS_DETAIL = "trellis_detail"


class EtaConfidence(str, Enum):
    INITIAL = "initial"
    LEARNING = "learning"
    MEASURED = "measured"
    UNAVAILABLE = "unavailable"


class UltraShapeMode(str, Enum):
    """Whether the job may use the verified UltraShape worker."""

    AUTO = "auto"
    OFF = "off"


class UltraShapeQuality(str, Enum):
    """Published execution presets, not model quantizations."""

    ECONOMY = "economy"
    FULL = "full"


class FaithCMode(str, Enum):
    """FaithC is an explicit geometry-only reconstruction, disabled by default."""

    OFF = "off"
    GEOMETRY = "geometry"


class TrellisBackgroundRemoval(str, Enum):
    AUTO = "auto"
    BIREFNET = "birefnet"
    THRESHOLD = "threshold"


class TrellisUvMode(str, Enum):
    XATLAS = "xatlas"
    BOX = "box"


class JobKind(str, Enum):
    GENERATION = "generation"
    SPLIT = "split"
    SIMPLIFY = "simplify"
    REMESH = "remesh"
    RETEXTURE = "retexture"
    TRANSFORM = "transform"


OPERATION_KINDS = {
    JobKind.SPLIT,
    JobKind.SIMPLIFY,
    JobKind.REMESH,
    JobKind.RETEXTURE,
    JobKind.TRANSFORM,
}


class UploadMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    filename: str
    stored_filename: str
    content_type: str
    size: int
    created_at: datetime
    url: str


class GenerationOptions(BaseModel):
    # The UI may evolve faster than a particular local generator. Unknown
    # presentation controls are ignored rather than making an otherwise valid
    # image-to-3D request fail with 422.
    model_config = ConfigDict(extra="ignore")

    seed: int | None = Field(default=None, ge=0, le=2_147_483_647)
    resolution: int | None = Field(default=None, ge=128, le=2048)
    remove_background: bool | None = None
    mesh_quality: str | None = Field(default=None, max_length=64)
    texture_resolution: int | None = Field(default=None, ge=128, le=8192)
    # Final triangle ceiling. Forge3D only reduces when the generated result
    # exceeds it; it never subdivides a smaller mesh to invent detail.
    target_triangles: int | None = Field(default=None, ge=10_000, le=2_000_000)
    trellis_quality_id: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    # These map directly to supported trellis-cli switches. The installer
    # remains the authority for profile/quality ceilings in ``main.py``.
    trellis_background_removal: TrellisBackgroundRemoval = TrellisBackgroundRemoval.AUTO
    trellis_uv_mode: TrellisUvMode = TrellisUvMode.XATLAS
    trellis_max_tokens: int | None = Field(default=None, ge=1_024, le=65_536)
    trellis_remesh_band: int | None = Field(default=None, ge=0, le=64)
    trellis_decimation_grid: int | None = Field(default=None, ge=0, le=1_024)
    trellis_webp: bool | None = None
    trellis_gss: float | None = Field(default=None, ge=0.0, le=30.0)
    trellis_gsh: float | None = Field(default=None, ge=0.0, le=30.0)
    trellis_flash_attention: bool | None = None
    trellis_f32: bool = False
    # ``auto`` is deliberate: when the local worker has passed calibration it
    # is used, otherwise the pipeline clearly retains the TRELLIS base output.
    ultrashape: UltraShapeMode = UltraShapeMode.AUTO
    ultrashape_quality: UltraShapeQuality | None = None
    # Official ``scripts/infer_dit_refine.py`` controls. They are only used
    # after the isolated worker has passed its real CUDA/import/inference
    # calibration; otherwise the pipeline preserves the TRELLIS result.
    ultrashape_steps: int | None = Field(default=None, ge=12, le=50)
    ultrashape_num_latents: int | None = Field(default=None, ge=8_192, le=32_768)
    ultrashape_chunk_size: int | None = Field(default=None, ge=512, le=8_000)
    ultrashape_octree_resolution: int | None = Field(default=None, ge=256, le=1_024)
    ultrashape_scale: float | None = Field(default=None, ge=0.1, le=1.5)
    ultrashape_low_vram: bool | None = None
    faithc: FaithCMode = FaithCMode.OFF
    faithc_resolution: Literal[128, 256, 512] = 256
    # Compatibility with earlier clients. ``refine=true`` maps to auto; an
    # explicit ``ultrashape=off`` always wins.
    refine: bool = False


class JobMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=140)
    tags: list[str] = Field(default_factory=list, max_length=16)
    notes: str | None = Field(default=None, max_length=2_000)

    def normalized(self) -> "JobMetadata":
        tags: list[str] = []
        for raw in self.tags:
            tag = " ".join(raw.strip().split())[:40]
            if tag and tag.lower() not in {item.lower() for item in tags}:
                tags.append(tag)
        title = " ".join(self.title.split())[:140] if self.title else None
        notes = self.notes.strip()[:2_000] if self.notes else None
        return JobMetadata(title=title or None, tags=tags, notes=notes or None)


class TransformSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    translation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation_degrees: tuple[float, float, float] = (0.0, 0.0, 0.0)
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)


class OperationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: JobKind
    target_triangles: int | None = Field(default=None, ge=100, le=2_000_000)
    transform: TransformSpec | None = None
    metadata: JobMetadata | None = None


class JobPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    favorite: bool | None = None
    metadata: JobMetadata | None = None


class CreateJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upload_id: str = Field(min_length=1, max_length=80)
    profile: ProfileId | None = None
    adapter: str = Field(default="auto", min_length=1, max_length=64)
    pipeline_mode: PipelineMode = PipelineMode.TRELLIS_DETAIL
    # ``generation`` is the only accepted value in POST /api/jobs. Operation
    # jobs are created from a completed parent through the dedicated endpoint.
    job_kind: JobKind = JobKind.GENERATION
    parent_job_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    metadata: JobMetadata | None = None
    output_format: ExportFormat = ExportFormat.GLB
    prompt: str | None = Field(default=None, max_length=2_000)
    options: GenerationOptions = Field(default_factory=GenerationOptions)


class JobInput(BaseModel):
    upload_id: str
    filename: str
    content_type: str


class JobOutput(BaseModel):
    filename: str
    format: ExportFormat
    size: int
    url: str
    download_url: str


class JobEvent(BaseModel):
    at: datetime
    stage: str
    message: str
    progress: Annotated[int, Field(ge=0, le=100)]
    tool: str | None = None
    indeterminate: bool = False


class JobLog(BaseModel):
    """A short, scrubbed line emitted by a local worker command."""

    at: datetime
    source: str
    message: str = Field(min_length=1, max_length=500)


class JobArtifact(BaseModel):
    kind: str = Field(min_length=1, max_length=48)
    label: str = Field(min_length=1, max_length=120)
    filename: str = Field(min_length=1, max_length=255)
    size: int = Field(ge=0)
    url: str
    media_type: str


class OutputValidation(BaseModel):
    """Inspectable technical audit of an exported model.

    A GLB can be valid but untextured.  That distinction is retained so the
    UI never presents an untextured mesh as a textured/PBR result.
    """

    validated_at: datetime
    format: ExportFormat
    passed: bool
    status: str
    file_size: int = Field(ge=0)
    glb_version: int | None = None
    scenes: int = Field(default=0, ge=0)
    meshes: int = Field(default=0, ge=0)
    nodes: int = Field(default=0, ge=0)
    vertices: int = Field(default=0, ge=0)
    triangles: int = Field(default=0, ge=0)
    has_uvs: bool = False
    images: int = Field(default=0, ge=0)
    textures: int = Field(default=0, ge=0)
    materials: int = Field(default=0, ge=0)
    pbr_materials: int = Field(default=0, ge=0)
    has_texture: bool = False
    base_color_textures: int = Field(default=0, ge=0)
    metallic_roughness_textures: int = Field(default=0, ge=0)
    normal_textures: int = Field(default=0, ge=0)
    occlusion_textures: int = Field(default=0, ge=0)
    has_base_color_texture: bool = False
    has_metallic_roughness_texture: bool = False
    has_normal_map: bool = False
    has_occlusion_texture: bool = False
    image_dimensions: list["ImageDimension"] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ImageDimension(BaseModel):
    """A detected embedded image used by an audited GLB material."""

    index: int = Field(ge=0)
    mime_type: str | None = None
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)


class JobRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    status: JobStatus
    progress: Annotated[int, Field(ge=0, le=100)] = 0
    stage: str = "queued"
    current_stage: str = "queued"
    stage_started_at: datetime | None = None
    current_tool: str | None = None
    progress_indeterminate: bool = False
    elapsed_seconds: int = Field(default=0, ge=0)
    estimated_total_seconds: int | None = Field(default=None, ge=0)
    eta_seconds: int | None = Field(default=None, ge=0)
    eta_confidence: EtaConfidence = EtaConfidence.UNAVAILABLE
    queue_position: int | None = Field(default=None, ge=0)
    profile: ProfileId
    adapter_requested: str
    adapter_used: str | None = None
    pipeline_mode: PipelineMode = PipelineMode.TRELLIS_DETAIL
    job_kind: JobKind = JobKind.GENERATION
    parent_job_id: str | None = None
    operation_target_triangles: int | None = Field(default=None, ge=100)
    operation_transform: TransformSpec | None = None
    metadata: JobMetadata = Field(default_factory=JobMetadata)
    favorite: bool = False
    output_format: ExportFormat
    prompt: str | None = None
    options: GenerationOptions
    input: JobInput
    output: JobOutput | None = None
    artifacts: list[JobArtifact] = Field(default_factory=list)
    validation: OutputValidation | None = None
    fallback_reason: str | None = None
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)
    events: list[JobEvent] = Field(default_factory=list)
    logs: list[JobLog] = Field(default_factory=list)
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime


class MessageResponse(BaseModel):
    message: str
