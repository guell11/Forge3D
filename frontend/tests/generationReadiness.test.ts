import assert from "node:assert/strict";
import test from "node:test";
import { canChangeReference, getGenerationReadiness } from "../src/generationReadiness.ts";
import type { EngineCapabilities, TrellisQuality } from "../src/types.ts";

const quality: TrellisQuality = {
  id: "balanced",
  label: "Balanced",
  available: true,
};

const capabilities: EngineCapabilities = {
  trellisQualities: [quality],
  ultrashapeAvailable: false,
  ultrashapeModes: [],
  faithc: {
    configured: true,
    available: true,
    resolutions: [128, 256],
    recommendedResolution: 256,
    limitations: [],
  },
  operationsAvailable: false,
  operationKinds: [],
  operationCapabilities: {},
};

const check = (overrides: Partial<Parameters<typeof getGenerationReadiness>[0]> = {}) =>
  getGenerationReadiness({
    hasFile: true,
    activity: null,
    connection: "ready",
    capabilities,
    selectedQuality: quality,
    faithcMode: "off",
    ...overrides,
  });

test("generation readiness follows real connection and capability state", () => {
  assert.deepEqual(check({ hasFile: false }), {
    canGenerate: false,
    reason: "choose-image",
  });
  assert.deepEqual(check({ connection: "checking" }), {
    canGenerate: false,
    reason: "connecting",
  });
  assert.deepEqual(check({ connection: "offline" }), {
    canGenerate: false,
    reason: "offline",
  });
  assert.deepEqual(check({ demoMode: true }), {
    canGenerate: false,
    reason: "demo",
  });
  assert.deepEqual(check({ capabilities: null }), {
    canGenerate: false,
    reason: "capabilities",
  });
  assert.deepEqual(check({ capabilities: { ...capabilities, trellisQualities: [] } }), {
    canGenerate: false,
    reason: "quality",
  });
  assert.deepEqual(check({ selectedQuality: { ...quality, available: false } }), {
    canGenerate: false,
    reason: "quality",
  });
  assert.deepEqual(check({ selectedQuality: { id: "stale", label: "Stale", available: true } }), {
    canGenerate: false,
    reason: "quality",
  });
  assert.deepEqual(
    check({
      faithcMode: "geometry",
      capabilities: {
        ...capabilities,
        faithc: { ...capabilities.faithc, configured: false },
      },
    }),
    { canGenerate: false, reason: "faithc" },
  );
  assert.deepEqual(check(), { canGenerate: true, reason: null });
});

test("uploading and queued/running work block generation and reference changes", () => {
  for (const activity of ["uploading", "queued", "running"] as const) {
    assert.deepEqual(check({ activity }), { canGenerate: false, reason: "busy" });
    assert.equal(canChangeReference(activity), false);
  }
  assert.equal(canChangeReference("completed"), true);
  assert.deepEqual(check({ activity: "completed" }), {
    canGenerate: true,
    reason: null,
  });
});
