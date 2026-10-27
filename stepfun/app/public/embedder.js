/**
 * Browser-side embedding.
 *
 * All inference happens on the user device with Transformers.js (ONNX Runtime Web):
 *   - WebGPU + FP16 when available (explicit backend selection)
 *   - automatic fallback to WASM + INT8(q8)
 *
 * Model files are served from the local `public/models` directory when present and fall
 * back to the hf-mirror mirror otherwise. Nothing is sent to a cloud inference API.
 */
import { pipeline, env } from "/vendor/transformers/transformers.min.js";

export const MODEL_ID = "Xenova/bge-small-zh-v1.5";
export const MODEL_DIM = 512;

env.allowLocalModels = true;
env.localModelPath = "/models/";
env.allowRemoteModels = true;
env.remoteHost = "https://hf-mirror.com";
env.backends.onnx.wasm.wasmPaths = "/vendor/transformers/";
env.backends.onnx.wasm.numThreads = 1;

/** Preset configurations used by the UI / benchmark. */
export const CONFIGS = {
  auto: { key: "auto", label: "自动（优先 WebGPU/FP16，否则 WASM/INT8）", device: null, dtype: null },
  fp16_webgpu: { key: "fp16", label: "FP16 + WebGPU", device: "webgpu", dtype: "fp16" },
  int8_wasm: { key: "int8", label: "INT8(q8) + WASM", device: "wasm", dtype: "q8" },
  fp32_wasm: { key: "fp32", label: "fp32 + WASM（量化前基线）", device: "wasm", dtype: "fp32" },
};

/** ONNX file sizes actually downloaded for this model (bytes), measured on disk. */
export const MODEL_FILE_BYTES = {
  fp32: 94_851_877,
  fp16: 47_497_427,
  q8: 24_010_842,
};
export const AUX_FILE_BYTES = 716 + 439_125 + 367 + 125 + 109_540; // config/tokenizer/vocab

export async function detectWebGPU() {
  if (!("gpu" in navigator) || !navigator.gpu) {
    return { available: false, f16: false, reason: "navigator.gpu 不存在" };
  }
  try {
    const adapter = await navigator.gpu.requestAdapter();
    if (!adapter) return { available: false, f16: false, reason: "requestAdapter() 返回 null" };
    return { available: true, f16: adapter.features.has("shader-f16"), reason: "" };
  } catch (e) {
    return { available: false, f16: false, reason: String(e?.message ?? e) };
  }
}

export async function pickAutoConfig() {
  const gpu = await detectWebGPU();
  if (gpu.available && gpu.f16) return { key: "fp16_webgpu", reason: "检测到 WebGPU 且支持 shader-f16" };
  if (gpu.available) return { key: "int8_wasm", reason: "检测到 WebGPU 但不支持 shader-f16，回退 WASM/INT8" };
  return { key: "int8_wasm", reason: `WebGPU 不可用（${gpu.reason || "unknown"}），回退 WASM/INT8` };
}

function aggregateProgress(onProgress) {
  const files = new Map();
  return (p) => {
    if (!p || !p.file) return;
    if (p.status === "progress" && typeof p.total === "number" && p.total > 0) {
      files.set(p.file, { loaded: p.loaded ?? 0, total: p.total });
    }
    let loaded = 0, total = 0;
    for (const f of files.values()) { loaded += f.loaded; total += f.total; }
    onProgress?.({
      file: p.file,
      status: p.status,
      progress: total ? Math.min(100, (loaded / total) * 100) : null,
      loaded, total,
    });
  };
}

/**
 * Load a feature-extraction pipeline.
 * @param {string} configKey key of CONFIGS (or "auto")
 * @param {object} [opts]
 * @param {(p:object)=>void} [opts.onProgress]
 * @returns {Promise<{pipe:Function, device:string, dtype:string, configKey:string, fallback:boolean, fallbackReason:string, requested:string}>}
 */
export async function loadModel(configKey = "auto", opts = {}) {
  let key = configKey;
  let fallbackReason = "";
  let requested = key;
  if (key === "auto") {
    const picked = await pickAutoConfig();
    key = picked.key;
    fallbackReason = picked.reason;
    requested = "auto";
  }
  const cfg = CONFIGS[key];
  if (!cfg || cfg.key === "auto") throw new Error(`unknown config ${configKey}`);

  const progress_callback = aggregateProgress(opts.onProgress);
  const device = cfg.device;
  const dtype = cfg.dtype;
  try {
    const pipe = await pipeline("feature-extraction", MODEL_ID, { device, dtype, progress_callback });
    return { pipe, device, dtype, configKey: key, fallback: false, fallbackReason: "", requested };
  } catch (e) {
    if (device === "webgpu") {
      // Explicit, observable degradation path: WebGPU failed -> WASM/q8.
      const reason = String(e?.message ?? e);
      const pipe = await pipeline("feature-extraction", MODEL_ID, {
        device: "wasm", dtype: "q8", progress_callback,
      });
      return {
        pipe, device: "wasm", dtype: "q8", configKey: "int8_wasm", fallback: true,
        fallbackReason: `WebGPU/FP16 初始化失败，自动降级 WASM/INT8：${reason}`,
        requested,
      };
    }
    throw e;
  }
}

/**
 * Embed texts in batches (mean pooling + L2 normalize).
 * @returns {Promise<number[][]>}
 */
export async function embedBatch(model, texts, opts = {}) {
  const batchSize = Math.max(1, opts.batchSize ?? 8);
  const out = [];
  for (let i = 0; i < texts.length; i += batchSize) {
    const batch = texts.slice(i, i + batchSize);
    const tensor = await model.pipe(batch, { pooling: "mean", normalize: true });
    out.push(...tensor.tolist());
    opts.onProgress?.(Math.min(texts.length, i + batch.length), texts.length);
    // yield so the UI can repaint between batches; background tabs must not hit the
    // 1-minute timer throttling (that would make automated benchmarks 10x slower).
    if (!document.hidden) await new Promise((r) => setTimeout(r, 0));
    else await Promise.resolve();
  }
  return out;
}

export function disposeModel(model) {
  try {
    if (typeof model?.pipe?.dispose === "function") model.pipe.dispose();
    else if (typeof model?.pipe?.model?.dispose === "function") model.pipe.model.dispose();
  } catch { /* ignore */ }
}