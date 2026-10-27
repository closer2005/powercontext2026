#!/usr/bin/env node
/**
 * Aggregate repeated benchmark runs into a median table.
 *
 * The browser benchmark (stepfun/app/public/bench.js) writes one summary per run into
 * stepfun/results/raw-bench-run-*.json (and bench-summary.json for the latest run).
 * Timings on a shared dev machine fluctuate, so this script reports the median of N runs
 * while keeping every raw run next to it.
 *
 *   node scripts/aggregate-bench.mjs
 *   -> results/bench-aggregate.json
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const RESULTS = path.resolve(__dirname, "..", "results");

const files = fs.readdirSync(RESULTS)
  .filter((f) => /^raw-bench-run-.*\.json$/.test(f))
  .sort();
if (!files.length) {
  console.error("no raw-bench-run-*.json files found");
  process.exit(1);
}

const runs = files.map((f) => ({ file: f, data: JSON.parse(fs.readFileSync(path.join(RESULTS, f), "utf8")) }));
const configs = [...new Set(runs.flatMap((r) => r.data.rows.map((row) => row.config)))];

const median = (arr) => {
  const s = arr.filter((x) => typeof x === "number" && Number.isFinite(x)).sort((a, b) => a - b);
  if (!s.length) return null;
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
};
const r1 = (x) => (x == null ? null : Math.round(x * 10) / 10);
const r3 = (x) => (x == null ? null : Math.round(x * 1000) / 1000);

const out = {
  generatedAt: new Date().toISOString(),
  runs: runs.map((r) => ({ file: r.file, startedAt: r.data.meta?.startedAt, browser: r.data.meta?.browser })),
  environment: runs[0].data.meta ?? null,
  note: "每个配置在每轮中重复 3 次语料向量化取中位数；跨轮结果取中位数。质量指标在各轮完全一致。",
  configs: {},
};

for (const cfg of configs) {
  const rows = runs.map((r) => r.data.rows.find((x) => x.config === cfg && x.ok)).filter(Boolean);
  if (!rows.length) continue;
  const pick = (fn) => median(rows.map(fn));
  out.configs[cfg] = {
    label: rows[0].label,
    device: rows[0].device,
    dtype: rows[0].dtype,
    fallback: rows.some((r) => r.fallback),
    modelBytes: rows[0].modelBytes,
    modelMB: rows[0].modelBytes ? r3(rows[0].modelBytes / 1048576) : null,
    runs: rows.length,
    loadMs: r1(pick((r) => r.loadMs)),
    warmLoadMs: r1(pick((r) => r.warmLoadMs)),
    embedMs: r1(pick((r) => r.embedMs)),
    docsPerSec: r3(pick((r) => r.docsPerSec)),
    writeMs: r1(pick((r) => r.writeMs)),
    refreshMs: r1(pick((r) => r.refreshMs)),
    queryEmbedP50: r1(pick((r) => r.latencyMs.queryEmbedP50)),
    queryEmbedP95: r1(pick((r) => r.latencyMs.queryEmbedP95)),
    hybridP50: r1(pick((r) => r.latencyMs.hybridP50)),
    hybridP95: r1(pick((r) => r.latencyMs.hybridP95)),
    e2eP50: r1(pick((r) => r.latencyMs.e2eP50)),
    e2eP95: r1(pick((r) => r.latencyMs.e2eP95)),
    queryBatchMs: r1(pick((r) => r.queryBatchMs)),
    queryBatchPerItemMs: r1(pick((r) => r.queryBatchPerItemMs)),
    quality: {
      hybridRecall5: r3(median(rows.map((r) => r.quality.hybrid.recall5))),
      hybridRecall10: r3(median(rows.map((r) => r.quality.hybrid.recall10))),
      hybridNdcg10: r3(median(rows.map((r) => r.quality.hybrid.ndcg10))),
      vectorRecall5: r3(median(rows.map((r) => r.quality.vector.recall5))),
      vectorRecall10: r3(median(rows.map((r) => r.quality.vector.recall10))),
      vectorNdcg10: r3(median(rows.map((r) => r.quality.vector.ndcg10))),
    },
    incrementalFoundAfterRefresh: rows.every((r) => r.incremental?.foundAfterRefresh),
    perRun: Object.fromEntries(rows.map((r, i) => [runs[i].file, {
      docsPerSec: r.docsPerSec, loadMs: r.loadMs, writeMs: r.writeMs, refreshMs: r.refreshMs,
      hybridP50: r.latencyMs.hybridP50, e2eP50: r.latencyMs.e2eP50,
    }])),
  };
}

const base = out.configs.fp32_wasm;
if (base) {
  out.comparisonVsFp32 = {};
  for (const [cfg, c] of Object.entries(out.configs)) {
    out.comparisonVsFp32[cfg] = {
      compressionRatio: c.modelMB && base.modelMB ? r3(base.modelMB / c.modelMB) : null,
      embedSpeedup: c.docsPerSec && base.docsPerSec ? r3(c.docsPerSec / base.docsPerSec) : null,
      warmLoadSpeedup: c.warmLoadMs && base.warmLoadMs ? r3(base.warmLoadMs / c.warmLoadMs) : null,
      hybridRecall5Delta: c.quality.hybridRecall5 != null ? r3(c.quality.hybridRecall5 - base.quality.hybridRecall5) : null,
      hybridRecall10Delta: r3(c.quality.hybridRecall10 - base.quality.hybridRecall10),
      hybridNdcg10Delta: r3(c.quality.hybridNdcg10 - base.quality.hybridNdcg10),
    };
  }
}

fs.writeFileSync(path.join(RESULTS, "bench-aggregate.json"), JSON.stringify(out, null, 2), "utf8");
console.log(`aggregated ${runs.length} runs -> results/bench-aggregate.json`);
console.log(JSON.stringify({ configs: out.configs, comparisonVsFp32: out.comparisonVsFp32 }, null, 1));