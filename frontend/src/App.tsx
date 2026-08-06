import {
  Aperture,
  BookOpen,
  Box,
  Camera,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  CloudOff,
  Download,
  ExternalLink,
  FileBox,
  FileImage,
  Focus,
  Heart,
  History,
  Image as ImageIcon,
  ImagePlus,
  Layers3,
  LoaderCircle,
  Maximize2,
  Paintbrush,
  RefreshCw,
  Rotate3D,
  ScanLine,
  Search,
  Settings2,
  SlidersHorizontal,
  Sparkles,
  Split,
  Trash2,
  WandSparkles,
  X,
} from "lucide-react";
import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { ApiError, localApi } from "./api";
import type { JobStreamState } from "./api";
import type {
  ConnectionState,
  EngineCapabilities,
  EngineHealth,
  EngineProfile,
  GenerationJob,
  OperationKind,
  TransformSpec,
  TrellisQuality,
} from "./types";
import type { ViewerHandle } from "./Viewer";

const Viewer = lazy(() => import("./Viewer"));

const FAVORITES_KEY = "forge3d:favourite-job-ids";
const FALLBACK_PROFILE: EngineProfile = {
  id: "8gb",
  label: "RTX 40 · 8 GB",
  vramLabel: "8 GB VRAM",
  description: "Perfil equilibrado para geração local.",
};
const FALLBACK_QUALITIES: TrellisQuality[] = [
  {
    id: "profile-8gb",
    label: "Perfil instalado — 512 px / atlas 1024 px",
    description: "Limite seguro detectado para o perfil ativo.",
    resolution: 512,
    atlas: 1024,
    available: true,
  },
];

type Page = "home" | "assets" | "docs";
type ViewMode = "perspective" | "front" | "side";
type ActiveRail = "image" | "model" | "split" | "remesh" | "texture" | "edit";
type HistoryStatus = "all" | GenerationJob["status"];
type AdvancedSettings = {
  background: "auto" | "birefnet" | "threshold";
  uv: "xatlas" | "box";
  maxTokens: string;
  remeshBand: string;
  decimationGrid: string;
  webp: boolean;
  gss: string;
  gsh: string;
  flashAttention: boolean;
  f32: boolean;
  ultraQuality: "economy" | "full";
  ultraSteps: string;
  ultraLatents: string;
  ultraChunk: string;
  ultraOctree: string;
  ultraScale: string;
  ultraLowVram: boolean;
  translation: [string, string, string];
  rotation: [string, string, string];
  scale: [string, string, string];
};

const railItems: Array<{
  id: ActiveRail;
  label: string;
  icon: typeof ImageIcon;
}> = [
  { id: "image", label: "Imagem", icon: ImageIcon },
  { id: "model", label: "Modelo", icon: WandSparkles },
  { id: "split", label: "Dividir", icon: Split },
  { id: "remesh", label: "Remesh", icon: ScanLine },
  { id: "texture", label: "Textura", icon: Paintbrush },
  { id: "edit", label: "Editar", icon: Settings2 },
];

function readIds(key: string): Set<string> {
  try {
    const value = JSON.parse(localStorage.getItem(key) || "[]");
    return new Set(
      Array.isArray(value)
        ? value.filter((item): item is string => typeof item === "string")
        : [],
    );
  } catch {
    return new Set();
  }
}
function writeIds(key: string, values: Set<string>) {
  try {
    localStorage.setItem(key, JSON.stringify([...values]));
  } catch {
    /* Local history remains optional. */
  }
}
function errorText(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Não foi possível concluir esta ação agora.";
}
function isRunning(job?: GenerationJob | null): boolean {
  return job?.status === "queued" || job?.status === "running";
}
function statusName(status?: GenerationJob["status"]): string {
  const names: Record<NonNullable<GenerationJob["status"]>, string> = {
    uploading: "Enviando imagem",
    queued: "Na fila da GPU",
    running: "Gerando modelo",
    completed: "Modelo pronto",
    failed: "Geração interrompida",
    cancelled: "Geração cancelada",
  };
  return status ? names[status] : "Pronto para criar";
}
function prettyTool(tool?: string): string {
  const value = (tool || "").toLowerCase();
  if (value.includes("ultrashape")) return "UltraShape";
  if (value.includes("trellis")) return "TRELLIS 2";
  if (value.includes("valid")) return "Auditoria GLB";
  return tool || "TRELLIS 2";
}
function stageText(job?: GenerationJob | null): string {
  if (job?.events?.length)
    return job.events.at(-1)?.message || job.currentStage || "Processando";
  if (job?.currentStage || job?.stage)
    return job.currentStage || job.stage || "Processando";
  if (job?.status === "queued") return "Aguardando a GPU local";
  if (job?.status === "running")
    return "TRELLIS 2 gerando malha, UV e materiais PBR";
  if (job?.status === "completed")
    return job.validation?.valid
      ? "GLB e materiais validados"
      : "Resultado disponível para auditoria";
  return "Envie uma imagem para começar";
}
function formatTime(seconds?: number): string {
  if (seconds === undefined || seconds < 0) return "—";
  const total = Math.round(seconds);
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return minutes
    ? `${minutes} min ${String(rest).padStart(2, "0")} s`
    : `${rest} s`;
}
function formatCount(value?: number): string {
  return value
    ? new Intl.NumberFormat("pt-BR", {
        notation: value > 9999 ? "compact" : "standard",
        maximumFractionDigits: 1,
      }).format(value)
    : "—";
}
function formatDate(value?: string): string {
  return value
    ? new Intl.DateTimeFormat("pt-BR", {
        dateStyle: "short",
        timeStyle: "short",
      }).format(new Date(value))
    : "Sem data";
}
function statusClass(status?: GenerationJob["status"]): string {
  return `status-chip ${status || "queued"}`;
}

async function inspectReferenceImage(file: File): Promise<string | undefined> {
  const objectUrl = URL.createObjectURL(file);
  try {
    const image = await new Promise<HTMLImageElement>((resolve, reject) => {
      const next = new Image();
      next.onload = () => resolve(next);
      next.onerror = () => reject(new Error("imagem inválida"));
      next.src = objectUrl;
    });
    const longest = Math.max(image.naturalWidth, image.naturalHeight) || 1;
    const scale = Math.min(1, 256 / longest);
    const width = Math.max(1, Math.round(image.naturalWidth * scale));
    const height = Math.max(1, Math.round(image.naturalHeight * scale));
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (!context) return undefined;
    context.drawImage(image, 0, 0, width, height);
    const pixels = context.getImageData(0, 0, width, height).data;
    const edge: number[] = [];
    for (let y = 0; y < height; y += 1)
      for (let x = 0; x < width; x += 1)
        if (x === 0 || y === 0 || x === width - 1 || y === height - 1) {
          const offset = (y * width + x) * 4;
          edge.push(pixels[offset], pixels[offset + 1], pixels[offset + 2]);
        }
    const background = edge.length
      ? [0, 1, 2].map((channel) =>
          Math.round(
            edge
              .filter((_, index) => index % 3 === channel)
              .reduce((sum, value) => sum + value, 0) /
              (edge.length / 3),
          ),
        )
      : [255, 255, 255];
    let foreground = 0;
    let borderForeground = 0;
    let border = 0;
    for (let y = 0; y < height; y += 1)
      for (let x = 0; x < width; x += 1) {
        const offset = (y * width + x) * 4;
        const delta = Math.hypot(
          pixels[offset] - background[0],
          pixels[offset + 1] - background[1],
          pixels[offset + 2] - background[2],
        );
        const marked = pixels[offset + 3] > 18 && delta > 42;
        if (marked) foreground += 1;
        if (x === 0 || y === 0 || x === width - 1 || y === height - 1) {
          border += 1;
          if (marked) borderForeground += 1;
        }
      }
    if (foreground / (width * height) < 0.12)
      return "O objeto parece pequeno na imagem. Aproxime e centralize o assunto para evitar uma malha fraca.";
    if (border && borderForeground / border > 0.42)
      return "O fundo parece confuso ou conectado ao objeto. Um fundo simples reduz peças soltas e melhora a textura.";
    return undefined;
  } catch {
    return undefined;
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}

export default function App() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<ViewerHandle>(null);
  const objectUrlRef = useRef<string | undefined>(undefined);
  const [page, setPage] = useState<Page>("home");
  const [connection, setConnection] = useState<ConnectionState>("checking");
  const [health, setHealth] = useState<EngineHealth | null>(null);
  const [capabilities, setCapabilities] = useState<EngineCapabilities | null>(
    null,
  );
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string>();
  const [prompt, setPrompt] = useState("");
  const [trellisQualityId, setTrellisQualityId] = useState("profile-8gb");
  const [ultrashapeMode, setUltrashapeMode] = useState<"auto" | "off">("auto");
  const [seed, setSeed] = useState("");
  const [view, setView] = useState<ViewMode>("perspective");
  const [activeRail, setActiveRail] = useState<ActiveRail>("model");
  const [rightPanel, setRightPanel] = useState<"assets" | "properties">(
    "assets",
  );
  const [job, setJob] = useState<GenerationJob | null>(null);
  const [history, setHistory] = useState<GenerationJob[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [historyQuery, setHistoryQuery] = useState("");
  const [historyStatus, setHistoryStatus] = useState<HistoryStatus>("all");
  const [favouritesOnly, setFavouritesOnly] = useState(false);
  const [favourites, setFavourites] = useState<Set<string>>(() =>
    readIds(FAVORITES_KEY),
  );
  const [targetTriangles, setTargetTriangles] = useState("300000");
  const [advanced, setAdvanced] = useState<AdvancedSettings>({
    background: "auto",
    uv: "xatlas",
    maxTokens: "49152",
    remeshBand: "",
    decimationGrid: "",
    webp: false,
    gss: "",
    gsh: "",
    flashAttention: true,
    f32: false,
    ultraQuality: "economy",
    ultraSteps: "12",
    ultraLatents: "8192",
    ultraChunk: "2048",
    ultraOctree: "512",
    ultraScale: "0.99",
    ultraLowVram: true,
    translation: ["0", "0", "0"],
    rotation: ["0", "0", "0"],
    scale: ["1", "1", "1"],
  });
  const [modelCache, setModelCache] = useState<Record<string, string>>({});
  const [isUploading, setIsUploading] = useState(false);
  const [notice, setNotice] = useState("");
  const [lastError, setLastError] = useState("");
  const [modelError, setModelError] = useState("");
  const [imageWarning, setImageWarning] = useState("");
  const [isDragging, setIsDragging] = useState(false);
  const [clock, setClock] = useState(Date.now());
  const [streamState, setStreamState] = useState<JobStreamState>("disabled");

  const activeProfile = health?.activeProfile || FALLBACK_PROFILE;
  const trellisQualities = capabilities?.trellisQualities.length
    ? capabilities.trellisQualities
    : FALLBACK_QUALITIES;
  const selectedQuality =
    trellisQualities.find((quality) => quality.id === trellisQualityId) ||
    trellisQualities[0];
  const ultraAvailable = capabilities?.ultrashapeAvailable === true;
  const busy = isUploading || isRunning(job);
  const generatedModelUrl =
    job?.status === "completed"
      ? modelCache[job.id] || localApi.resolveAssetUrl(job.output?.url)
      : undefined;
  const progress = isUploading ? 7 : job?.progress || 0;
  const elapsed =
    job?.elapsedSeconds ??
    (job?.createdAt && busy
      ? Math.max(
          0,
          Math.floor((clock - new Date(job.createdAt).getTime()) / 1000),
        )
      : undefined);
  const isVerified =
    job?.status === "completed" && job.validation?.valid === true;
  const projectName =
    file?.name.replace(/\.[^/.]+$/, "") ||
    job?.inputFilename?.replace(/\.[^/.]+$/, "") ||
    "Sem projeto aberto";
  const engineLabel =
    connection === "checking"
      ? "Verificando engine"
      : connection === "offline"
        ? "Engine offline"
        : health?.demoMode
          ? "Diagnóstico local"
          : "Engine local online";

  const mergeHistory = useCallback((next: GenerationJob) => {
    setHistory((current) => [
      next,
      ...current.filter((item) => item.id !== next.id),
    ]);
  }, []);
  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    setHistoryError("");
    try {
      setHistory(await localApi.jobs(200));
    } catch (error) {
      setHistoryError(errorText(error));
    } finally {
      setHistoryLoading(false);
    }
  }, []);
  const refreshConnection = useCallback(async () => {
    setConnection("checking");
    try {
      const nextHealth = await localApi.health();
      setHealth(nextHealth);
      try {
        const nextCapabilities = await localApi.capabilities();
        setCapabilities(nextCapabilities);
        setTrellisQualityId((current) =>
          nextCapabilities.trellisQualities.some(
            (quality) => quality.id === current,
          )
            ? current
            : nextCapabilities.trellisQualities.find(
                (quality) => quality.available !== false,
              )?.id || current,
        );
      } catch {
        setCapabilities(null);
      }
      setConnection("ready");
    } catch (error) {
      setConnection("offline");
      setHealth(null);
      setLastError(errorText(error));
    }
  }, []);

  useEffect(() => {
    void refreshConnection();
    void loadHistory();
  }, [loadHistory, refreshConnection]);
  useEffect(() => {
    writeIds(FAVORITES_KEY, favourites);
  }, [favourites]);
  useEffect(() => {
    if (!notice) return undefined;
    const timeout = window.setTimeout(() => setNotice(""), 4400);
    return () => window.clearTimeout(timeout);
  }, [notice]);
  useEffect(
    () => () => {
      if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    },
    [],
  );
  useEffect(() => {
    if (!busy) return undefined;
    const interval = window.setInterval(() => setClock(Date.now()), 1000);
    return () => window.clearInterval(interval);
  }, [busy]);
  useEffect(() => {
    if (!job?.id || !isRunning(job)) {
      setStreamState("disabled");
      return undefined;
    }
    let active = true;
    const accept = (next: GenerationJob) => {
      if (!active) return;
      setJob(next);
      mergeHistory(next);
      if (next.status === "completed")
        setNotice(
          next.validation?.valid
            ? "Modelo pronto e validado."
            : "Modelo concluído; confira a auditoria.",
        );
      if (next.status === "failed")
        setLastError(next.error || "A geração não foi concluída.");
    };
    const closeStream = localApi.subscribeJob(job.id, accept, setStreamState);
    const poll = async () => {
      try {
        accept(await localApi.job(job.id));
      } catch (error) {
        if (active) setLastError(`Acompanhamento pausado: ${errorText(error)}`);
      }
    };
    void poll();
    const interval = window.setInterval(() => void poll(), 1400);
    return () => {
      active = false;
      closeStream?.();
      window.clearInterval(interval);
    };
  }, [job?.id, job?.status, mergeHistory]);
  useEffect(() => {
    if (!job?.id || job.status !== "completed") return;
    const url = localApi.resolveAssetUrl(job.output?.url);
    if (url)
      setModelCache((current) =>
        current[job.id] === url ? current : { ...current, [job.id]: url },
      );
  }, [job]);

  const visibleHistory = useMemo(
    () =>
      history.filter((item) => {
        if (historyStatus !== "all" && item.status !== historyStatus)
          return false;
        if (favouritesOnly && !(item.favorite || favourites.has(item.id)))
          return false;
        const haystack =
          `${item.id} ${item.inputFilename || ""} ${item.prompt || ""} ${item.currentTool || ""}`.toLowerCase();
        return haystack.includes(historyQuery.trim().toLowerCase());
      }),
    [favourites, favouritesOnly, history, historyQuery, historyStatus],
  );

  function chooseFile(nextFile: File | undefined) {
    if (!nextFile) return;
    if (
      !["image/png", "image/jpeg", "image/webp", "image/bmp"].includes(
        nextFile.type,
      )
    ) {
      setLastError("Escolha uma imagem PNG, JPG, WEBP ou BMP.");
      return;
    }
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    const nextPreview = URL.createObjectURL(nextFile);
    objectUrlRef.current = nextPreview;
    setFile(nextFile);
    setPreviewUrl(nextPreview);
    setJob(null);
    setModelError("");
    setLastError("");
    setImageWarning("");
    setPage("home");
    void inspectReferenceImage(nextFile).then((warning) => {
      if (warning) setImageWarning(warning);
    });
    setNotice(
      "Imagem carregada. A qualidade será limitada pelo perfil instalado.",
    );
  }
  function clearProject() {
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    objectUrlRef.current = undefined;
    setFile(null);
    setPreviewUrl(undefined);
    setJob(null);
    setImageWarning("");
    setModelError("");
    if (fileInputRef.current) fileInputRef.current.value = "";
  }
  async function toggleFavourite(jobId: string) {
    const current = history.find((item) => item.id === jobId);
    const nextFavorite = !(current?.favorite || favourites.has(jobId));
    try {
      const next = await localApi.patchJob(jobId, { favorite: nextFavorite });
      mergeHistory(next);
      setFavourites((items) => {
        const copied = new Set(items);
        nextFavorite ? copied.add(jobId) : copied.delete(jobId);
        return copied;
      });
    } catch (error) {
      setLastError(
        `Não foi possível atualizar o favorito: ${errorText(error)}`,
      );
    }
  }
  async function deleteJob(jobId: string) {
    if (
      !window.confirm(
        "Excluir este job e seus arquivos locais? Esta ação não pode ser desfeita.",
      )
    )
      return;
    try {
      await localApi.deleteJob(jobId);
      setHistory((items) => items.filter((item) => item.id !== jobId));
      setFavourites((items) => {
        const copied = new Set(items);
        copied.delete(jobId);
        return copied;
      });
      if (job?.id === jobId) clearProject();
      setNotice("Job e arquivos associados foram excluídos da engine local.");
    } catch (error) {
      setLastError(`Não foi possível excluir o job: ${errorText(error)}`);
    }
  }
  async function runOperation(kind: OperationKind) {
    if (!job || job.status !== "completed") {
      setNotice(
        "Conclua ou reabra um modelo validado antes de executar uma operação.",
      );
      return;
    }
    const operationCapability = capabilities?.operationCapabilities?.[kind];
    if (
      operationCapability
        ? !operationCapability.available
        : !capabilities?.operationKinds.includes(kind)
    ) {
      setLastError(
        operationCapability?.detail ||
          capabilities?.operationsDetail ||
          "O worker local para esta operação não está disponível.",
      );
      return;
    }
    const numericTarget = Number.parseInt(targetTriangles, 10);
    try {
      const vector = (
        values: [string, string, string],
        fallback: number,
      ): [number, number, number] =>
        values.map((value) =>
          Number.isFinite(Number(value)) ? Number(value) : fallback,
        ) as [number, number, number];
      const transform: TransformSpec | undefined =
        kind === "transform"
          ? {
              translation: vector(advanced.translation, 0),
              rotation_degrees: vector(advanced.rotation, 0),
              scale: vector(advanced.scale, 1),
            }
          : undefined;
      const next = await localApi.createOperation(job.id, {
        kind,
        targetTriangles:
          (kind === "simplify" || kind === "remesh") &&
          Number.isFinite(numericTarget)
            ? numericTarget
            : undefined,
        transform,
      });
      setJob(next);
      mergeHistory(next);
      setNotice(`${kind} enviado para a fila local como operação derivada.`);
    } catch (error) {
      setLastError(`Não foi possível iniciar ${kind}: ${errorText(error)}`);
    }
  }
  async function reopenJob(jobId: string) {
    try {
      const next = await localApi.job(jobId);
      setJob(next);
      mergeHistory(next);
      setPage("home");
      setRightPanel("properties");
      setModelError("");
      const source = localApi.resolveAssetUrl(
        localApi.uploadUrl(next.inputUploadId),
      );
      if (source) setPreviewUrl(source);
      setFile(null);
      setNotice(
        "Job reaberto. O modelo e a auditoria foram restaurados do histórico local.",
      );
    } catch (error) {
      setLastError(errorText(error));
    }
  }
  async function handleGenerate() {
    if (!file) {
      setActiveRail("image");
      setNotice("Adicione uma imagem antes de iniciar a geração.");
      return;
    }
    setLastError("");
    setModelError("");
    setIsUploading(true);
    try {
      const upload = await localApi.upload(file);
      const numericSeed = Number.parseInt(seed, 10);
      const optionalInt = (value: string) =>
        value.trim() && Number.isFinite(Number(value))
          ? Number.parseInt(value, 10)
          : undefined;
      const optionalFloat = (value: string) =>
        value.trim() && Number.isFinite(Number(value))
          ? Number(value)
          : undefined;
      // "auto" resolves to the one-shot trellis-cli first.  Do not route a
      // normal Forge3D job through the legacy resident HTTP server: it would
      // require TRELLIS_AUTOSTART and retain VRAM between jobs.
      const next = await localApi.createJob({
        uploadId: upload.id,
        prompt: prompt.trim() || undefined,
        outputFormat: "glb",
        adapter: "auto",
        pipelineMode: "trellis_detail",
        options: {
          texture_resolution: selectedQuality?.textureResolution || 1024,
          target_triangles: Number.isFinite(
            Number.parseInt(targetTriangles, 10),
          )
            ? Number.parseInt(targetTriangles, 10)
            : undefined,
          mesh_quality: selectedQuality?.id.includes("balance")
            ? "balanced"
            : "high",
          trellis_quality_id: selectedQuality?.id,
          trellis_background_removal: advanced.background,
          trellis_uv_mode: advanced.uv,
          trellis_max_tokens: optionalInt(advanced.maxTokens),
          trellis_remesh_band: optionalInt(advanced.remeshBand),
          trellis_decimation_grid: optionalInt(advanced.decimationGrid),
          trellis_webp: advanced.webp,
          trellis_gss: optionalFloat(advanced.gss),
          trellis_gsh: optionalFloat(advanced.gsh),
          trellis_flash_attention: advanced.flashAttention,
          trellis_f32: advanced.f32,
          ultrashape: ultrashapeMode,
          ultrashape_quality: advanced.ultraQuality,
          ultrashape_steps: optionalInt(advanced.ultraSteps),
          ultrashape_num_latents: optionalInt(advanced.ultraLatents),
          ultrashape_chunk_size: optionalInt(advanced.ultraChunk),
          ultrashape_octree_resolution: optionalInt(advanced.ultraOctree),
          ultrashape_scale: optionalFloat(advanced.ultraScale),
          ultrashape_low_vram: advanced.ultraLowVram,
          seed: Number.isFinite(numericSeed) ? numericSeed : undefined,
        },
      });
      setJob(next);
      mergeHistory(next);
      setNotice(
        "Job enviado para a fila GPU local. Acompanhe as etapas reais no rodapé.",
      );
    } catch (error) {
      setLastError(errorText(error));
    } finally {
      setIsUploading(false);
    }
  }
  async function handleCancel() {
    if (!job?.id || !isRunning(job)) return;
    try {
      const next = await localApi.cancel(job.id);
      setJob(next);
      mergeHistory(next);
      setNotice("Cancelamento solicitado.");
    } catch (error) {
      setLastError(errorText(error));
    }
  }
  function selectRail(item: ActiveRail) {
    setActiveRail(item);
    if (item === "image") fileInputRef.current?.click();
    if (item === "texture" && !job?.validation)
      setNotice(
        "A auditoria de textura PBR aparecerá após uma geração concluída.",
      );
    const operationByRail: Partial<Record<ActiveRail, OperationKind>> = {
      split: "split",
      remesh: "remesh",
      texture: "retexture",
      edit: "transform",
    };
    const capability = operationByRail[item]
      ? capabilities?.operationCapabilities?.[operationByRail[item]!]
      : undefined;
    if (capability && !capability.available)
      setNotice(
        capability.detail ||
          "Instale e valide o worker Blender para habilitar esta operação.",
      );
  }
  function centerViewer() {
    if (!generatedModelUrl) {
      setNotice("Gere ou reabra um modelo antes de centralizar o viewport.");
      return;
    }
    viewerRef.current?.center();
  }
  function captureViewer() {
    if (!generatedModelUrl) {
      setNotice("Gere ou reabra um modelo antes de capturar.");
      return;
    }
    if (viewerRef.current?.capture()) setNotice("Captura PNG baixada.");
  }
  async function fullscreenViewer() {
    if (!viewportRef.current?.requestFullscreen) {
      setNotice("Tela cheia não é suportada neste navegador.");
      return;
    }
    try {
      await viewportRef.current.requestFullscreen();
    } catch (error) {
      setLastError(errorText(error));
    }
  }

  return (
    <main className="forge-shell">
      <header className="forge-header">
        <button
          className="forge-brand"
          type="button"
          onClick={() => setPage("home")}
          aria-label="Forge3D Local Studio"
        >
          <span className="brand-glyph">
            <Box size={18} />
          </span>
          <strong>
            FORGE<span>3D</span>
          </strong>
        </button>
        <span className="header-divider" />
        <button
          className="space-switch"
          type="button"
          onClick={() => setPage("home")}
        >
          Espaço 3D <ChevronDown size={13} />
        </button>
        <nav className="top-nav" aria-label="Navegação principal">
          <button
            className={page === "home" ? "active" : ""}
            type="button"
            onClick={() => setPage("home")}
          >
            Início
          </button>
          <button
            className={page === "assets" ? "active" : ""}
            type="button"
            onClick={() => {
              setPage("assets");
              void loadHistory();
            }}
          >
            Ativos
          </button>
          <button
            className={page === "docs" ? "active" : ""}
            type="button"
            onClick={() => setPage("docs")}
          >
            Documentação
          </button>
        </nav>
        <div className="header-side">
          <button
            className={`connection-pill ${connection}`}
            type="button"
            onClick={() => void refreshConnection()}
          >
            {connection === "checking" ? (
              <LoaderCircle className="spin" size={14} />
            ) : connection === "offline" ? (
              <CloudOff size={14} />
            ) : (
              <CheckCircle2 size={14} />
            )}
            <span>{engineLabel}</span>
          </button>
          <button
            className="circle-control"
            type="button"
            title="Atualizar conexão e histórico"
            aria-label="Atualizar estado da engine"
            onClick={() => {
              void refreshConnection();
              void loadHistory();
            }}
          >
            <RefreshCw size={15} />
          </button>
        </div>
      </header>
      {page === "home" && (
        <HomeStudio
          activeRail={activeRail}
          setRail={selectRail}
          fileInputRef={fileInputRef}
          previewUrl={previewUrl}
          file={file}
          chooseFile={chooseFile}
          clearProject={clearProject}
          imageWarning={imageWarning}
          isDragging={isDragging}
          setIsDragging={setIsDragging}
          trellisQualities={trellisQualities}
          selectedQuality={selectedQuality}
          selectQuality={setTrellisQualityId}
          ultraAvailable={ultraAvailable}
          ultraDetail={capabilities?.ultrashapeDetail}
          ultrashapeMode={ultrashapeMode}
          setUltrashapeMode={setUltrashapeMode}
          seed={seed}
          setSeed={setSeed}
          prompt={prompt}
          setPrompt={setPrompt}
          advanced={advanced}
          setAdvanced={setAdvanced}
          activeProfile={activeProfile}
          capabilities={capabilities}
          lastError={lastError}
          clearError={() => setLastError("")}
          busy={busy}
          uploading={isUploading}
          generate={handleGenerate}
          job={job}
          generatedModelUrl={generatedModelUrl}
          modelError={modelError}
          setModelError={setModelError}
          viewerRef={viewerRef}
          viewportRef={viewportRef}
          view={view}
          setView={setView}
          centerViewer={centerViewer}
          captureViewer={captureViewer}
          fullscreenViewer={fullscreenViewer}
          projectName={projectName}
          progress={progress}
          elapsed={elapsed}
          verified={isVerified}
          streamState={streamState}
          cancel={handleCancel}
          rightPanel={rightPanel}
          setRightPanel={setRightPanel}
          reopenJob={reopenJob}
          openDocs={() => setPage("docs")}
          targetTriangles={targetTriangles}
          setTargetTriangles={setTargetTriangles}
          runOperation={runOperation}
        />
      )}
      {page === "assets" && (
        <AssetsPage
          history={visibleHistory}
          allHistoryCount={history.length}
          loading={historyLoading}
          error={historyError}
          query={historyQuery}
          setQuery={setHistoryQuery}
          status={historyStatus}
          setStatus={setHistoryStatus}
          favouritesOnly={favouritesOnly}
          setFavouritesOnly={setFavouritesOnly}
          favourites={favourites}
          toggleFavourite={toggleFavourite}
          reopen={reopenJob}
          remove={deleteJob}
          reload={() => void loadHistory()}
        />
      )}
      {page === "docs" && (
        <DocsPage
          activeProfile={activeProfile}
          capabilities={capabilities}
          onHome={() => setPage("home")}
        />
      )}
      {notice && (
        <div className="forge-toast" role="status">
          <CheckCircle2 size={15} />
          {notice}
        </div>
      )}
    </main>
  );
}

type HomeProps = {
  activeRail: ActiveRail;
  setRail: (item: ActiveRail) => void;
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  previewUrl?: string;
  file: File | null;
  chooseFile: (file?: File) => void;
  clearProject: () => void;
  imageWarning: string;
  isDragging: boolean;
  setIsDragging: (value: boolean) => void;
  trellisQualities: TrellisQuality[];
  selectedQuality?: TrellisQuality;
  selectQuality: (id: string) => void;
  ultraAvailable: boolean;
  ultraDetail?: string;
  ultrashapeMode: "auto" | "off";
  setUltrashapeMode: (mode: "auto" | "off") => void;
  seed: string;
  setSeed: (value: string) => void;
  prompt: string;
  setPrompt: (value: string) => void;
  advanced: AdvancedSettings;
  setAdvanced: React.Dispatch<React.SetStateAction<AdvancedSettings>>;
  activeProfile: EngineProfile;
  capabilities: EngineCapabilities | null;
  lastError: string;
  clearError: () => void;
  busy: boolean;
  uploading: boolean;
  generate: () => void;
  job: GenerationJob | null;
  generatedModelUrl?: string;
  modelError: string;
  setModelError: (value: string) => void;
  viewerRef: React.RefObject<ViewerHandle | null>;
  viewportRef: React.RefObject<HTMLDivElement | null>;
  view: ViewMode;
  setView: (view: ViewMode) => void;
  centerViewer: () => void;
  captureViewer: () => void;
  fullscreenViewer: () => void;
  projectName: string;
  progress: number;
  elapsed?: number;
  verified: boolean;
  streamState: JobStreamState;
  cancel: () => void;
  rightPanel: "assets" | "properties";
  setRightPanel: (value: "assets" | "properties") => void;
  reopenJob: (id: string) => void;
  openDocs: () => void;
  targetTriangles: string;
  setTargetTriangles: (value: string) => void;
  runOperation: (kind: OperationKind) => void;
};

function HomeStudio(props: HomeProps) {
  const {
    activeRail,
    setRail,
    fileInputRef,
    previewUrl,
    file,
    chooseFile,
    clearProject,
    imageWarning,
    isDragging,
    setIsDragging,
    trellisQualities,
    selectedQuality,
    selectQuality,
    ultraAvailable,
    ultraDetail,
    ultrashapeMode,
    setUltrashapeMode,
    seed,
    setSeed,
    prompt,
    setPrompt,
    advanced,
    setAdvanced,
    activeProfile,
    capabilities,
    lastError,
    clearError,
    busy,
    uploading,
    generate,
    job,
    generatedModelUrl,
    modelError,
    setModelError,
    viewerRef,
    viewportRef,
    view,
    setView,
    centerViewer,
    captureViewer,
    fullscreenViewer,
    projectName,
    progress,
    elapsed,
    verified,
    streamState,
    cancel,
    rightPanel,
    setRightPanel,
    reopenJob,
    openDocs,
    targetTriangles,
    setTargetTriangles,
    runOperation,
  } = props;
  const railTitle =
    activeRail === "image"
      ? "Imagem de referência"
      : activeRail === "remesh"
        ? "Topologia e remesh"
        : activeRail === "texture"
          ? "Texturas PBR"
          : activeRail === "split"
            ? "Separar objetos"
            : activeRail === "edit"
              ? "Edição local"
              : "Gerar modelo";
  const operationByRail: Partial<Record<ActiveRail, OperationKind>> = {
    split: "split",
    remesh: "remesh",
    texture: "retexture",
    edit: "transform",
  };
  const requestedOperation = operationByRail[activeRail];
  const requestedCapability = requestedOperation
    ? capabilities?.operationCapabilities?.[requestedOperation]
    : undefined;
  const operationSupported = Boolean(
    requestedOperation &&
    (requestedCapability
      ? requestedCapability.available
      : capabilities?.operationKinds.includes(requestedOperation)),
  );
  const simplifyCapability = capabilities?.operationCapabilities?.simplify;
  const simplifySupported = simplifyCapability
    ? simplifyCapability.available
    : Boolean(capabilities?.operationKinds.includes("simplify"));
  const operationReason =
    !job || job.status !== "completed"
      ? "Reabra ou conclua um GLB validado antes de criar uma operação derivada."
      : !operationSupported
        ? requestedCapability?.detail ||
          capabilities?.operationsDetail ||
          "O worker local de operações não está configurado."
        : "";
  const latestActivity = [
    ...(job?.events || []),
    ...(job?.logs || []).map((log) => ({
      message: log.message,
      tool: log.source,
      at: log.at,
    })),
  ]
    .slice(-5)
    .reverse();
  return (
    <div className="forge-workspace">
      <aside className="tool-rail" aria-label="Ferramentas do estúdio">
        {railItems.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.id}
              title={item.label}
              aria-label={item.label}
              className={
                activeRail === item.id ? "rail-tool selected" : "rail-tool"
              }
              type="button"
              onClick={() => setRail(item.id)}
            >
              <Icon size={18} />
              <span>{item.label}</span>
            </button>
          );
        })}
        <div className="rail-spacer" />
        <button
          className="rail-tool"
          type="button"
          title="Abrir documentação local"
          onClick={openDocs}
        >
          <CircleHelp size={18} />
          <span>Ajuda</span>
        </button>
      </aside>
      <aside className="studio-panel" aria-label="Painel de geração">
        <div className="panel-title">
          <span className="panel-breadcrumb">
            <WandSparkles size={14} /> {railTitle}
          </span>
          <h1>{activeRail === "model" ? "Imagem para 3D" : railTitle}</h1>
        </div>
        <div className="work-tabs">
          <button
            type="button"
            className={activeRail !== "texture" ? "active" : ""}
            onClick={() => setRail("model")}
          >
            <WandSparkles size={14} /> Modelo
          </button>
          <button
            type="button"
            className={activeRail === "texture" ? "active" : ""}
            onClick={() => setRail("texture")}
          >
            <Paintbrush size={14} /> Textura PBR
          </button>
        </div>
        <input
          ref={fileInputRef}
          className="visually-hidden"
          type="file"
          accept="image/png,image/jpeg,image/webp,image/bmp"
          onChange={(event) => chooseFile(event.target.files?.[0])}
        />
        {(activeRail === "image" || activeRail === "model") && (
          <>
            <section className="upload-card">
              {previewUrl ? (
                <>
                  <div className="uploaded-thumb">
                    <img src={previewUrl} alt="Referência selecionada" />
                    <button
                      type="button"
                      onClick={clearProject}
                      aria-label="Remover imagem"
                    >
                      <Trash2 size={15} />
                    </button>
                  </div>
                  <div className="upload-file-name">
                    <FileImage size={14} />
                    <strong title={file?.name || job?.inputFilename}>
                      {file?.name ||
                        job?.inputFilename ||
                        "Imagem de referência"}
                    </strong>
                    <span>
                      {file
                        ? "Imagem pronta para novo job"
                        : "Referência restaurada do histórico"}
                    </span>
                  </div>
                </>
              ) : (
                <button
                  className={`upload-drop ${isDragging ? "dragging" : ""}`}
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  onDragOver={(event) => {
                    event.preventDefault();
                    setIsDragging(true);
                  }}
                  onDragLeave={() => setIsDragging(false)}
                  onDrop={(event) => {
                    event.preventDefault();
                    setIsDragging(false);
                    chooseFile(event.dataTransfer.files[0]);
                  }}
                >
                  <span className="drop-icon">
                    <ImagePlus size={21} />
                  </span>
                  <strong>Enviar imagem</strong>
                  <small>PNG, JPG, WEBP ou BMP · até o limite do perfil</small>
                </button>
              )}
            </section>
            {imageWarning && (
              <div className="image-quality-warning" role="status">
                <CircleHelp size={14} />
                <span>{imageWarning}</span>
              </div>
            )}
          </>
        )}
        {(activeRail === "model" || activeRail === "remesh") && (
          <section className="setting-section">
            <div className="setting-label">
              <span>Qualidade TRELLIS aprovada</span>
              <CircleHelp size={13} />
            </div>
            <div className="quality-list">
              {trellisQualities.map((quality) => (
                <button
                  key={quality.id}
                  type="button"
                  disabled={quality.available === false}
                  title={quality.reason}
                  className={
                    selectedQuality?.id === quality.id
                      ? "quality-option selected"
                      : "quality-option"
                  }
                  onClick={() => selectQuality(quality.id)}
                >
                  <span>
                    <strong>{quality.label}</strong>
                    <small>
                      {quality.description ||
                        `${quality.resolution || "—"} px · atlas ${quality.atlas || "definido pelo perfil"}`}
                    </small>
                  </span>
                  {quality.available === false ? (
                    <em>Indisponível</em>
                  ) : selectedQuality?.id === quality.id ? (
                    <Check size={14} />
                  ) : null}
                </button>
              ))}
            </div>
          </section>
        )}
        {(activeRail === "model" || activeRail === "remesh") && (
          <section className="setting-section">
            <div className="setting-label">
              <span>Refinamento de geometria</span>
              <CircleHelp size={13} />
            </div>
            <div className="ultrashape-control">
              <div>
                <strong>UltraShape</strong>
                <small>
                  {ultraAvailable
                    ? "Worker disponível: o backend fará handoff seguro de VRAM após TRELLIS."
                    : ultraDetail ||
                      "O backend fará preflight. Se indisponível, o resultado TRELLIS base será preservado e o motivo aparecerá no job."}
                </small>
              </div>
              <div className="segmented">
                <button
                  type="button"
                  className={ultrashapeMode === "auto" ? "selected" : ""}
                  onClick={() => setUltrashapeMode("auto")}
                >
                  Automático
                </button>
                <button
                  type="button"
                  className={ultrashapeMode === "off" ? "selected" : ""}
                  onClick={() => setUltrashapeMode("off")}
                >
                  Só TRELLIS
                </button>
              </div>
            </div>
            <p className="capability-note">
              Modelo instalado:{" "}
              {capabilities?.modelSet || "GGUF nativo do perfil"}. Quantização
              não é alterável no navegador.
            </p>
          </section>
        )}
        {requestedOperation && (
          <section className="operation-panel">
            <div>
              <strong>
                {requestedOperation === "split"
                  ? "Separar componentes conectados"
                  : requestedOperation === "remesh"
                    ? "Reconstruir topologia do GLB atual"
                    : requestedOperation === "retexture"
                      ? "Retexturizar o GLB atual com rebake PBR"
                      : "Transformar malha"}
              </strong>
              <small>
                {operationSupported
                  ? "A operação usa o modelo aberto e cria um job derivado; o GLB original sempre será preservado."
                  : operationReason}
              </small>
            </div>
            {requestedOperation === "remesh" && (
              <label>
                Densidade / teto de triângulos
                <input
                  value={targetTriangles}
                  onChange={(event) =>
                    setTargetTriangles(
                      event.target.value.replace(/[^0-9]/g, "").slice(0, 7),
                    )
                  }
                  inputMode="numeric"
                  min="100"
                  max="2000000"
                  disabled={!operationSupported}
                />
                <small>
                  {operationSupported
                    ? "Remesh usa esse orçamento para reconstruir a topologia; Simplificar apenas reduz ao teto, sempre sem regenerar pela imagem."
                    : operationReason}
                </small>
              </label>
            )}
            {requestedOperation === "transform" && (
              <div className="transform-grid">
                <VectorFields
                  label="Posição"
                  values={advanced.translation}
                  update={(translation) =>
                    setAdvanced((current) => ({ ...current, translation }))
                  }
                />
                <VectorFields
                  label="Rotação °"
                  values={advanced.rotation}
                  update={(rotation) =>
                    setAdvanced((current) => ({ ...current, rotation }))
                  }
                />
                <VectorFields
                  label="Escala"
                  values={advanced.scale}
                  update={(scale) =>
                    setAdvanced((current) => ({ ...current, scale }))
                  }
                />
              </div>
            )}
            <button
              type="button"
              disabled={
                !operationSupported || !job || job.status !== "completed"
              }
              title={operationReason || "Criar operação derivada"}
              onClick={() => runOperation(requestedOperation)}
            >
              {operationSupported
                ? requestedOperation === "remesh"
                  ? "Aplicar remesh ao modelo aberto"
                  : "Criar operação derivada"
                : "Worker indisponível"}
            </button>
            {requestedOperation === "remesh" && (
              <button
                type="button"
                className="operation-secondary"
                disabled={
                  !simplifySupported || !job || job.status !== "completed"
                }
                title={
                  simplifyCapability?.detail ||
                  "Reduzir o GLB aberto ao teto definido"
                }
                onClick={() => runOperation("simplify")}
              >
                {simplifySupported
                  ? "Simplificar ao teto"
                  : "Simplificação indisponível"}
              </button>
            )}
          </section>
        )}
        {activeRail === "texture" && job?.validation && (
          <section className="texture-audit">
            <strong>Auditoria PBR do job atual</strong>
            <div>
              <span className={job.validation.hasTexture ? "ok" : ""}>
                Base color
              </span>
              <span
                className={job.validation.hasMetallicRoughnessMap ? "ok" : ""}
              >
                Metal/Rough
              </span>
              <span className={job.validation.hasNormalMap ? "ok" : ""}>
                Normal
              </span>
              <span className={job.validation.hasOcclusionMap ? "ok" : ""}>
                Occlusion
              </span>
            </div>
            <p>
              {job.validation.message ||
                "A auditoria examina os mapas realmente incorporados no GLB."}
            </p>
          </section>
        )}
        <details className="advanced-drawer trellis-compute">
          <summary>
            <SlidersHorizontal size={14} /> Compute e guidance TRELLIS{" "}
            <ChevronDown size={14} />
          </summary>
          <div className="advanced-fields">
            <label>
              GSS
              <input
                value={advanced.gss}
                onChange={(event) =>
                  setAdvanced((current) => ({
                    ...current,
                    gss: event.target.value.replace(/[^0-9.]/g, "").slice(0, 5),
                  }))
                }
                inputMode="decimal"
                placeholder="Padrão runtime"
              />
            </label>
            <label>
              GSH
              <input
                value={advanced.gsh}
                onChange={(event) =>
                  setAdvanced((current) => ({
                    ...current,
                    gsh: event.target.value.replace(/[^0-9.]/g, "").slice(0, 5),
                  }))
                }
                inputMode="decimal"
                placeholder="Padrão runtime"
              />
            </label>
            <label className="check-field">
              <input
                type="checkbox"
                checked={advanced.flashAttention}
                onChange={(event) =>
                  setAdvanced((current) => ({
                    ...current,
                    flashAttention: event.target.checked,
                  }))
                }
              />{" "}
              FlashAttention
            </label>
            <label
              className="check-field"
              title={
                activeProfile.id === "16gb"
                  ? "Compute F32 do trellis-cli"
                  : "Liberado somente pelo perfil de 16 GB"
              }
            >
              <input
                type="checkbox"
                checked={advanced.f32}
                disabled={activeProfile.id !== "16gb"}
                onChange={(event) =>
                  setAdvanced((current) => ({
                    ...current,
                    f32: event.target.checked,
                  }))
                }
              />{" "}
              F32 {activeProfile.id !== "16gb" ? "— requer 16 GB" : ""}
            </label>
          </div>
        </details>
        <details className="advanced-drawer">
          <summary>
            <Settings2 size={14} /> Opções avançadas reais{" "}
            <ChevronDown size={14} />
          </summary>
          <div className="advanced-fields">
            <label>
              Formato
              <select
                value="glb"
                disabled
                title="GLB é o único formato do pipeline PBR"
              >
                <option value="glb">GLB</option>
              </select>
            </label>
            <label>
              Seed
              <input
                value={seed}
                onChange={(event) =>
                  setSeed(
                    event.target.value.replace(/[^0-9]/g, "").slice(0, 10),
                  )
                }
                inputMode="numeric"
                placeholder="Automática"
              />
            </label>
            <label>
              Teto de polígonos
              <input
                value={targetTriangles}
                onChange={(event) =>
                  setTargetTriangles(
                    event.target.value.replace(/[^0-9]/g, "").slice(0, 7),
                  )
                }
                inputMode="numeric"
                min="10000"
                max="2000000"
              />
              <small>
                Reduz somente se a malha exceder o teto; nunca subdivide nem
                inventa detalhe.
              </small>
            </label>
            <label>
              Recorte de fundo
              <select
                value={advanced.background}
                onChange={(event) =>
                  setAdvanced((current) => ({
                    ...current,
                    background: event.target
                      .value as AdvancedSettings["background"],
                  }))
                }
              >
                <option value="auto">Automático</option>
                <option value="birefnet">BiRefNet</option>
                <option value="threshold">Threshold</option>
              </select>
            </label>
            <label>
              UV
              <select
                value={advanced.uv}
                onChange={(event) =>
                  setAdvanced((current) => ({
                    ...current,
                    uv: event.target.value as AdvancedSettings["uv"],
                  }))
                }
              >
                <option value="xatlas">xatlas</option>
                <option value="box">Box UV</option>
              </select>
            </label>
            <label>
              Max tokens
              <input
                value={advanced.maxTokens}
                onChange={(event) =>
                  setAdvanced((current) => ({
                    ...current,
                    maxTokens: event.target.value
                      .replace(/[^0-9]/g, "")
                      .slice(0, 5),
                  }))
                }
                inputMode="numeric"
              />
            </label>
            <label>
              Remesh band
              <input
                value={advanced.remeshBand}
                onChange={(event) =>
                  setAdvanced((current) => ({
                    ...current,
                    remeshBand: event.target.value
                      .replace(/[^0-9]/g, "")
                      .slice(0, 2),
                  }))
                }
                placeholder="Automático"
                inputMode="numeric"
              />
            </label>
            <label>
              Decimation grid
              <input
                value={advanced.decimationGrid}
                onChange={(event) =>
                  setAdvanced((current) => ({
                    ...current,
                    decimationGrid: event.target.value
                      .replace(/[^0-9]/g, "")
                      .slice(0, 4),
                  }))
                }
                placeholder="Automático"
                inputMode="numeric"
              />
            </label>
            <label
              className="check-field"
              title="Desative para exportar PNG sem perda; isso aumenta o tamanho do GLB."
            >
              <input
                type="checkbox"
                checked={advanced.webp}
                onChange={(event) =>
                  setAdvanced((current) => ({
                    ...current,
                    webp: event.target.checked,
                  }))
                }
              />{" "}
              Usar WebP (PNG preserva mais textura)
            </label>
          </div>
          <p className="format-note">
            Resolução, atlas e quantização continuam limitados pelo perfil
            escolhido no instalador.
          </p>
          {ultrashapeMode === "auto" && (
            <fieldset className="ultra-advanced" disabled={!ultraAvailable}>
              <legend>
                UltraShape oficial{" "}
                {ultraAvailable ? "" : "— bloqueado pelo preflight"}
              </legend>
              <div className="advanced-fields">
                <label>
                  Preset
                  <select
                    value={advanced.ultraQuality}
                    onChange={(event) => {
                      const full = event.target.value === "full";
                      setAdvanced((current) => ({
                        ...current,
                        ultraQuality: full ? "full" : "economy",
                        ultraSteps: full ? "50" : "12",
                        ultraLatents: full ? "32768" : "8192",
                        ultraChunk: full ? "8000" : "2048",
                        ultraOctree: full ? "1024" : "512",
                        ultraLowVram: !full,
                      }));
                    }}
                  >
                    <option value="economy">Baixa VRAM</option>
                    <option value="full">Completo</option>
                  </select>
                </label>
                <label>
                  Steps 12–50
                  <input
                    value={advanced.ultraSteps}
                    onChange={(event) =>
                      setAdvanced((current) => ({
                        ...current,
                        ultraSteps: event.target.value
                          .replace(/[^0-9]/g, "")
                          .slice(0, 2),
                      }))
                    }
                    inputMode="numeric"
                    min="12"
                    max="50"
                  />
                </label>
                <label>
                  Latentes
                  <input
                    value={advanced.ultraLatents}
                    onChange={(event) =>
                      setAdvanced((current) => ({
                        ...current,
                        ultraLatents: event.target.value
                          .replace(/[^0-9]/g, "")
                          .slice(0, 5),
                      }))
                    }
                    inputMode="numeric"
                    min="8192"
                    max="32768"
                  />
                </label>
                <label>
                  Chunk size
                  <input
                    value={advanced.ultraChunk}
                    onChange={(event) =>
                      setAdvanced((current) => ({
                        ...current,
                        ultraChunk: event.target.value
                          .replace(/[^0-9]/g, "")
                          .slice(0, 4),
                      }))
                    }
                    inputMode="numeric"
                    min="512"
                    max="8000"
                  />
                </label>
                <label>
                  Octree
                  <input
                    value={advanced.ultraOctree}
                    onChange={(event) =>
                      setAdvanced((current) => ({
                        ...current,
                        ultraOctree: event.target.value
                          .replace(/[^0-9]/g, "")
                          .slice(0, 4),
                      }))
                    }
                    inputMode="numeric"
                    min="256"
                    max="1024"
                  />
                </label>
                <label>
                  Escala
                  <input
                    value={advanced.ultraScale}
                    onChange={(event) =>
                      setAdvanced((current) => ({
                        ...current,
                        ultraScale: event.target.value
                          .replace(/[^0-9.]/g, "")
                          .slice(0, 4),
                      }))
                    }
                    inputMode="decimal"
                  />
                </label>
                <label className="check-field">
                  <input
                    type="checkbox"
                    checked={advanced.ultraLowVram}
                    onChange={(event) =>
                      setAdvanced((current) => ({
                        ...current,
                        ultraLowVram: event.target.checked,
                      }))
                    }
                  />{" "}
                  --low_vram
                </label>
              </div>
              <small>
                {ultraAvailable
                  ? "Estes nomes correspondem diretamente ao infer_dit_refine.py oficial."
                  : ultraDetail ||
                    "Execute a instalação experimental e a inferência de calibração para liberar."}
              </small>
            </fieldset>
          )}
          <label className="prompt-field">
            Direção visual <span>opcional</span>
            <textarea
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder="Ex.: madeira esculpida, acabamento fosco..."
              rows={2}
            />
          </label>
        </details>
        <div className="profile-note">
          <span>
            <Aperture size={15} />
          </span>
          <div>
            <strong>
              {activeProfile.label} · {activeProfile.vramLabel}
            </strong>
            <p>
              Definido pelo instalador. A API recusa tiers acima do perfil e
              serializa o uso da GPU.
            </p>
          </div>
        </div>
        {lastError && (
          <div className="panel-error" role="status">
            <CloudOff size={15} />
            <span>{lastError}</span>
            <button type="button" onClick={clearError} aria-label="Fechar">
              <X size={14} />
            </button>
          </div>
        )}
        <button
          className="generate-cta"
          type="button"
          onClick={generate}
          disabled={busy}
        >
          {busy ? (
            <LoaderCircle className="spin" size={17} />
          ) : (
            <WandSparkles size={17} />
          )}
          <span>
            {uploading
              ? "Enviando imagem"
              : busy
                ? "Geração em andamento"
                : "Gerar modelo 3D"}
          </span>
        </button>
      </aside>
      <section className="viewport-column" aria-label="Viewport de modelo 3D">
        <div className="viewport-breadcrumb">
          <span>
            {activeRail === "texture"
              ? "Auditoria de texturas 3D"
              : "Viewport de modelo 3D"}
          </span>
          <span className="viewport-project">{projectName}</span>
        </div>
        <div className="viewport-canvas" ref={viewportRef}>
          <Suspense
            fallback={
              <div className="viewport-loader">
                <LoaderCircle className="spin" size={18} />
                Abrindo viewport
              </div>
            }
          >
            <Viewer
              ref={viewerRef}
              modelUrl={generatedModelUrl}
              cacheKey={job?.id}
              view={view}
              onLoaded={() => setModelError("")}
              onError={setModelError}
            />
          </Suspense>
          {!generatedModelUrl && (
            <div className="empty-viewport">
              <div className="empty-orbit">
                <Box size={29} />
              </div>
              <strong>
                {file
                  ? "Pronto para gerar o modelo"
                  : "Seu modelo aparecerá aqui"}
              </strong>
              <span>
                {file
                  ? "A imagem está na bancada. Clique em gerar para iniciar."
                  : "Envie uma imagem no painel ao lado ou reabra um ativo."}
              </span>
            </div>
          )}
          {modelError && (
            <div className="viewport-error" role="alert">
              <CloudOff size={16} />
              <div>
                <strong>Não foi possível abrir o modelo</strong>
                <span>{modelError}</span>
              </div>
              <button type="button" onClick={() => setModelError("")}>
                <X size={14} />
              </button>
            </div>
          )}
          <div className="scene-data">
            <span>Topologia</span>
            <strong>{job?.validation?.triangles ? "Triangle" : "—"}</strong>
            <span>Faces</span>
            <strong>{formatCount(job?.validation?.triangles)}</strong>
            <span>Vértices</span>
            <strong>{formatCount(job?.validation?.vertices)}</strong>
          </div>
          <div className="axis-indicator">
            <i className="x">X</i>
            <i className="y">Y</i>
            <i className="z">Z</i>
          </div>
          <div className="viewport-actions">
            <button
              type="button"
              title={
                generatedModelUrl
                  ? "Centralizar e enquadrar o modelo"
                  : "Gere um modelo para centralizar"
              }
              aria-label="Centralizar modelo"
              onClick={centerViewer}
              disabled={!generatedModelUrl}
            >
              <Focus size={17} />
            </button>
            <button
              type="button"
              title={
                generatedModelUrl
                  ? "Baixar captura PNG"
                  : "Gere um modelo para capturar"
              }
              aria-label="Capturar imagem"
              onClick={captureViewer}
              disabled={!generatedModelUrl}
            >
              <Camera size={16} />
            </button>
            <button
              type="button"
              title="Abrir viewport em tela cheia"
              aria-label="Tela cheia"
              onClick={() => void fullscreenViewer()}
            >
              <Maximize2 size={16} />
            </button>
          </div>
          <div className="view-dock">
            <button
              type="button"
              className={view === "perspective" ? "selected" : ""}
              onClick={() => setView("perspective")}
            >
              3D
            </button>
            <button
              type="button"
              className={view === "front" ? "selected" : ""}
              onClick={() => setView("front")}
            >
              Frente
            </button>
            <button
              type="button"
              className={view === "side" ? "selected" : ""}
              onClick={() => setView("side")}
            >
              Lado
            </button>
            <i />
            <span>Arraste para orbitar</span>
          </div>
        </div>
        <section className="generation-console" aria-live="polite">
          <div
            className={`console-icon ${busy ? "working" : verified ? "verified" : ""}`}
          >
            {busy ? (
              <LoaderCircle className="spin" size={18} />
            ) : verified ? (
              <CheckCircle2 size={18} />
            ) : (
              <Sparkles size={18} />
            )}
          </div>
          <div className="console-copy">
            <div>
              <strong>
                {statusName(uploading ? "uploading" : job?.status)}
              </strong>
              {job?.queuePosition ? (
                <span className="queue-badge">Fila #{job.queuePosition}</span>
              ) : null}
            </div>
            <span>
              {uploading
                ? "Preparando a imagem para a fila local"
                : stageText(job)}
            </span>
          </div>
          <div className="console-tool">
            <span>Executando agora</span>
            <strong>
              {busy
                ? prettyTool(job?.currentTool)
                : verified
                  ? "Auditoria concluída"
                  : "TRELLIS 2"}
            </strong>
          </div>
          <div className="console-time">
            <span>Tempo</span>
            <strong>
              {busy
                ? formatTime(elapsed)
                : job?.status === "completed"
                  ? formatTime(job.elapsedSeconds)
                  : "—"}
            </strong>
          </div>
          <div className="console-time eta">
            <span>Estimativa</span>
            <strong>
              {busy
                ? job?.etaSeconds !== undefined
                  ? `~${formatTime(job.etaSeconds)}`
                  : "calculando…"
                : "—"}
            </strong>
            <small>
              {streamState === "live"
                ? "tempo real · SSE"
                : streamState === "connecting"
                  ? "conectando SSE"
                  : "atualização por polling"}
            </small>
          </div>
          <div className="console-progress">
            <div>
              <span style={{ width: `${progress}%` }} />
            </div>
            <small>
              {busy && progress > 0
                ? `${progress}%`
                : busy
                  ? "em processamento"
                  : verified
                    ? "validado"
                    : "aguardando"}
            </small>
          </div>
          <div className="console-actions">
            {isRunning(job) && (
              <button type="button" onClick={cancel}>
                Cancelar
              </button>
            )}
            {job?.status === "completed" && job.id && (
              <a href={localApi.downloadUrl(job.id)}>
                <Download size={15} /> Exportar
              </a>
            )}
          </div>
        </section>
      </section>
      <aside className="inspector-panel" aria-label="Ativos e propriedades">
        <div className="inspector-tabs">
          <button
            type="button"
            className={rightPanel === "assets" ? "active" : ""}
            onClick={() => setRightPanel("assets")}
          >
            <Layers3 size={14} /> Ativos
          </button>
          <button
            type="button"
            className={rightPanel === "properties" ? "active" : ""}
            onClick={() => setRightPanel("properties")}
          >
            <Settings2 size={14} /> Propriedades
          </button>
        </div>
        {rightPanel === "assets" ? (
          <div className="asset-panel">
            <div className="asset-head">
              <span>Projeto</span>
              <button
                type="button"
                title="Atualizar dados do job atual"
                aria-label="Mais opções"
                onClick={() => job && reopenJob(job.id)}
              >
                <RefreshCw size={14} />
              </button>
            </div>
            <div className="asset-grid">
              <button
                className={previewUrl ? "asset-tile selected" : "asset-tile"}
                type="button"
                onClick={() => setRail("image")}
              >
                <div>
                  {previewUrl ? (
                    <img src={previewUrl} alt="Imagem de referência" />
                  ) : (
                    <ImageIcon size={22} />
                  )}
                </div>
                <span>Referência</span>
              </button>
              <button
                className={
                  generatedModelUrl ? "asset-tile selected" : "asset-tile"
                }
                type="button"
                onClick={centerViewer}
                disabled={!generatedModelUrl}
                title={
                  generatedModelUrl
                    ? "Centralizar modelo"
                    : "Modelo ainda não disponível"
                }
              >
                <div className="model-asset">
                  <FileBox size={23} />
                </div>
                <span>Modelo 3D</span>
              </button>
            </div>
            <div className="asset-section">
              <span>Artefatos da geração</span>
              {job?.artifacts?.length ? (
                job.artifacts.map((artifact, index) => (
                  <a
                    key={artifact.id || artifact.name || index}
                    href={localApi.resolveAssetUrl(artifact.url)}
                    className="artifact-row"
                  >
                    <FileBox size={14} />
                    <span>
                      {artifact.label ||
                        artifact.name ||
                        artifact.type ||
                        "Arquivo gerado"}
                    </span>
                    <ChevronRight size={14} />
                  </a>
                ))
              ) : (
                <p>Nenhum artefato disponível ainda.</p>
              )}
            </div>
            {latestActivity.length > 0 && (
              <div className="activity-feed">
                <span>Atividade real</span>
                {latestActivity.map((item, index) => (
                  <div key={`${item.at || index}-${item.message || ""}`}>
                    <strong>{prettyTool(item.tool)}</strong>
                    <p>{item.message}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : (
          <div className="property-panel">
            <PropertyRow
              label="Pipeline"
              value={
                job?.fallbackReason
                  ? "TRELLIS 2 · base preservada"
                  : ultrashapeMode === "auto"
                    ? "TRELLIS 2 + UltraShape"
                    : "TRELLIS 2 · UV + PBR"
              }
            />
            <PropertyRow
              label="Ferramenta"
              value={prettyTool(job?.currentTool)}
            />
            <PropertyRow
              label="Formato"
              value={(job?.output?.format || "glb").toUpperCase()}
            />
            <PropertyRow
              label="Textura"
              value={
                job?.validation?.hasTexture === true
                  ? "Incluída"
                  : job?.status === "completed"
                    ? "Não encontrada"
                    : "Aguardando"
              }
            />
            {job?.fallbackReason && (
              <div className="fallback-note">
                <CircleHelp size={13} />
                <span>{job.fallbackReason}</span>
              </div>
            )}
            <div className="validation-card">
              <div>
                <span>Auditoria de saída</span>
                {verified ? (
                  <em>
                    <CheckCircle2 size={13} /> Validado
                  </em>
                ) : (
                  <em className={job?.status === "completed" ? "warn" : ""}>
                    {job?.status === "completed" ? "Pendente" : "Aguardando"}
                  </em>
                )}
              </div>
              <p>
                {job?.validation?.message ||
                  (verified
                    ? "GLB, malha e materiais passaram na verificação."
                    : "A verificação real aparece quando a geração terminar.")}
              </p>
              <ul>
                <li className={job?.validation?.hasMesh ? "ok" : ""}>Malha</li>
                <li className={job?.validation?.hasUv ? "ok" : ""}>UV</li>
                <li className={job?.validation?.hasTexture ? "ok" : ""}>
                  Base color
                </li>
                <li className={job?.validation?.hasPbrMaterial ? "ok" : ""}>
                  Metal/Rough
                </li>
                <li className={job?.validation?.hasNormalMap ? "ok" : ""}>
                  Normal
                </li>
                <li className={job?.validation?.hasOcclusionMap ? "ok" : ""}>
                  Occlusion
                </li>
              </ul>
            </div>
          </div>
        )}
      </aside>
    </div>
  );
}

type AssetsProps = {
  history: GenerationJob[];
  allHistoryCount: number;
  loading: boolean;
  error: string;
  query: string;
  setQuery: (value: string) => void;
  status: HistoryStatus;
  setStatus: (value: HistoryStatus) => void;
  favouritesOnly: boolean;
  setFavouritesOnly: (value: boolean) => void;
  favourites: Set<string>;
  toggleFavourite: (id: string) => void;
  reopen: (id: string) => void;
  remove: (id: string) => void;
  reload: () => void;
};
function AssetsPage({
  history,
  allHistoryCount,
  loading,
  error,
  query,
  setQuery,
  status,
  setStatus,
  favouritesOnly,
  setFavouritesOnly,
  favourites,
  toggleFavourite,
  reopen,
  remove,
  reload,
}: AssetsProps) {
  return (
    <section className="assets-page">
      <header className="page-heading">
        <div>
          <span>
            <History size={16} /> Biblioteca local
          </span>
          <h1>Ativos e histórico de gerações</h1>
          <p>
            Dados carregados de <code>GET /api/jobs</code>. Favoritos e
            exclusões são persistidos pela engine local.
          </p>
        </div>
        <button
          className="page-refresh"
          type="button"
          onClick={reload}
          disabled={loading}
        >
          {loading ? (
            <LoaderCircle className="spin" size={16} />
          ) : (
            <RefreshCw size={16} />
          )}{" "}
          Atualizar
        </button>
      </header>
      <div className="history-toolbar">
        <label className="history-search">
          <Search size={15} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Buscar por arquivo, ferramenta ou ID"
          />
        </label>
        <label>
          <SlidersHorizontal size={14} /> Status
          <select
            value={status}
            onChange={(event) => setStatus(event.target.value as HistoryStatus)}
          >
            <option value="all">Todos</option>
            <option value="completed">Concluídos</option>
            <option value="running">Em execução</option>
            <option value="queued">Na fila</option>
            <option value="failed">Falhos</option>
            <option value="cancelled">Cancelados</option>
          </select>
        </label>
        <button
          type="button"
          className={favouritesOnly ? "filter-toggle active" : "filter-toggle"}
          onClick={() => setFavouritesOnly(!favouritesOnly)}
        >
          <Heart size={14} fill={favouritesOnly ? "currentColor" : "none"} />{" "}
          Favoritos
        </button>
      </div>
      {error && (
        <div className="history-error">
          <CloudOff size={16} />
          <span>{error}</span>
          <button type="button" onClick={reload}>
            Tentar novamente
          </button>
        </div>
      )}
      <div className="history-summary">
        Exibindo {history.length} de {allHistoryCount} jobs locais.
      </div>
      <div className="history-list">
        {loading && (
          <div className="history-empty">
            <LoaderCircle className="spin" size={21} />
            Carregando histórico local…
          </div>
        )}
        {!loading && !history.length && (
          <div className="history-empty">
            <FileBox size={24} />
            <strong>Nenhum ativo nesta visão</strong>
            <span>Ajuste os filtros ou gere um novo modelo.</span>
          </div>
        )}
        {history.map((item) => {
          const favorite = item.favorite || favourites.has(item.id);
          return (
            <article className="history-card" key={item.id}>
              <div className="history-card-main">
                <button
                  type="button"
                  className={favorite ? "favourite active" : "favourite"}
                  onClick={() => toggleFavourite(item.id)}
                  title={
                    favorite
                      ? "Remover dos favoritos"
                      : "Adicionar aos favoritos"
                  }
                >
                  <Heart size={16} fill={favorite ? "currentColor" : "none"} />
                </button>
                <div className="history-icon">
                  {item.inputUploadId ? (
                    <img src={localApi.uploadUrl(item.inputUploadId)} alt="" />
                  ) : (
                    <FileBox size={19} />
                  )}
                </div>
                <div>
                  <div className="history-title">
                    <strong>
                      {item.metadata?.title ||
                        item.inputFilename ||
                        "Imagem sem nome"}
                    </strong>
                    <span className={statusClass(item.status)}>
                      {statusName(item.status)}
                    </span>
                  </div>
                  <p>
                    {formatDate(item.createdAt)} ·{" "}
                    {prettyTool(item.currentTool || item.pipelineMode)} ·{" "}
                    {item.validation?.triangles
                      ? `${formatCount(item.validation.triangles)} faces`
                      : "topologia pendente"}
                  </p>
                  <small>{item.id}</small>
                </div>
              </div>
              <div className="history-actions">
                <button type="button" onClick={() => reopen(item.id)}>
                  <Rotate3D size={15} /> Reabrir
                </button>
                {item.status === "completed" && (
                  <a href={localApi.downloadUrl(item.id)}>
                    <Download size={15} /> Exportar
                  </a>
                )}
                <button
                  type="button"
                  className="quiet delete"
                  onClick={() => remove(item.id)}
                  title="Excluir job e arquivos locais"
                >
                  <Trash2 size={15} /> Excluir
                </button>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function DocsPage({
  activeProfile,
  capabilities,
  onHome,
}: {
  activeProfile: EngineProfile;
  capabilities: EngineCapabilities | null;
  onHome: () => void;
}) {
  return (
    <section className="docs-page">
      <header className="page-heading">
        <div>
          <span>
            <BookOpen size={16} /> Manual local
          </span>
          <h1>Como usar a Forge3D</h1>
          <p>
            Guia baseado no runtime instalado, sem prometer recursos que a API
            não expõe.
          </p>
        </div>
        <button className="page-refresh" type="button" onClick={onHome}>
          <WandSparkles size={16} /> Novo projeto
        </button>
      </header>
      <div className="docs-grid">
        <article>
          <span>01</span>
          <h2>Prepare a referência</h2>
          <p>
            Use um único objeto, centralizado e com fundo simples. A
            pré-checagem avisa sobre enquadramento que costuma gerar partes
            soltas.
          </p>
        </article>
        <article>
          <span>02</span>
          <h2>Escolha o tier aprovado</h2>
          <p>
            O perfil ativo é <strong>{activeProfile.label}</strong>. Só os tiers
            publicados pela instalação podem ser enviados ao backend.
          </p>
        </article>
        <article>
          <span>03</span>
          <h2>Acompanhe ferramentas reais</h2>
          <p>
            O rodapé recebe snapshots SSE da API local e usa polling se a
            conexão de eventos cair.
          </p>
        </article>
        <article>
          <span>04</span>
          <h2>Valide antes de exportar</h2>
          <p>
            O GLB só é apresentado como validado após auditoria de malha, UV,
            materiais e mapas PBR detectáveis.
          </p>
        </article>
      </div>
      <section className="docs-runtime">
        <h2>Runtime detectado</h2>
        <PropertyRow
          label="Perfil"
          value={`${activeProfile.label} · ${activeProfile.vramLabel}`}
        />
        <PropertyRow
          label="Qualidades aprovadas"
          value={
            capabilities?.trellisQualities
              .map((quality) => quality.label)
              .join(", ") || "Consultando API"
          }
        />
        <PropertyRow
          label="UltraShape"
          value={
            capabilities?.ultrashapeAvailable
              ? "Disponível após preflight"
              : capabilities?.ultrashapeDetail || "Ainda não disponível"
          }
        />
        <PropertyRow
          label="Operações derivadas"
          value={
            capabilities?.operationsAvailable
              ? capabilities.operationKinds.join(", ")
              : capabilities?.operationsDetail || "Worker não configurado"
          }
        />
        <a href={`${localApi.baseUrl}/docs`} target="_blank" rel="noreferrer">
          <ExternalLink size={15} /> Abrir documentação técnica da API
        </a>
      </section>
    </section>
  );
}

function PropertyRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="property-row">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
function VectorFields({
  label,
  values,
  update,
}: {
  label: string;
  values: [string, string, string];
  update: (values: [string, string, string]) => void;
}) {
  return (
    <label>
      {label}
      <span className="vector-fields">
        {(["X", "Y", "Z"] as const).map((axis, index) => (
          <span key={axis}>
            <i>{axis}</i>
            <input
              value={values[index]}
              onChange={(event) => {
                const next = [...values] as [string, string, string];
                next[index] = event.target.value
                  .replace(/[^0-9.-]/g, "")
                  .slice(0, 8);
                update(next);
              }}
              inputMode="decimal"
              aria-label={`${label} ${axis}`}
            />
          </span>
        ))}
      </span>
    </label>
  );
}
