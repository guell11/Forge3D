import type { ConnectionState, EngineCapabilities, TrellisQuality } from "./types";

export type GenerationBlockReason =
  | "choose-image"
  | "busy"
  | "connecting"
  | "offline"
  | "capabilities"
  | "quality"
  | "faithc"
  | "demo"
  | null;

export type GenerationReadiness = {
  canGenerate: boolean;
  reason: GenerationBlockReason;
};

export type GenerationActivity =
  | "uploading"
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled"
  | null;

export function isGenerationBusy(activity: GenerationActivity): boolean {
  return activity === "uploading" || activity === "queued" || activity === "running";
}

export function getGenerationReadiness(input: {
  hasFile: boolean;
  activity: GenerationActivity;
  connection: ConnectionState;
  capabilities: EngineCapabilities | null;
  selectedQuality?: TrellisQuality;
  faithcMode: "off" | "geometry";
  demoMode?: boolean;
}): GenerationReadiness {
  if (isGenerationBusy(input.activity))
    return { canGenerate: false, reason: "busy" };
  if (!input.hasFile) return { canGenerate: false, reason: "choose-image" };
  if (input.connection === "checking")
    return { canGenerate: false, reason: "connecting" };
  if (input.connection === "offline")
    return { canGenerate: false, reason: "offline" };
  if (input.demoMode)
    return { canGenerate: false, reason: "demo" };
  if (!input.capabilities) return { canGenerate: false, reason: "capabilities" };
  if (
    input.capabilities.trellisQualities.length === 0 ||
    !input.selectedQuality ||
    input.selectedQuality.available === false ||
    !input.capabilities.trellisQualities.some(
      (quality) =>
        quality.id === input.selectedQuality?.id && quality.available !== false,
    )
  ) {
    return { canGenerate: false, reason: "quality" };
  }
  if (input.faithcMode === "geometry" && !input.capabilities.faithc.configured)
    return { canGenerate: false, reason: "faithc" };
  return { canGenerate: true, reason: null };
}

export function canChangeReference(activity: GenerationActivity): boolean {
  return !isGenerationBusy(activity);
}
