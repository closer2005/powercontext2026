/**
 * Quantization / backend benchmark + retrieval-quality evaluation.
 *
 * Runs entirely in the browser: the same corpus is embedded with each model precision,
 * written to a fresh seekdb collection through the local server, and queried on a fixed
 * query set. Only embeddings computed in the browser are stored (no server-side inference).
 */
import {
  CONFIGS, MODEL_ID, MODEL_DIM, MODEL_FILE_BYTES, AUX_FILE_BYTES,
  loadModel, embedBatch, detectWebGPU, disposeModel,
} from "./embedder.js";

export const BENCH_CONFIGS = ["fp32_wasm", "int8_wasm", "fp16_webgpu"];
export const BENCH_CONFIG_LABELS = {
  fp32_wasm: "fp32 + WASM（基线）",
  int8_wasm: "INT8(q8) + WASM",
  fp16_webgpu: "FP16 + WebGPU",
};
export const DTYPE_BYTES = {
  fp32: MODEL_FILE_BYTES.fp32 + AUX_FILE_BYTES,
  fp16: MODEL_FILE_BYTES.fp16 + AUX_FILE_BYTES,
  q8: MODEL_FILE_BYTES.q8 + AUX_FILE_BYTES,
};

export function recallAtK(ids, qrels, k) {
  if (!qrels.length) return 0;
  const set = new Set(qrels);
  return ids.slice(0, k).filter((id) => set.has(id)).length / qrels.length;
}

export function ndcgAtK(ids, qrels, k) {
  const set = new Set(qrels);
  let dcg = 0;
  ids.slice(0, k).forEach((id, i) => { if (set.has(id)) dcg += 1 / Math.log2(i + 2); });
  let idcg = 0;
  for (let i = 0; i < Math.min(qrels.length, k); i++) idcg += 1 / Math.log2(i + 2);
  return idcg ? dcg / idcg : 0;
}

export function percentile(arr, p) {
  if (!arr.length) return null;
  const s = [...arr].sort((a, b) => a - b);
  const idx = Math.min(s.length - 1, Math.ceil((p / 100) * s.length) - 1);
  return s[Math.max(0, idx)];
}

const mean = (arr) => (arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : 0);
const r3 = (x) => Math.round(x * 1000) / 1000;
const r1 = (x) => Math.round(x * 10) / 10;

/**
 * @param {object} opts
 * @param {string[]} opts.configs
 * @param {{docs:Array,queries:Array}} opts.dataset
 * @param {object} opts.api {createKb, ingest, search, searchVector, deleteKb, saveResults}
 * @param {(ev:object)=>void} [opts.onEvent]
 */
export async function runBenchmark({ configs, dataset, api, onEvent = () => {} }) {
  const startedAt = new Date().toISOString();
  const gpu = await detectWebGPU();
  const meta = {
    startedAt,
    browser: navigator.userAgent,
    platform: navigator.userAgentData?.platform ?? navigator.platform ?? "unknown",
    hardwareConcurrency: navigator.hardwareConcurrency ?? null,
    webgpu: gpu,
    model: { id: MODEL_ID, dimension: MODEL_DIM },
    corpus: { docs: dataset.docs.length, queries: dataset.queries.length },
    modelFileBytes: DTYPE_BYTES,
    configs,
  };
  onEvent({ type: "meta", meta });

  // Force a cold model-file fetch so the load timing is comparable across configs.
  let cacheCleared = false;
  try {
    cacheCleared = await caches.delete("transformers-cache");
    await caches.delete("transformers-cache");
  } catch { /* cache API may be unavailable */ }
  meta.cacheCleared = cacheCleared;
  onEvent({ type: "log", message: cacheCleared ? "已清空模型文件缓存（本轮为冷加载）" : "模型文件缓存清空失败或被禁用" });

  // Clean up collections left behind by an aborted benchmark tab before starting.
  try {
    const { kbs } = await api.listKbs();
    const leftovers = (kbs ?? []).filter((k) => k.name.startsWith("bench-"));
    for (const k of leftovers) await api.deleteKb(k.id);
    if (leftovers.length) onEvent({ type: "log", message: `清理上次中断的评测集合 ${leftovers.length} 个` });
  } catch { /* ignore */ }

  const rows = [];
  const stamp = Date.now().toString(36);

  for (const configKey of configs) {
    const cfgLabel = BENCH_CONFIG_LABELS[configKey] ?? configKey;
    onEvent({ type: "config-start", config: configKey, label: cfgLabel });
    const row = { config: configKey, label: cfgLabel, ok: false };

    let model = null;
    let kb = null;
    try {
      // ---------- 1. model load (cold files) ----------
      const tLoad0 = performance.now();
      model = await loadModel(configKey, {
        onProgress: (p) => onEvent({ type: "model-progress", config: configKey, progress: p }),
      });
      row.loadMs = r1(performance.now() - tLoad0);
      row.device = model.device;
      row.dtype = model.dtype;
      row.fallback = model.fallback;
      row.fallbackReason = model.fallbackReason;
      row.modelBytes = DTYPE_BYTES[model.dtype] ?? null;
      onEvent({ type: "model-loaded", config: configKey, device: model.device, dtype: model.dtype, loadMs: row.loadMs, fallback: model.fallback });

      // ---------- 2. fresh collection ----------
      kb = await api.createKb(`bench-${configKey}-${stamp}`);
      row.kbId = kb.id;

      // ---------- 3. browser-side embedding of the corpus (3 repetitions, median) ----------
      const batchSize = 8;
      const EMBED_REPS = 3;
      const embedRuns = [];
      for (let rep = 0; rep < EMBED_REPS; rep++) {
        const tEmb0 = performance.now();
        const vecs = await embedBatch(model, dataset.docs.map((d) => d.text), {
          batchSize,
          onProgress: (done, total) => onEvent({ type: "embed-progress", config: configKey, done, total }),
        });
        embedRuns.push({ ms: performance.now() - tEmb0, vecs });
      }
      const vectors = embedRuns[0].vecs; // identical input -> same vectors, reuse for ingest
      row.embedMsRuns = embedRuns.map((r) => r1(r.ms));
      row.embedMs = r1(percentile(row.embedMsRuns, 50));
      row.embedBatchSize = batchSize;
      row.docsPerSec = r3(dataset.docs.length / (row.embedMs / 1000));

      // ---------- 4. write to seekdb + refresh index ----------
      const ingest = await api.ingest(kb.id, dataset.docs.map((d, i) => ({
        id: d.id,
        text: d.text,
        vector: vectors[i],
        meta: { title: d.title, topic: d.topic, docId: d.id },
      })));
      row.writeMs = ingest.writeMs;
      row.refreshMs = ingest.refreshMs;
      row.ingestTotalMs = ingest.totalMs;
      row.count = ingest.count;
      onEvent({ type: "ingested", config: configKey, count: ingest.count, writeMs: ingest.writeMs, refreshMs: ingest.refreshMs });

      // ---------- 5. query set ----------
      const lat = { embed: [], hybrid: [], vector: [], e2e: [] };
      const quality = {
        hybrid: { recall5: [], recall10: [], ndcg10: [] },
        vector: { recall5: [], recall10: [], ndcg10: [] },
      };
      const perQuery = [];
      for (let qi = 0; qi < dataset.queries.length; qi++) {
        const q = dataset.queries[qi];
        const t0 = performance.now();
        const [qv] = await embedBatch(model, [q.query], { batchSize: 1 });
        const t1 = performance.now();
        const hybrid = await api.search(kb.id, q.query, qv, 10);
        const t2 = performance.now();
        const vector = await api.searchVector(kb.id, qv, 10);
        const t3 = performance.now();

        lat.embed.push(t1 - t0);
        lat.hybrid.push(t2 - t1);
        lat.vector.push(t3 - t2);
        lat.e2e.push(t2 - t0); // user-visible latency = query embedding + seekdb hybridSearch
        quality.hybrid.recall5.push(recallAtK(hybrid.results.ids, q.qrels, 5));
        quality.hybrid.recall10.push(recallAtK(hybrid.results.ids, q.qrels, 10));
        quality.hybrid.ndcg10.push(ndcgAtK(hybrid.results.ids, q.qrels, 10));
        quality.vector.recall5.push(recallAtK(vector.results.ids, q.qrels, 5));
        quality.vector.recall10.push(recallAtK(vector.results.ids, q.qrels, 10));
        quality.vector.ndcg10.push(ndcgAtK(vector.results.ids, q.qrels, 10));
        perQuery.push({
          id: q.id, query: q.query,
          hybridTop5: hybrid.results.ids.slice(0, 5),
          vectorTop5: vector.results.ids.slice(0, 5),
        });
        if (qi === 0) {
          row.firstQueryEmbedMs = r1(lat.embed[0]);
          row.firstQueryEndToEndMs = r1(lat.e2e[0]);
        }
        onEvent({ type: "query-progress", config: configKey, done: qi + 1, total: dataset.queries.length });
      }

      row.latencyMs = {
        queryEmbedP50: r1(percentile(lat.embed, 50)),
        queryEmbedP95: r1(percentile(lat.embed, 95)),
        hybridP50: r1(percentile(lat.hybrid, 50)),
        hybridP95: r1(percentile(lat.hybrid, 95)),
        vectorP50: r1(percentile(lat.vector, 50)),
        vectorP95: r1(percentile(lat.vector, 95)),
        e2eP50: r1(percentile(lat.e2e, 50)),
        e2eP95: r1(percentile(lat.e2e, 95)),
      };

      // Supplementary: batched query embedding (all eval queries in one call).
      // This isolates throughput from per-call dispatch overhead.
      try {
        const tQB = performance.now();
        await embedBatch(model, dataset.queries.map((q) => q.query), { batchSize: dataset.queries.length });
        row.queryBatchMs = r1(performance.now() - tQB);
        row.queryBatchPerItemMs = r1(row.queryBatchMs / dataset.queries.length);
      } catch { /* ignore */ }
      row.quality = {
        hybrid: {
          recall5: r3(mean(quality.hybrid.recall5)),
          recall10: r3(mean(quality.hybrid.recall10)),
          ndcg10: r3(mean(quality.hybrid.ndcg10)),
        },
        vector: {
          recall5: r3(mean(quality.vector.recall5)),
          recall10: r3(mean(quality.vector.recall10)),
          ndcg10: r3(mean(quality.vector.ndcg10)),
        },
      };
      row.perQuery = perQuery;

      // ---------- 6. incremental write + refresh check ----------
      const incDocs = [
        { id: `inc_${configKey}_1`, title: "增量：深夜咖啡", topic: "cafe", text: "新导入的文档：这家深夜咖啡店营业到凌晨三点，适合加班后喝一杯热拿铁。" },
        { id: `inc_${configKey}_2`, title: "增量：向量检索笔记", topic: "db", text: "新导入的文档：向量检索需要先把文本转成 embedding，再写入向量索引。" },
      ];
      const incVectors = await embedBatch(model, incDocs.map((d) => d.text), { batchSize: 2 });
      const incIngest = await api.ingest(kb.id, incDocs.map((d, i) => ({
        id: d.id, text: d.text, vector: incVectors[i], meta: { title: d.title, topic: d.topic },
      })));
      const check = await api.search(kb.id, "深夜营业的咖啡店", incVectors[0], 5);
      row.incremental = {
        added: incDocs.length,
        refreshMs: incIngest.refreshMs,
        foundAfterRefresh: check.results.ids.includes(incDocs[0].id),
        totalCount: incIngest.count,
      };
      onEvent({ type: "incremental", config: configKey, ...row.incremental });

      // ---------- 7. warm model load (files already in browser cache) ----------
      // Dispose the first session first, so this measures ONNX session init with warm
      // files instead of doubling resident model memory.
      try {
        disposeModel(model);
        model = null;
        const tWarm0 = performance.now();
        const warmModel = await loadModel(configKey);
        row.warmLoadMs = r1(performance.now() - tWarm0);
        disposeModel(warmModel);
      } catch (e) {
        row.warmLoadMs = null;
      }

      row.ok = true;
    } catch (e) {
      row.error = String(e?.message ?? e);
      onEvent({ type: "config-error", config: configKey, error: row.error });
    } finally {
      try { if (kb) await api.deleteKb(kb.id); } catch { /* ignore */ }
      disposeModel(model);
    }
    rows.push(row);
    onEvent({ type: "config-done", config: configKey, row });
    try { await api.saveResults(`bench-${configKey}`, row); } catch { /* ignore */ }
  }

  // baseline deltas (quality) vs fp32
  const base = rows.find((r) => r.config === "fp32_wasm" && r.ok);
  if (base) {
    for (const r of rows) {
      if (!r.ok || r === base) continue;
      r.deltaVsFp32 = {
        hybridRecall5: r3(r.quality.hybrid.recall5 - base.quality.hybrid.recall5),
        hybridRecall10: r3(r.quality.hybrid.recall10 - base.quality.hybrid.recall10),
        hybridNdcg10: r3(r.quality.hybrid.ndcg10 - base.quality.hybrid.ndcg10),
        vectorRecall5: r3(r.quality.vector.recall5 - base.quality.vector.recall5),
        vectorRecall10: r3(r.quality.vector.recall10 - base.quality.vector.recall10),
        vectorNdcg10: r3(r.quality.vector.ndcg10 - base.quality.vector.ndcg10),
      };
    }
  }

  const summary = { meta, rows, finishedAt: new Date().toISOString() };
  onEvent({ type: "done", summary });
  try { await api.saveResults("bench-summary", summary); } catch { /* ignore */ }
  return summary;
}