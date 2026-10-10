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
  ImagePlus,
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
  useRef,
  useState,
} from "react";
import { ApiError, localApi } from "./api";
import type { JobStreamState } from "./api";
import {
  canChangeReference,
  getGenerationReadiness,
  isGenerationBusy,
} from "./generationReadiness";
import type {
  GenerationActivity,
  GenerationBlockReason,
} from "./generationReadiness";
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
function generationReasonText(reason: GenerationBlockReason): string {
  switch (reason) {
    case "choose-image":
      return "Escolha uma imagem para começar.";
    case "busy":
      return "Geração em andamento. Aguarde concluir antes de mudar a imagem.";
    case "connecting":
      return "Conectando ao serviço local.";
    case "offline":
      return "Sem conexão. Atualize o estado e tente novamente.";
    case "capabilities":
      return "Recursos de geração indisponíveis. Atualize ou consulte Ajuda.";
    case "quality":
      return "Nenhuma qualidade de geração está disponível nesta instalação.";
    case "faithc":
      return "FaithC não está configurado. Desative ou consulte Ajuda.";
    case "demo":
      return "Geração indisponível em modo de diagnóstico. Consulte Ajuda.";
    default:
      return "Pronto para gerar.";
  }
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
  const [job, setJob] = useState<GenerationJob | null>(null);
  const [operationParent, setOperationParent] = useState<{
    job: GenerationJob;
    url: string;
  } | null>(null);
  const [history, setHistory] = useState<GenerationJob[]>([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [historyNextOffset, setHistoryNextOffset] = useState<number | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyLoadingMore, setHistoryLoadingMore] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [historyQuery, setHistoryQuery] = useState("");
  const [historyStatus, setHistoryStatus] = useState<HistoryStatus>("all");
  const [favouritesOnly, setFavouritesOnly] = useState(false);
  const [favourites, setFavourites] = useState<Set<string>>(() =>
    readIds(FAVORITES_KEY),
  );
  const [targetTriangles, setTargetTriangles] = useState("300000");
  const [faithcMode, setFaithcMode] = useState<"off" | "geometry">("off");
  const [faithcResolution, setFaithcResolution] = useState<128 | 256 | 512>(256);
  const [advanced, setAdvanced] = useState<AdvancedSettings>({
    background: "auto",
    uv: "xatlas",
    maxTokens: "16384",
    remeshBand: "",
    decimationGrid: "8",
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
  const imageAnalysisVersionRef = useRef(0);
  const historyRequestVersionRef = useRef(0);
  const historyOffsetRef = useRef<number | null>(null);
  const historyReloadRef = useRef<() => void>(() => undefined);
  const historyFiltersRef = useRef({
    query: historyQuery,
    status: historyStatus,
    favouritesOnly,
    favourites,
  });
  historyFiltersRef.current = { query: historyQuery, status: historyStatus, favouritesOnly, favourites };

  const activeProfile = health?.activeProfile;
  const trellisQualities = capabilities?.trellisQualities || [];
  const selectedQuality = trellisQualities.find(
    (quality) => quality.id === trellisQualityId,
  );
  const ultraAvailable = capabilities?.ultrashapeAvailable === true;
  const activity: GenerationActivity = isUploading
    ? "uploading"
    : job?.status || null;
  const busy = isGenerationBusy(activity);
  const generatedModelUrl =
    job?.status === "completed"
      ? modelCache[job.id] || localApi.resolveAssetUrl(job.output?.url)
      : undefined;
  const displayedModelUrl = generatedModelUrl || operationParent?.url;
  const displayedJob = generatedModelUrl ? job : operationParent?.job || job;
  const downloadJobId =
    generatedModelUrl && job?.status === "completed"
      ? job.id
      : operationParent?.job.id || job?.id;
  const progress = job?.progress || 0;
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
  const runtimeReadiness = getGenerationReadiness({
    hasFile: true,
    activity: null,
    connection,
    capabilities,
    selectedQuality,
    faithcMode,
    demoMode: health?.demoMode === true,
  });
  const engineLabel =
    runtimeReadiness.reason === "connecting"
      ? "Conectando"
      : runtimeReadiness.reason === "offline"
        ? "Sem conexão"
        : runtimeReadiness.canGenerate
          ? "Pronto para gerar"
          : "Instalação pendente";

  const mergeHistory = useCallback((next: GenerationJob) => {
    const filters = historyFiltersRef.current;
    const query = filters.query.trim().toLowerCase().split(/\s+/).filter(Boolean).join(" ");
    const haystack = [
      next.id,
      next.inputFilename || "",
      next.prompt || "",
      next.metadata?.title || "",
      next.metadata?.notes || "",
      (next.metadata?.tags || []).join(" "),
      next.jobKind || "",
    ].filter(Boolean).join(" ").toLowerCase();
    const matches = (filters.status === "all" || next.status === filters.status)
      && (!filters.favouritesOnly || next.favorite || filters.favourites.has(next.id))
      && (!query || haystack.includes(query));
    setHistory((current) => {
      const exists = current.some((item) => item.id === next.id);
      const withoutCurrent = current.filter((item) => item.id !== next.id);
      if (!matches) return withoutCurrent;
      return exists ? [next, ...withoutCurrent] : current;
    });
  }, []);
  const loadHistory = useCallback(async (append = false) => {
    const offset = append ? historyOffsetRef.current : 0;
    if (offset === null) return;
    const requestVersion = ++historyRequestVersionRef.current;
    if (append) setHistoryLoadingMore(true);
    else setHistoryLoading(true);
    setHistoryError("");
    try {
      const page = await localApi.jobs({
        limit: 50,
        offset,
        search: historyQuery,
        status: historyStatus === "all" ? undefined : historyStatus,
        favorite: favouritesOnly ? true : undefined,
      });
      if (requestVersion !== historyRequestVersionRef.current) return;
      setHistory((current) => {
        if (!append) return page.jobs;
        const seen = new Set(current.map((item) => item.id));
        return [...current, ...page.jobs.filter((item) => !seen.has(item.id))];
      });
      setHistoryTotal(page.total);
      historyOffsetRef.current = page.nextOffset;
      setHistoryNextOffset(page.nextOffset);
    } catch (error) {
      if (requestVersion === historyRequestVersionRef.current)
        setHistoryError(errorText(error));
    } finally {
      if (requestVersion === historyRequestVersionRef.current) {
        setHistoryLoading(false);
        setHistoryLoadingMore(false);
      }
    }
  }, [favouritesOnly, historyQuery, historyStatus]);
  historyReloadRef.current = () => { void loadHistory(); };
  const refreshConnection = useCallback(async () => {
    setConnection("checking");
    try {
      const nextHealth = await localApi.health();
      setHealth(nextHealth);
      let capabilityError = "";
      try {
        const nextCapabilities = await localApi.capabilities();
        setCapabilities(nextCapabilities);
        setFaithcResolution((current) => nextCapabilities.faithc.resolutions.includes(current)
          ? current
          : nextCapabilities.faithc.recommendedResolution);
        setTrellisQualityId((current) =>
          nextCapabilities.trellisQualities.some(
            (quality) => quality.id === current,
          )
            ? current
            : nextCapabilities.trellisQualities.find(
                (quality) => quality.available !== false,
              )?.id || current,
        );
      } catch (error) {
        setCapabilities(null);
        capabilityError = `Não foi possível carregar os recursos disponíveis da engine: ${errorText(error)}`;
      }
      setConnection("ready");
      setLastError(capabilityError);
    } catch (error) {
      setConnection("offline");
      setHealth(null);
      setLastError(errorText(error));
    }
  }, []);

  useEffect(() => {
    void refreshConnection();
  }, [refreshConnection]);
  useEffect(() => {
    const requestVersion = ++historyRequestVersionRef.current;
    const timeout = window.setTimeout(() => {
      if (requestVersion === historyRequestVersionRef.current) void loadHistory();
    }, historyQuery.trim() ? 250 : 0);
    return () => window.clearTimeout(timeout);
  }, [loadHistory]);
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
    let terminalRefreshDone = false;
    let pollInFlight = false;
    let pollInterval: number | undefined;
    const accept = (next: GenerationJob) => {
      if (!active) return;
      setJob(next);
      mergeHistory(next);
      if (!terminalRefreshDone && ["completed", "failed", "cancelled"].includes(next.status)) {
        terminalRefreshDone = true;
        historyReloadRef.current();
      }
      if (next.status === "completed")
        setNotice(
          next.validation?.valid
            ? "Modelo pronto e validado."
            : "Modelo concluído; confira a auditoria.",
        );
      if (next.status === "failed")
        setLastError(next.error || "A geração não foi concluída.");
    };
    const poll = async () => {
      if (!active || pollInFlight) return;
      pollInFlight = true;
      try {
        accept(await localApi.job(job.id));
      } catch (error) {
        if (active) setLastError(`Acompanhamento pausado: ${errorText(error)}`);
      } finally {
        pollInFlight = false;
      }
    };
    const startPolling = () => {
      if (!active || pollInterval !== undefined) return;
      setStreamState("polling");
      void poll();
      pollInterval = window.setInterval(() => void poll(), 1400);
    };
    const closeStream = localApi.subscribeJob(job.id, accept, (state) => {
      if (!active) return;
      setStreamState(state);
      if (state === "disabled" || state === "polling") startPolling();
      if (state === "live" && pollInterval !== undefined) {
        window.clearInterval(pollInterval);
        pollInterval = undefined;
      }
    });
    if (!closeStream) startPolling();
    return () => {
      active = false;
      closeStream?.();
      if (pollInterval !== undefined) window.clearInterval(pollInterval);
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

  function chooseFile(nextFile: File | undefined) {
    if (!nextFile) return;
    if (!canChangeReference(activity)) {
      setNotice(generationReasonText("busy"));
      return;
    }
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
    const analysisVersion = ++imageAnalysisVersionRef.current;
    objectUrlRef.current = nextPreview;
    setFile(nextFile);
    setPreviewUrl(nextPreview);
    setJob(null);
    setOperationParent(null);
    setModelError("");
    setLastError("");
    setImageWarning("");
    setPage("home");
    void inspectReferenceImage(nextFile).then((warning) => {
      if (analysisVersion === imageAnalysisVersionRef.current && objectUrlRef.current === nextPreview)
        setImageWarning(warning || "");
    });
    setNotice(
      "Imagem carregada. A qualidade será limitada pelo perfil instalado.",
    );
  }
  function clearProject() {
    if (!canChangeReference(activity)) {
      setNotice(generationReasonText("busy"));
      return;
    }
    imageAnalysisVersionRef.current += 1;
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    objectUrlRef.current = undefined;
    setFile(null);
    setPreviewUrl(undefined);
    setJob(null);
    setOperationParent(null);
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
      historyReloadRef.current();
    } catch (error) {
      setLastError(
        `Não foi possível atualizar o favorito: ${errorText(error)}`,
      );
    }
  }
  async function deleteJob(jobId: string) {
    if (busy && job?.id === jobId) {
      setNotice(generationReasonText("busy"));
      return;
    }
    if (
      !window.confirm(
        "Excluir este job e seus arquivos locais? Esta ação não pode ser desfeita.",
      )
    )
      return;
    try {
      await localApi.deleteJob(jobId);
      setHistory((items) => items.filter((item) => item.id !== jobId));
      setHistoryTotal((count) => Math.max(0, count - 1));
      setFavourites((items) => {
        const copied = new Set(items);
        copied.delete(jobId);
        return copied;
      });
      if (job?.id === jobId) clearProject();
      historyReloadRef.current();
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
      if (generatedModelUrl)
        setOperationParent({ job, url: generatedModelUrl });
      setJob(next);
      mergeHistory(next);
      historyReloadRef.current();
      setNotice(`${kind} enviado para a fila local como operação derivada.`);
    } catch (error) {
      setLastError(`Não foi possível iniciar ${kind}: ${errorText(error)}`);
    }
  }
  async function reopenJob(jobId: string) {
    if (busy) {
      setNotice(generationReasonText("busy"));
      return;
    }
    try {
      const next = await localApi.job(jobId);
      setJob(next);
      setOperationParent(null);
      mergeHistory(next);
      setPage("home");
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
    const readiness = getGenerationReadiness({
      hasFile: Boolean(file),
      activity,
      connection,
      capabilities,
      selectedQuality,
      faithcMode,
      demoMode: health?.demoMode === true,
    });
    if (readiness.reason === "choose-image") {
      fileInputRef.current?.click();
      return;
    }
    if (!readiness.canGenerate) {
      setNotice(generationReasonText(readiness.reason));
      return;
    }
    const sourceFile = file;
    if (!sourceFile) {
      fileInputRef.current?.click();
      return;
    }
    setLastError("");
    setModelError("");
    setIsUploading(true);
    try {
      const upload = await localApi.upload(sourceFile);
      const numericSeed = Number.parseInt(seed, 10);
      const optionalInt = (value: string) =>
        value.trim() && Number.isFinite(Number(value))
          ? Number.parseInt(value, 10)
          : undefined;
      const optionalFloat = (value: string) =>
        value.trim() && Number.isFinite(Number(value))
          ? Number(value)
          : undefined;
      // The backend selects a resident TRELLIS worker when explicitly enabled
      // by the local engine configuration, retaining model weights across jobs.
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
          faithc: faithcMode,
          faithc_resolution: faithcResolution,
          seed: Number.isFinite(numericSeed) ? numericSeed : undefined,
        },
      });
      setJob(next);
      mergeHistory(next);
      historyReloadRef.current();
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
    if (item === "model") {
      setActiveRail("model");
      return;
    }
    if (item === "image") {
      setActiveRail("model");
      if (canChangeReference(activity)) fileInputRef.current?.click();
      else setNotice(generationReasonText("busy"));
      return;
    }
    if (!displayedModelUrl) {
      setNotice("Gere ou reabra um resultado antes de usar estas ferramentas.");
      return;
    }
    setActiveRail(item);
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
    if (!displayedModelUrl) {
      setNotice("Gere ou reabra um modelo antes de centralizar o viewport.");
      return;
    }
    viewerRef.current?.center();
  }
  function captureViewer() {
    if (!displayedModelUrl) {
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
        <nav className="top-nav" aria-label="Navegação principal">
          <button
            className={page === "home" ? "active" : ""}
            type="button"
            onClick={() => setPage("home")}
          >
            Criar
          </button>
          <button
            className={page === "assets" ? "active" : ""}
            type="button"
            onClick={() => {
              setPage("assets");
              void loadHistory();
            }}
          >
            Biblioteca
          </button>
          <button
            className={page === "docs" ? "active" : ""}
            type="button"
            onClick={() => setPage("docs")}
          >
            Ajuda
          </button>
        </nav>
        <div className="header-side">
          <button
            className={`connection-pill ${connection === "checking" ? "checking" : connection === "offline" ? "offline" : runtimeReadiness.canGenerate ? "ready" : "pending"}`}
            type="button"
            onClick={() => void refreshConnection()}
            aria-label={`${engineLabel}. Atualizar estado`}
          >
            {connection === "checking" ? (
              <LoaderCircle className="spin" size={14} />
            ) : connection === "offline" ? (
              <CloudOff size={14} />
            ) : runtimeReadiness.canGenerate ? (
              <CheckCircle2 size={14} />
            ) : (
              <CircleHelp size={14} />
            )}
            <span>{engineLabel}</span>
          </button>
          <button
            className="circle-control"
            type="button"
            title="Atualizar conexão e biblioteca"
            aria-label="Atualizar conexão e biblioteca"
            onClick={() => {
              void refreshConnection();
              void loadHistory();
            }}
          >
            <RefreshCw size={15} />
          </button>
        </div>
      </header>
      <nav className="mobile-nav" aria-label="Navegação principal móvel">
        <button
          className={page === "home" ? "active" : ""}
          type="button"
          aria-current={page === "home" ? "page" : undefined}
          onClick={() => setPage("home")}
        >
          <WandSparkles size={15} /> <span>Criar</span>
        </button>
        <button
          className={page === "assets" ? "active" : ""}
          type="button"
          aria-current={page === "assets" ? "page" : undefined}
          onClick={() => {
            setPage("assets");
            void loadHistory();
          }}
        >
          <History size={15} /> <span>Biblioteca</span>
        </button>
        <button
          className={page === "docs" ? "active" : ""}
          type="button"
          aria-label="Documentação e ajuda"
          aria-current={page === "docs" ? "page" : undefined}
          onClick={() => setPage("docs")}
        >
          <BookOpen size={15} /> <span>Ajuda</span>
        </button>
      </nav>
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
          faithcMode={faithcMode}
          setFaithcMode={setFaithcMode}
          faithcResolution={faithcResolution}
          setFaithcResolution={setFaithcResolution}
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
          modelError={modelError}
          setModelError={setModelError}
          viewerRef={viewerRef}
          viewportRef={viewportRef}
          view={view}
          setView={setView}
          centerViewer={centerViewer}
          captureViewer={captureViewer}
          fullscreenViewer={fullscreenViewer}
          progress={progress}
          elapsed={elapsed}
          verified={isVerified}
          streamState={streamState}
          cancel={handleCancel}
          openDocs={() => setPage("docs")}
          targetTriangles={targetTriangles}
          setTargetTriangles={setTargetTriangles}
          runOperation={runOperation}
          connection={connection}
          activity={activity}
          displayModelUrl={displayedModelUrl}
          displayJob={displayedJob}
          downloadJobId={downloadJobId}
          demoMode={health?.demoMode === true}
          retryConnection={() => void refreshConnection()}
          originalDownloadJobId={operationParent?.job.id}
        />
      )}
      {page === "assets" && (
        <AssetsPage
          history={history}
          allHistoryCount={historyTotal}
          loading={historyLoading}
          loadingMore={historyLoadingMore}
          hasMore={historyNextOffset !== null}
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
          loadMore={() => void loadHistory(true)}
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
  faithcMode: "off" | "geometry";
  setFaithcMode: (mode: "off" | "geometry") => void;
  faithcResolution: 128 | 256 | 512;
  setFaithcResolution: (resolution: 128 | 256 | 512) => void;
  seed: string;
  setSeed: (value: string) => void;
  prompt: string;
  setPrompt: (value: string) => void;
  advanced: AdvancedSettings;
  setAdvanced: React.Dispatch<React.SetStateAction<AdvancedSettings>>;
  activeProfile?: EngineProfile;
  capabilities: EngineCapabilities | null;
  lastError: string;
  clearError: () => void;
  busy: boolean;
  uploading: boolean;
  generate: () => void;
  job: GenerationJob | null;
  modelError: string;
  setModelError: (value: string) => void;
  viewerRef: React.RefObject<ViewerHandle | null>;
  viewportRef: React.RefObject<HTMLDivElement | null>;
  view: ViewMode;
  setView: (view: ViewMode) => void;
  centerViewer: () => void;
  captureViewer: () => void;
  fullscreenViewer: () => void;
  progress: number;
  elapsed?: number;
  verified: boolean;
  streamState: JobStreamState;
  cancel: () => void;
  openDocs: () => void;
  targetTriangles: string;
  setTargetTriangles: (value: string) => void;
  runOperation: (kind: OperationKind) => void;
  connection: ConnectionState;
  activity: GenerationActivity;
  displayModelUrl?: string;
  displayJob: GenerationJob | null | undefined;
  downloadJobId?: string;
  demoMode: boolean;
  retryConnection: () => void;
  originalDownloadJobId?: string;
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
    faithcMode,
    setFaithcMode,
    faithcResolution,
    setFaithcResolution,
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
    modelError,
    setModelError,
    viewerRef,
    viewportRef,
    view,
    setView,
    centerViewer,
    captureViewer,
    fullscreenViewer,
    progress,
    elapsed,
    verified,
    streamState,
    cancel,
    openDocs,
    targetTriangles,
    setTargetTriangles,
    runOperation,
    connection,
    activity,
    displayModelUrl,
    displayJob,
    downloadJobId,
    demoMode,
    retryConnection,
    originalDownloadJobId,
  } = props;
  const faithc = capabilities?.faithc;
  const f32Available = activeProfile?.id === "16gb";
  const faithcStatus = !faithc?.configured
    ? "Configure o worker FaithC no backend para habilitar o refinamento."
    : faithc.probeState === "ready" || faithc.available
      ? "Worker configurado e GPU validada."
      : faithc.probeState === "failed"
        ? "Última validação CUDA falhou. O job tentará validar novamente ao entrar na fila."
        : "Worker configurado. CUDA será validada quando o job entrar na fila.";
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
    busy
      ? "Aguarde a operação atual terminar antes de iniciar outra."
      : !job || job.status !== "completed"
      ? "A operação fica disponível quando o resultado atual terminar."
      : !operationSupported
        ? requestedCapability?.detail ||
          capabilities?.operationsDetail ||
          "Esta operação ainda não está disponível nesta instalação."
        : "";
  const operationMode = activeRail !== "model" && activeRail !== "image";
  const actionReadiness = getGenerationReadiness({
    hasFile: Boolean(file),
    activity,
    connection,
    capabilities,
    selectedQuality,
    faithcMode,
    demoMode,
  });
  const currentStep = displayModelUrl
    ? "result"
    : busy || job?.status === "failed" || Boolean(file)
      ? "generate"
      : "image";
  const imageStep = file || previewUrl ? "complete" : "pending";
  const generateStep = displayModelUrl
    ? "complete"
    : job?.status === "failed"
      ? "error"
      : busy || file
        ? "current"
        : "pending";
  const resultStep = displayModelUrl ? "complete" : "pending";
  const latestActivity = [
    ...(displayJob?.events || []),
    ...(displayJob?.logs || []).map((log) => ({
      message: log.message,
      tool: log.source,
      at: log.at,
    })),
  ]
    .slice(-5)
    .reverse();
  const telemetryJob = job || displayJob;
  const viewerLoadFailure = Boolean(modelError && !lastError && job?.status !== "failed");
  return (
    <div className="forge-workspace">
      <aside className="studio-panel" aria-label="Painel de geração">
        {operationMode && (
          <button
            className="back-to-create"
            type="button"
            onClick={() => setRail("model")}
          >
            <ChevronRight size={15} /> Voltar para criação
          </button>
        )}
        <div className="panel-title">
          <span className="panel-breadcrumb">
            <WandSparkles size={14} /> {operationMode ? "Ferramenta do resultado" : "Imagem para 3D"}
          </span>
          <h1>{operationMode ? railTitle : "Imagem para 3D"}</h1>
          <p>
            {operationMode
              ? "A operação cria uma nova saída e preserva o GLB original."
              : "Escolha uma imagem. Forge3D gera um modelo 3D com materiais PBR."}
          </p>
        </div>
        {!operationMode && (
          <ol className="generation-steps" aria-label="Etapas de criação">
            <li className={imageStep} aria-current={currentStep === "image" ? "step" : undefined}>
              <span>1</span><strong>Imagem</strong>
            </li>
            <li className={generateStep} aria-current={currentStep === "generate" ? "step" : undefined}>
              <span>2</span><strong>Gerar</strong>
            </li>
            <li className={resultStep} aria-current={currentStep === "result" ? "step" : undefined}>
              <span>3</span><strong>Resultado</strong>
            </li>
          </ol>
        )}
        <input
          ref={fileInputRef}
          className="visually-hidden"
          type="file"
          accept="image/png,image/jpeg,image/webp,image/bmp"
          disabled={!canChangeReference(activity)}
          onChange={(event) => chooseFile(event.target.files?.[0])}
        />
        {!operationMode && (
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
                      disabled={!canChangeReference(activity)}
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
                        ? actionReadiness.canGenerate
                          ? "Pronta para gerar"
                          : "Imagem selecionada"
                        : "Referência restaurada do histórico"}
                    </span>
                  </div>
                  <button
                    className="change-reference"
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    disabled={!canChangeReference(activity)}
                  >
                    Trocar imagem
                  </button>
                </>
              ) : (
                <button
                  className={`upload-drop ${isDragging ? "dragging" : ""}`}
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={!canChangeReference(activity)}
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
        {!operationMode && (
          <details className="optional-settings">
            <summary>
              <span className="optional-summary-title">
                <Settings2 size={15} /> Ajustes opcionais
              </span>
              <span className="optional-summary-detail">
                {selectedQuality?.label || "Qualidade indisponível"} · UltraShape {ultrashapeMode === "auto" ? "automático" : "desativado"} · FaithC {faithcMode === "geometry" ? `${faithcResolution} px` : "desativado"}
              </span>
              <ChevronDown size={15} />
            </summary>
            <fieldset className="optional-fields" disabled={busy}>
          <section className="setting-section">
            <div className="setting-label">
              <span>Qualidade TRELLIS aprovada</span>
              <CircleHelp size={13} />
            </div>
            <div className="quality-list">
              {trellisQualities.length === 0 && (
                <p className="quality-empty">Qualidades aprovadas ainda não estão disponíveis.</p>
              )}
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
          <section className="faithc-card" aria-labelledby="faithc-heading">
            <div className="faithc-heading">
              <div>
                <strong id="faithc-heading">FaithC</strong>
                <small>Faithful Contouring &amp; Geometry Refinement</small>
              </div>
              <span className={faithc?.configured ? "faithc-badge ready" : "faithc-badge"}>
                {faithc?.configured ? "Configurado" : "Indisponível"}
              </span>
            </div>
            <p>
              Refinamento opcional de contorno em artefato separado.
            </p>
            <div className="faithc-actions" role="group" aria-label="Modo FaithC">
              <button
                type="button"
                aria-pressed={faithcMode === "off"}
                className={faithcMode === "off" ? "selected" : ""}
                onClick={() => setFaithcMode("off")}
                disabled={busy}
              >
                Desativado
              </button>
              <button
                type="button"
                aria-pressed={faithcMode === "geometry"}
                className={faithcMode === "geometry" ? "selected" : ""}
                onClick={() => setFaithcMode("geometry")}
                disabled={busy || !faithc?.configured}
              >
                Geometria
              </button>
            </div>
            {faithcMode === "geometry" && (
              <label className="faithc-resolution">
                Resolução
                <select
                  value={faithcResolution}
                  disabled={busy || !faithc?.configured}
                  onChange={(event) => setFaithcResolution(Number(event.target.value) as 128 | 256 | 512)}
                >
                  {(faithc?.resolutions || [128, 256, 512]).map((resolution) => (
                    <option value={resolution} key={resolution}>{resolution} px</option>
                  ))}
                </select>
              </label>
            )}
            <p className="faithc-status" role="status">{faithcStatus}</p>
            {faithcMode === "geometry" && (
              <p className="faithc-output-note">Saída FaithC contém geometria sem UV/PBR. GLB principal preservado.</p>
            )}
            {!faithc?.configured && (
              <button className="faithc-help" type="button" onClick={openDocs}>Ver instalação</button>
            )}
          </section>
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
        <section className="advanced-group">
          <h2><SlidersHorizontal size={14} /> Compute e guidance</h2>
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
              f32Available
                  ? "Compute F32 do trellis-cli"
                : "Liberado somente pelo perfil de 16 GB"
              }
            >
              <input
                type="checkbox"
                checked={advanced.f32}
                disabled={!f32Available}
                onChange={(event) =>
                  setAdvanced((current) => ({
                    ...current,
                    f32: event.target.checked,
                  }))
                }
              />{" "}
              F32 {!f32Available ? "— requer perfil de 16 GB" : ""}
            </label>
          </div>
        </section>
        <section className="advanced-group">
          <h2><Settings2 size={14} /> Opções avançadas</h2>
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
        </section>
        {activeProfile && (
          <div className="profile-note">
            <span><Aperture size={15} /></span>
            <div>
              <strong>{activeProfile.label} · {activeProfile.vramLabel}</strong>
              <p>Perfil informado pela instalação local.</p>
            </div>
          </div>
        )}
            </fieldset>
          </details>
        )}
        {!operationMode && file && !busy && !actionReadiness.canGenerate && (
          <div className="availability-callout" role="status">
            <CloudOff size={17} />
            <div>
              <strong>Geração indisponível</strong>
              <p>{generationReasonText(actionReadiness.reason)}</p>
              <div>
                <button type="button" onClick={retryConnection}>
                  Tentar novamente
                </button>
                <button type="button" className="quiet" onClick={openDocs}>
                  Ajuda
                </button>
              </div>
            </div>
          </div>
        )}
        {operationMode && requestedOperation && displayModelUrl && (
          <section className="operation-panel" aria-labelledby="operation-title">
            <div>
              <strong id="operation-title">
                {requestedOperation === "split"
                  ? "Separar objetos"
                  : requestedOperation === "remesh"
                    ? "Reconstruir topologia"
                    : requestedOperation === "retexture"
                      ? "Atualizar textura PBR"
                      : "Transformar malha"}
              </strong>
              <small>
                {operationSupported
                  ? "Cria uma saída derivada e mantém o resultado original na biblioteca."
                  : operationReason}
              </small>
            </div>
            {requestedOperation === "retexture" && displayJob?.validation && (
              <details className="texture-audit">
                <summary>Auditoria PBR do resultado</summary>
                <div>
                  <span className={displayJob.validation.hasTexture ? "ok" : ""}>Base color</span>
                  <span className={displayJob.validation.hasMetallicRoughnessMap ? "ok" : ""}>Metal/Rough</span>
                  <span className={displayJob.validation.hasNormalMap ? "ok" : ""}>Normal</span>
                  <span className={displayJob.validation.hasOcclusionMap ? "ok" : ""}>Occlusion</span>
                </div>
                <p>{displayJob.validation.message || "Auditoria dos mapas incluídos no GLB."}</p>
              </details>
            )}
            <fieldset className="operation-fields" disabled={busy}>
              {requestedOperation === "remesh" && (
                <label>
                  Densidade ou teto de triângulos
                  <input
                    value={targetTriangles}
                    onChange={(event) =>
                      setTargetTriangles(event.target.value.replace(/[^0-9]/g, "").slice(0, 7))
                    }
                    inputMode="numeric"
                    min="100"
                    max="2000000"
                  />
                  <small>Remesh reconstrói a topologia. Simplificar apenas reduz ao teto definido.</small>
                </label>
              )}
              {requestedOperation === "transform" && (
                <div className="transform-grid">
                  <VectorFields
                    label="Posição"
                    values={advanced.translation}
                    update={(translation) => setAdvanced((current) => ({ ...current, translation }))}
                  />
                  <VectorFields
                    label="Rotação °"
                    values={advanced.rotation}
                    update={(rotation) => setAdvanced((current) => ({ ...current, rotation }))}
                  />
                  <VectorFields
                    label="Escala"
                    values={advanced.scale}
                    update={(scale) => setAdvanced((current) => ({ ...current, scale }))}
                  />
                </div>
              )}
              <button
                type="button"
                disabled={!operationSupported || !job || job.status !== "completed" || busy}
                title={operationReason || "Criar saída derivada"}
                onClick={() => runOperation(requestedOperation)}
              >
                {operationSupported
                  ? requestedOperation === "remesh" ? "Aplicar remesh" : "Criar saída derivada"
                  : "Indisponível nesta instalação"}
              </button>
              {requestedOperation === "remesh" && (
                <button
                  type="button"
                  className="operation-secondary"
                  disabled={!simplifySupported || !job || job.status !== "completed" || busy}
                  title={simplifyCapability?.detail || "Reduzir o resultado ao teto definido"}
                  onClick={() => runOperation("simplify")}
                >
                  {simplifySupported ? "Simplificar ao teto" : "Simplificação indisponível"}
                </button>
              )}
            </fieldset>
          </section>
        )}
        {displayModelUrl && downloadJobId && (
          <section className="result-ready">
            <div>
              <CheckCircle2 size={18} />
              <div>
                <strong>{busy && operationMode ? "Resultado original preservado" : "Resultado pronto"}</strong>
                <span>Arquivo GLB principal</span>
              </div>
            </div>
            <a href={localApi.downloadUrl(downloadJobId)} download aria-label="Baixar GLB principal">
              <Download size={17} /> Baixar GLB
            </a>
            {operationMode && originalDownloadJobId && job?.status === "completed" && (
              <a
                className="original-download"
                href={localApi.downloadUrl(originalDownloadJobId)}
                download
                aria-label="Baixar GLB original"
              >
                Baixar GLB original
              </a>
            )}
          </section>
        )}
        {!operationMode && displayModelUrl && (
          <section className="operation-picker" aria-labelledby="operation-picker-title">
            <h2 id="operation-picker-title">Ferramentas do resultado</h2>
            <p>Crie uma saída derivada sem substituir o GLB original.</p>
            <div>
              <button type="button" onClick={() => setRail("split")} disabled={busy}><Split size={16} />Separar objetos</button>
              <button type="button" onClick={() => setRail("remesh")} disabled={busy}><ScanLine size={16} />Remesh e simplificar</button>
              <button type="button" onClick={() => setRail("texture")} disabled={busy}><Paintbrush size={16} />Textura PBR</button>
              <button type="button" onClick={() => setRail("edit")} disabled={busy}><Settings2 size={16} />Transformar</button>
            </div>
          </section>
        )}
        {!operationMode && (
          <button
            className="generate-cta"
            type="button"
            onClick={generate}
            disabled={busy || (Boolean(file) && !actionReadiness.canGenerate)}
            aria-busy={busy}
          >
            {busy ? <LoaderCircle className="spin" size={17} /> : file ? <WandSparkles size={17} /> : <ImagePlus size={17} />}
            <span>
              {uploading
                ? "Preparando imagem"
                : busy
                  ? "Gerando modelo"
                  : file
                    ? "Gerar modelo 3D"
                    : "Escolher imagem"}
            </span>
          </button>
        )}
        {(busy || job) && (
          <section className="job-status" aria-live="polite" aria-atomic="true">
            <div className="job-status-heading">
              <span className={busy ? "job-status-icon working" : "job-status-icon"}>
                {busy ? <LoaderCircle className="spin" size={17} /> : job?.status === "completed" ? <CheckCircle2 size={17} /> : <Sparkles size={17} />}
              </span>
              <div>
                <strong>
                  {uploading
                    ? "Preparando imagem"
                    : job?.status === "queued"
                      ? "Na fila"
                      : job?.status === "running"
                        ? "Criando modelo"
                        : job?.status === "completed"
                          ? verified ? "Resultado validado" : "Resultado concluído"
                          : job?.status === "failed"
                            ? "Geração interrompida"
                            : job?.status === "cancelled"
                              ? "Geração cancelada"
                              : "Pronto para criar"}
                </strong>
                <span>
                  {uploading
                    ? "Enviando imagem"
                    : job?.status === "queued"
                      ? "Aguardando início"
                      : job?.status === "running"
                        ? "Preparando geometria e materiais"
                        : job?.status === "completed"
                          ? "O resultado está disponível para baixar."
                          : job?.status === "failed"
                            ? "Tente novamente quando a geração estiver disponível."
                            : job?.status === "cancelled"
                              ? "Você pode iniciar uma nova geração."
                              : ""}
                </span>
              </div>
              {busy && elapsed !== undefined && <time>{formatTime(elapsed)}</time>}
            </div>
            {busy && (
              <div className="job-progress-row">
                <div className={progress > 0 ? "job-progress" : "job-progress indeterminate"}>
                  <span style={progress > 0 ? { width: `${Math.min(100, progress)}%` } : undefined} />
                </div>
                <span>{progress > 0 ? `${Math.min(100, progress)}%` : "Em andamento"}</span>
                {isRunning(job) && <button type="button" onClick={cancel}>Cancelar</button>}
              </div>
            )}
          </section>
        )}
        {((lastError && !busy) || job?.status === "failed" || modelError) && (
          <section className="failure-card" role="alert">
            <strong>{viewerLoadFailure ? "Não foi possível exibir o modelo." : "Não foi possível concluir."}</strong>
            <span>
              {viewerLoadFailure
                ? "Baixe o GLB principal ou consulte Detalhes para a falha de visualização."
                : "Confira disponibilidade e tente novamente."}
            </span>
            {!viewerLoadFailure && file && actionReadiness.canGenerate && (
              <button type="button" onClick={generate}>Tentar novamente</button>
            )}
            <details>
              <summary>Detalhes</summary>
              <p>{viewerLoadFailure ? modelError : lastError || job?.error || modelError || "Geração interrompida."}</p>
              <button type="button" onClick={clearError}>Fechar aviso</button>
            </details>
          </section>
        )}
      </aside>
      <section className="viewport-column" aria-label="Resultado 3D">
        <div className="viewport-breadcrumb">
          <strong>Resultado</strong>
          <span className="viewport-project">
            {displayJob?.metadata?.title || file?.name || displayJob?.inputFilename || "Aguardando imagem"}
          </span>
        </div>
        <div
          className={displayModelUrl ? "viewport-canvas has-result" : "viewport-canvas awaiting-result"}
          ref={viewportRef}
        >
          {displayModelUrl ? (
            <>
              <Suspense
                fallback={
                  <div className="viewport-loader">
                    <LoaderCircle className="spin" size={18} />
                    Abrindo resultado
                  </div>
                }
              >
                <Viewer
                  ref={viewerRef}
                  modelUrl={displayModelUrl}
                  cacheKey={displayJob?.id}
                  view={view}
                  onLoaded={() => setModelError("")}
                  onError={setModelError}
                />
              </Suspense>
              {modelError && (
                <div className="viewport-error" role="alert">
                  <CloudOff size={16} />
                  <div>
                    <strong>Não foi possível abrir o resultado</strong>
                    <span>Abra os detalhes para consultar a falha.</span>
                  </div>
                  <button type="button" onClick={() => setModelError("")} aria-label="Fechar aviso">
                    <X size={14} />
                  </button>
                </div>
              )}
              {displayJob?.validation && (
                <div className="scene-data" aria-label="Medidas verificadas do modelo">
                  {displayJob.validation.triangles !== undefined && (
                    <>
                      <span>Triângulos</span>
                      <strong>{formatCount(displayJob.validation.triangles)}</strong>
                    </>
                  )}
                  {displayJob.validation.vertices !== undefined && (
                    <>
                      <span>Vértices</span>
                      <strong>{formatCount(displayJob.validation.vertices)}</strong>
                    </>
                  )}
                </div>
              )}
              <div className="axis-indicator" aria-hidden="true">
                <i className="x">X</i>
                <i className="y">Y</i>
                <i className="z">Z</i>
              </div>
              <div className="viewport-actions">
                <button type="button" title="Centralizar modelo" aria-label="Centralizar modelo" onClick={centerViewer}>
                  <Focus size={17} />
                </button>
                <button type="button" title="Baixar captura PNG" aria-label="Capturar imagem" onClick={captureViewer}>
                  <Camera size={16} />
                </button>
                <button type="button" title="Abrir em tela cheia" aria-label="Tela cheia" onClick={() => void fullscreenViewer()}>
                  <Maximize2 size={16} />
                </button>
              </div>
              <div className="view-dock" aria-label="Ângulo de visualização">
                <button type="button" className={view === "perspective" ? "selected" : ""} onClick={() => setView("perspective")}>3D</button>
                <button type="button" className={view === "front" ? "selected" : ""} onClick={() => setView("front")}>Frente</button>
                <button type="button" className={view === "side" ? "selected" : ""} onClick={() => setView("side")}>Lado</button>
                <i />
                <span>Arraste para orbitar</span>
              </div>
            </>
          ) : (
            <div className="empty-result">
              {previewUrl ? (
                <img className="empty-reference" src={previewUrl} alt="Imagem escolhida para gerar o modelo" />
              ) : (
                <span className="empty-result-icon"><Box size={25} /></span>
              )}
              <div>
                <strong>
                  {job?.status === "failed"
                    ? "Resultado indisponível"
                    : busy
                      ? "Modelo em criação"
                      : file
                        ? actionReadiness.canGenerate
                          ? "Pronto para gerar"
                          : "Imagem selecionada"
                        : "Escolha uma imagem"}
                </strong>
                <p>
                  {job?.status === "failed"
                    ? "Confira os detalhes e tente novamente."
                    : busy
                      ? "O andamento e o cancelamento aparecem no painel."
                      : file
                        ? "Quando estiver pronto, o resultado aparecerá aqui."
                        : "Seu modelo 3D aparecerá aqui."}
                </p>
              </div>
            </div>
          )}
        </div>
        {(Boolean(telemetryJob) || latestActivity.length > 0 || Boolean(lastError) || Boolean(modelError)) && (
          <details className="result-details">
            <summary>
              <span>Detalhes do resultado</span>
              <small>Auditoria · execução · arquivos · registros</small>
              <ChevronDown size={15} />
            </summary>
            <div className="result-details-grid">
              {telemetryJob && (
                <section className="job-telemetry" aria-labelledby="job-telemetry-title">
                  <h2 id="job-telemetry-title">Estado da execução</h2>
                  <dl>
                    <div><dt>Status</dt><dd>{statusName(telemetryJob.status)}</dd></div>
                    {telemetryJob.queuePosition !== undefined && (
                      <div><dt>Posição na fila</dt><dd>#{telemetryJob.queuePosition}</dd></div>
                    )}
                    <div>
                      <dt>Tempo decorrido</dt>
                      <dd>
                        {telemetryJob.status === "completed"
                          ? formatTime(telemetryJob.elapsedSeconds)
                          : busy && elapsed !== undefined
                            ? formatTime(elapsed)
                            : "—"}
                      </dd>
                    </div>
                    <div>
                      <dt>Estimativa</dt>
                      <dd>
                        {busy
                          ? telemetryJob.etaSeconds !== undefined
                            ? `~${formatTime(telemetryJob.etaSeconds)}`
                            : "Calculando…"
                          : "—"}
                      </dd>
                    </div>
                    <div>
                      <dt>Atualizações</dt>
                      <dd>
                        {streamState === "live"
                          ? "Tempo real · SSE"
                          : streamState === "connecting"
                            ? "Conectando SSE"
                            : streamState === "polling"
                              ? "Consulta periódica · polling"
                              : "Sem atualização ativa"}
                      </dd>
                    </div>
                  </dl>
                </section>
              )}
              {displayJob?.validation && (
                <section className="validation-card">
                  <div>
                    <span>Auditoria de saída</span>
                    {displayJob.validation.valid ? (
                      <em><CheckCircle2 size={13} /> Validado</em>
                    ) : (
                      <em className="warn">Verifique o resultado</em>
                    )}
                  </div>
                  <p>{displayJob.validation.message || "Resultado auditado localmente."}</p>
                  <ul>
                    <li className={displayJob.validation.hasMesh ? "ok" : ""}>Malha</li>
                    <li className={displayJob.validation.hasUv ? "ok" : ""}>UV</li>
                    <li className={displayJob.validation.hasTexture ? "ok" : ""}>Base color</li>
                    <li className={displayJob.validation.hasPbrMaterial ? "ok" : ""}>Metal/Rough</li>
                    <li className={displayJob.validation.hasNormalMap ? "ok" : ""}>Normal</li>
                    <li className={displayJob.validation.hasOcclusionMap ? "ok" : ""}>Occlusion</li>
                  </ul>
                  <PropertyRow label="Formato" value={(displayJob.output?.format || "glb").toUpperCase()} />
                  <PropertyRow label="Textura" value={displayJob.validation.hasTexture ? "Incluída" : "Não encontrada"} />
                </section>
              )}
              {displayJob?.artifacts && displayJob.artifacts.length > 0 && (
                <section className="result-artifacts">
                  <h2>Arquivos adicionais</h2>
                  {displayJob.artifacts.map((artifact, index) => {
                    const artifactName = [artifact.id, artifact.name, artifact.label, artifact.type].filter(Boolean).join(" ");
                    const isFaithcArtifact = /faithc/i.test(artifactName);
                    const label = isFaithcArtifact
                      ? "FaithC · Geometria sem UV/PBR"
                      : artifact.label || artifact.name || artifact.type || "Arquivo gerado";
                    const url = localApi.resolveAssetUrl(artifact.url);
                    return url ? (
                      <a
                        key={artifact.id || artifact.name || index}
                        href={url}
                        download={artifact.name || undefined}
                        className="artifact-row"
                        aria-label={"Baixar " + label}
                      >
                        <FileBox size={14} />
                        <span>{label}</span>
                        <Download size={14} />
                      </a>
                    ) : null;
                  })}
                </section>
              )}
              {latestActivity.length > 0 && (
                <section className="activity-feed">
                  <span>Registros recentes</span>
                  {latestActivity.map((item, index) => (
                    <div key={[item.at || index, item.message || ""].join("-")}>
                      <strong>{prettyTool(item.tool)}</strong>
                      <p>{item.message}</p>
                    </div>
                  ))}
                </section>
              )}
              {(lastError || job?.error || modelError || displayJob?.fallbackReason) && (
                <section className="diagnostic-detail">
                  <h2>Diagnóstico</h2>
                  <p>{displayJob?.fallbackReason || lastError || job?.error || modelError}</p>
                  <small>
                    Atualização: {streamState === "live" ? "tempo real" : streamState === "connecting" ? "conectando" : "consulta periódica"}
                  </small>
                </section>
              )}
            </div>
          </details>
        )}
      </section>
    </div>
  );
}

type AssetsProps = {
  history: GenerationJob[];
  allHistoryCount: number;
  loading: boolean;
  loadingMore: boolean;
  hasMore: boolean;
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
  loadMore: () => void;
};
function AssetsPage({
  history,
  allHistoryCount,
  loading,
  loadingMore,
  hasMore,
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
  loadMore,
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
            Consulte gerações anteriores, filtre por status, marque favoritas e reabra arquivos disponíveis nesta engine.
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
            placeholder="Buscar por arquivo, prompt ou ID"
            aria-label="Buscar no histórico"
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
          aria-pressed={favouritesOnly}
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
      <div className="history-summary" role="status" aria-live="polite">
        Exibindo {history.length} de {allHistoryCount} jobs locais.
      </div>
      <div className="history-list" aria-busy={loading || loadingMore}>
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
                  aria-label={favorite ? "Remover dos favoritos" : "Adicionar aos favoritos"}
                  aria-pressed={favorite}
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
                  <a href={localApi.downloadUrl(item.id)} download aria-label="Baixar GLB principal">
                    <Download size={15} /> Baixar GLB
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
        {hasMore && (
          <button
            className="history-load-more"
            type="button"
            onClick={loadMore}
            disabled={loading || loadingMore}
            aria-busy={loadingMore}
          >
            {loadingMore ? <LoaderCircle className="spin" size={16} /> : null}
            {loadingMore ? "Carregando mais" : "Carregar mais"}
          </button>
        )}
      </div>
    </section>
  );
}

function DocsPage({
  activeProfile,
  capabilities,
  onHome,
}: {
  activeProfile?: EngineProfile;
  capabilities: EngineCapabilities | null;
  onHome: () => void;
}) {
  const faithcRuntime = !capabilities
    ? "Consultando API"
    : !capabilities.faithc.configured
      ? "Instalação necessária"
      : capabilities.faithc.probeState === "ready" || capabilities.faithc.available
        ? "Configurado · CUDA validada"
        : capabilities.faithc.probeState === "failed"
          ? "Configurado · nova validação na fila"
          : "Configurado · validação no job";
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
            {activeProfile ? (
              <>O perfil ativo é <strong>{activeProfile.label}</strong>. Só as qualidades publicadas pela instalação podem ser usadas.</>
            ) : (
              "Perfil local ainda não identificado."
            )}
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
        <article>
          <span>05</span>
          <h2>Instale FaithC</h2>
          <p>
            FaithC usa worker CUDA separado e adiciona geometria sem UV/PBR. Configure o worker conforme <code>docs/FAITHC.md</code>; o GLB principal continua disponível.
          </p>
        </article>
      </div>
      <section className="docs-runtime">
        <h2>Runtime detectado</h2>
        <PropertyRow
          label="Perfil"
          value={activeProfile ? `${activeProfile.label} · ${activeProfile.vramLabel}` : "Não identificado"}
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
          label="FaithC"
          value={faithcRuntime}
        />
        <p className="docs-runtime-note">
          Ativo, FaithC cria geometria num artefato separado sem UV/PBR. Consulte <code>docs/FAITHC.md</code> para instalação.
        </p>
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
