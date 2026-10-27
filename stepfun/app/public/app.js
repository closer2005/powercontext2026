/**
 * Demo UI glue:
 *   - model loading / backend badge
 *   - knowledge base management (one seekdb collection per KB)
 *   - import pipeline: chunk -> browser embedding -> seekdb upsert -> refresh_index
 *   - search pipeline: browser query embedding -> seekdb hybridSearch (vector + full-text RRF)
 *   - benchmark: fp32 / INT8 / FP16 x WASM / WebGPU, retrieval quality + latency
 *
 * `window.__app` exposes the same operations for scripted verification.
 */
import {
  CONFIGS, MODEL_ID, MODEL_DIM, MODEL_FILE_BYTES, AUX_FILE_BYTES,
  detectWebGPU, pickAutoConfig, loadModel, embedBatch, disposeModel,
} from "./embedder.js";
import {
  BENCH_CONFIGS, BENCH_CONFIG_LABELS, runBenchmark, recallAtK, ndcgAtK, percentile, DTYPE_BYTES,
} from "./bench.js";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));
const fmtMs = (x) => (x == null ? "–" : `${Number(x).toFixed(1)} ms`);
const fmtNum = (x, d = 3) => (x == null ? "–" : Number(x).toFixed(d));

const state = {
  model: null,
  modelKey: null,
  kbs: [],
  currentKbId: localStorage.getItem("stepfun.kb") || "",
  dataset: null,
  benchRunning: false,
  benchSummary: null,
  gpu: null,
};

// ---------------------------------------------------------------- api helpers
async function api(path, { method = "GET", body } = {}) {
  const res = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let json = null;
  try { json = await res.json(); } catch { /* ignore */ }
  if (!res.ok || (json && json.ok === false)) {
    throw new Error(json?.error || `${method} ${path} -> HTTP ${res.status}`);
  }
  return json;
}

// ---------------------------------------------------------------- ui helpers
function setStatus(id, text, kind = "") {
  const el = $(id);
  if (!el) return;
  el.textContent = text;
  el.dataset.kind = kind;
}

function setProgress(barId, pct) {
  const el = $(barId);
  if (el) el.style.width = `${Math.max(0, Math.min(100, pct))}%`;
}

function badge(id, text, kind = "muted") {
  const el = $(id.startsWith("#") ? id : `#${id}`);
  if (!el) return;
  el.textContent = text;
  el.className = `badge badge-${kind}`;
}

function renderKv(elId, pairs) {
  const el = $(elId);
  if (!el) return;
  el.innerHTML = pairs.map(([k, v]) => `<span>${k}: <b>${v}</b></span>`).join("");
}

function logBench(line) {
  const el = $("#bench-log");
  if (!el) return;
  const ts = new Date().toLocaleTimeString("zh-CN", { hour12: false });
  el.textContent += `[${ts}] ${line}\n`;
  el.scrollTop = el.scrollHeight;
}

// ---------------------------------------------------------------- health
let healthSeq = 0;
async function refreshHealth() {
  const seq = ++healthSeq;
  try {
    const h = await api("/api/health");
    if (seq !== healthSeq) return; // ignore stale responses that resolved out of order
    badge("badge-seekdb", `seekdb ${h.seekdb.version ?? "ok"} · ${h.seekdb.collectionCount ?? 0} 个集合`, "ok");
    state.health = h;
  } catch (e) {
    if (seq !== healthSeq) return;
    // don't flip a healthy badge to red on a transient failure (e.g. while the
    // benchmark is hammering seekdb); only report when we have never connected
    if (!state.health?.seekdb?.version) {
      badge("badge-seekdb", `seekdb 连接失败：${String(e.message).slice(0, 60)}`, "err");
    } else {
      console.warn("health refresh failed (keeping last known state):", e.message);
    }
  }
}

// ---------------------------------------------------------------- model
async function ensureModel(configKey = "auto") {
  if (state.model && state.modelKey === configKey) return state.model;
  if (state.model) { disposeModel(state.model); state.model = null; }
  setStatus("#model-status", "模型加载中…");
  setProgress("#model-progress-bar", 0);
  const t0 = performance.now();
  const model = await loadModel(configKey, {
    onProgress: (p) => {
      if (p.progress != null) {
        setProgress("#model-progress-bar", p.progress);
        setStatus("#model-status", `加载模型：${p.file} … ${p.progress.toFixed(0)}%`);
      } else if (p.status === "initiate") {
        setStatus("#model-status", `读取模型文件：${p.file}`);
      }
    },
  });
  model.loadMs = performance.now() - t0;
  model.requestedConfig = configKey;
  state.model = model;
  state.modelKey = configKey;
  setProgress("#model-progress-bar", 100);
  const backendText = `${model.device.toUpperCase()} · ${model.dtype}`;
  badge("badge-backend", `后端 ${backendText}`, model.fallback ? "warn" : "ok");
  setStatus("#model-status", model.fallback
    ? `已加载，但发生自动降级：${model.fallbackReason}`
    : `模型已就绪（${backendText}），加载耗时 ${fmtMs(model.loadMs)}。`);
  renderKv("#model-kv", [
    ["model", MODEL_ID],
    ["backend", backendText],
    ["load", fmtMs(model.loadMs)],
    ["dim", String(MODEL_DIM)],
  ]);
  return model;
}

// ---------------------------------------------------------------- knowledge bases
async function refreshKbs({ keepSelection = true } = {}) {
  const { kbs } = await api("/api/kbs");
  state.kbs = kbs;
  if (state.currentKbId && !kbs.some((k) => k.id === state.currentKbId)) state.currentKbId = "";
  if (!state.currentKbId && kbs.length) state.currentKbId = kbs[0].id;
  const sel = $("#kb-select");
  sel.innerHTML = kbs.length
    ? kbs.map((k) => `<option value="${k.id}">${escapeHtml(k.name)} · ${k.count ?? 0} 条</option>`).join("")
    : `<option value="">（尚未创建）</option>`;
  sel.value = state.currentKbId;
  localStorage.setItem("stepfun.kb", state.currentKbId);
  setStatus("#kb-status", kbs.length
    ? `共 ${kbs.length} 个知识库；当前：${kbs.find((k) => k.id === state.currentKbId)?.name ?? "-"}`
    : "还没有知识库，导入时会自动创建一个。");
}

async function createKb(name) {
  const { kb } = await api("/api/kbs", { method: "POST", body: { name, dim: MODEL_DIM } });
  state.currentKbId = kb.id;
  await refreshKbs();
  refreshHealth();
  setStatus("#kb-status", `已创建知识库「${kb.name}」（seekdb 集合 kb_${kb.id}）`);
  return kb;
}

async function ensureKb() {
  const found = state.kbs.find((k) => k.id === state.currentKbId);
  if (found) return found;
  return createKb("我的知识库");
}

async function deleteCurrentKb() {
  const kb = state.kbs.find((k) => k.id === state.currentKbId);
  if (!kb) return;
  if (!confirm(`删除知识库「${kb.name}」及其全部文档？`)) return;
  await api(`/api/kbs/${encodeURIComponent(kb.id)}`, { method: "DELETE" });
  state.currentKbId = "";
  await refreshKbs();
  refreshHealth();
  setStatus("#kb-status", `已删除「${kb.name}」`);
}

// ---------------------------------------------------------------- import
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function chunkText(text, maxLen = 240, overlap = 60) {
  const clean = String(text).replace(/\r\n/g, "\n").trim();
  if (!clean) return [];
  if (clean.length <= maxLen) return [clean];
  const out = [];
  let i = 0;
  while (i < clean.length) {
    const end = Math.min(clean.length, i + maxLen);
    out.push(clean.slice(i, end));
    if (end >= clean.length) break;
    i = Math.max(i + 1, end - overlap);
  }
  return out;
}

function hashString(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0).toString(36);
}

function parseTextarea(text) {
  return text.split(/\n\s*\n+/).map((s) => s.trim()).filter(Boolean);
}

async function collectImportItems() {
  const items = [];
  const textDocs = parseTextarea($("#import-text").value || "");
  textDocs.forEach((t, i) => items.push({ name: `粘贴文本 ${i + 1}`, text: t }));
  for (const file of Array.from($("#file-input").files ?? [])) {
    const text = await file.text();
    parseTextarea(text).forEach((t, i) => items.push({ name: `${file.name}${i ? ` #${i + 1}` : ""}`, text: t }));
  }
  return items;
}

async function importItems(items, { quiet = false } = {}) {
  if (!items.length) throw new Error("没有可导入的文本");
  const model = await ensureModel($("#model-config").value || "auto");
  const kb = await ensureKb();
  const batchSize = Number($("#batch-size").value || 8);
  const started = performance.now();

  const chunks = [];
  for (const item of items) {
    const pieces = chunkText(item.text);
    pieces.forEach((text, i) => {
      chunks.push({
        id: `${hashString(item.name + "#" + i)}_${chunks.length.toString(36)}`,
        text,
        meta: { title: item.name, chunk: i, source: item.name, chars: text.length },
      });
    });
  }
  if (!quiet) {
    setStatus("#import-status", `切分为 ${chunks.length} 个片段，浏览器本地向量化中…`);
    setProgress("#import-progress-bar", 0);
  }

  const tEmb0 = performance.now();
  const vectors = await embedBatch(model, chunks.map((c) => c.text), {
    batchSize,
    onProgress: (done, total) => {
      setProgress("#import-progress-bar", (done / total) * 85);
      if (!quiet) setStatus("#import-status", `浏览器本地向量化 ${done}/${total}…`);
    },
  });
  const embedMs = performance.now() - tEmb0;

  const ingest = await api("/api/ingest", {
    method: "POST",
    body: {
      kbId: kb.id,
      docs: chunks.map((c, i) => ({ id: c.id, text: c.text, vector: vectors[i], meta: c.meta })),
    },
  });
  const totalMs = performance.now() - started;
  setProgress("#import-progress-bar", 100);
  if (!quiet) {
    const backend = `${model.device.toUpperCase()}·${model.dtype}`;
    setStatus("#import-status", `已写入 seekdb 并完成索引刷新：${ingest.written} 个片段（集合共 ${ingest.count} 条）。`);
    renderKv("#import-timings", [
      ["后端", backend],
      ["批大小", batchSize],
      ["向量化", fmtMs(embedMs)],
      ["写入", fmtMs(ingest.writeMs)],
      ["refresh_index", fmtMs(ingest.refreshMs)],
      ["总耗时", fmtMs(totalMs)],
      ["吞吐", `${(chunks.length / (embedMs / 1000)).toFixed(1)} docs/s`],
    ]);
  }
  await refreshKbs();
  refreshHealth();
  return { kb, chunks: chunks.length, embedMs, ingest, totalMs, model, vectors };
}

// ---------------------------------------------------------------- search
function renderResults(results) {
  const ol = $("#results");
  if (!results.ids.length) {
    ol.innerHTML = `<li class="empty">没有检索结果。请先导入文档。</li>`;
    return;
  }
  ol.innerHTML = results.ids.map((id, i) => {
    const meta = results.metadatas[i] || {};
    const text = results.documents[i] || "";
    const dist = results.distances?.[i];
    const title = meta.title || id;
    return `<li class="result">
      <div class="result-head">
        <span class="result-title">${i + 1}. ${escapeHtml(title)}</span>
        <span class="result-meta">score distance=${dist == null ? "–" : Number(dist).toFixed(4)} · id=${escapeHtml(id)}</span>
      </div>
      <p class="result-text">${escapeHtml(text)}</p>
      <div class="result-tags">
        ${meta.topic ? `<span class="tag">主题 ${escapeHtml(meta.topic)}</span>` : ""}
        ${meta.chunk != null ? `<span class="tag">片段 ${meta.chunk}</span>` : ""}
        <span class="tag">向量 + 全文 RRF</span>
      </div>
    </li>`;
  }).join("");
}

async function search(query, { quiet = false } = {}) {
  const q = String(query ?? "").trim();
  if (!q) throw new Error("请输入查询");
  const model = await ensureModel($("#model-config").value || "auto");
  const kb = await ensureKb();
  const topK = Number($("#topk").value || 5);
  const t0 = performance.now();
  const [vector] = await embedBatch(model, [q], { batchSize: 1 });
  const t1 = performance.now();
  const res = await api("/api/search", {
    method: "POST",
    body: { kbId: kb.id, queryText: q, vector, topK, nCandidates: Math.max(20, topK * 4) },
  });
  const t2 = performance.now();
  if (!quiet) {
    setStatus("#search-status", `seekdb hybridSearch：全文 whereDocument + 向量 knn + RRF，返回 ${res.results.ids.length} 条`);
    renderKv("#search-timings", [
      ["查询向量化(浏览器)", fmtMs(t1 - t0)],
      ["seekdb hybridSearch", fmtMs(t2 - t1)],
      ["端到端", fmtMs(t2 - t0)],
      ["后端", `${model.device.toUpperCase()}·${model.dtype}`],
    ]);
    renderResults(res.results);
  }
  return { ...res, queryEmbedMs: t1 - t0, e2eMs: t2 - t0, kb, model };
}

// ---------------------------------------------------------------- benchmark
function renderBenchTable(rows) {
  const table = $("#bench-table");
  if (!rows.length) { table.innerHTML = ""; return; }
  const head = ["配置", "后端", "模型体积", "向量化", "写入+refresh", "hybrid p50/p95", "端到端 p50/p95", "R@5", "R@10", "nDCG@10", "ΔR@5"];
  const base = rows.find((r) => r.config === "fp32_wasm" && r.ok);
  const body = rows.map((r) => {
    if (!r.ok) {
      return `<tr><td>${r.label}</td><td colspan="10">失败：${escapeHtml(r.error || "unknown")}</td></tr>`;
    }
    const q = r.quality.hybrid;
    const delta = r.deltaVsFp32 ? r.deltaVsFp32.hybridRecall5 : (r === base ? 0 : null);
    const deltaCls = delta == null ? "" : delta < -0.005 ? "bad" : "good";
    return `<tr>
      <td>${r.label}</td>
      <td>${r.device.toUpperCase()}·${r.dtype}${r.fallback ? "（降级）" : ""}</td>
      <td class="num">${(r.modelBytes / 1024 / 1024).toFixed(1)} MB</td>
      <td class="num">${fmtNum(r.docsPerSec, 1)} docs/s</td>
      <td class="num">${fmtNum(r.writeMs, 0)}+${fmtNum(r.refreshMs, 0)} ms</td>
      <td class="num">${fmtNum(r.latencyMs.hybridP50, 0)}/${fmtNum(r.latencyMs.hybridP95, 0)} ms</td>
      <td class="num">${fmtNum(r.latencyMs.e2eP50, 0)}/${fmtNum(r.latencyMs.e2eP95, 0)} ms</td>
      <td class="num">${fmtNum(q.recall5)}</td>
      <td class="num">${fmtNum(q.recall10)}</td>
      <td class="num">${fmtNum(q.ndcg10)}</td>
      <td class="num ${deltaCls}">${delta == null ? "–" : (delta >= 0 ? "+" : "") + fmtNum(delta)}</td>
    </tr>`;
  }).join("");
  table.innerHTML = `<thead><tr>${head.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${body}</tbody>`;
}

async function startBenchmark(configs = BENCH_CONFIGS) {
  if (state.benchRunning) throw new Error("基准评测正在运行");
  state.benchRunning = true;
  $("#btn-bench").disabled = true;
  $("#bench-log").textContent = "";
  $("#bench-status").textContent = "准备评测数据集…";
  logBench(`开始评测：${configs.map((c) => BENCH_CONFIG_LABELS[c]).join(" / ")}`);
  try {
    const dataset = await api("/api/dataset");
    state.dataset = dataset;
    const summary = await runBenchmark({
      configs,
      dataset,
      api: {
        listKbs: () => api("/api/kbs"),
        createKb: async (name) => (await api("/api/kbs", { method: "POST", body: { name, dim: MODEL_DIM } })).kb,
        ingest: (kbId, docs) => api("/api/ingest", { method: "POST", body: { kbId, docs } }),
        search: (kbId, queryText, vector, topK) => api("/api/search", { method: "POST", body: { kbId, queryText, vector, topK } }),
        searchVector: (kbId, vector, topK) => api("/api/search/vector", { method: "POST", body: { kbId, vector, topK } }),
        deleteKb: (kbId) => api(`/api/kbs/${encodeURIComponent(kbId)}`, { method: "DELETE" }),
        saveResults: (name, data) => api("/api/results", { method: "POST", body: { name, data } }),
      },
      onEvent: (ev) => {
        if (ev.type === "log") { logBench(ev.message); }
        else if (ev.type === "config-start") { logBench(`▶ ${ev.label}`); setProgress("#bench-progress-bar", 0); $("#bench-status").textContent = `正在评测 ${ev.label} …`; }
        else if (ev.type === "model-loaded") { logBench(`  模型加载 ${fmtMs(ev.loadMs)}（${ev.device}/${ev.dtype}${ev.fallback ? "，已降级" : ""}）`); }
        else if (ev.type === "embed-progress") { setProgress("#bench-progress-bar", 10 + (ev.done / ev.total) * 30); }
        else if (ev.type === "ingested") { logBench(`  写入 seekdb ${ev.count} 条，write=${fmtMs(ev.writeMs)} refresh=${fmtMs(ev.refreshMs)}`); }
        else if (ev.type === "query-progress") { setProgress("#bench-progress-bar", 40 + (ev.done / ev.total) * 50); }
        else if (ev.type === "incremental") { logBench(`  增量写入 ${ev.added} 条，刷新后可检索：${ev.foundAfterRefresh}`); }
        else if (ev.type === "config-done") {
          renderBenchTable(summaryRowsOf(ev.row));
          logBench(`✓ ${ev.row.label}：向量化 ${fmtNum(ev.row.docsPerSec, 1)} docs/s，hybrid p50 ${fmtNum(ev.row.latencyMs.hybridP50, 0)} ms，R@10 ${fmtNum(ev.row.quality.hybrid.recall10)}`);
        }
        else if (ev.type === "config-error") { logBench(`✗ ${ev.error}`); }
        else if (ev.type === "done") {
          state.benchSummary = ev.summary;
          renderBenchTable(ev.summary.rows);
          setProgress("#bench-progress-bar", 100);
          $("#bench-status").textContent = `评测完成，结果已写入 results/（${ev.summary.rows.filter((r) => r.ok).length} 个配置成功）`;
          logBench("全部完成；bench-summary.json 已写入 results/");
        }
      },
    });
    state.benchSummary = summary;
    return summary;
  } finally {
    state.benchRunning = false;
    $("#btn-bench").disabled = false;
  }
}

function summaryRowsOf(row) {
  const rows = (state.benchSummary?.rows ?? []).filter((r) => r.config !== row.config);
  state.benchSummary = { ...(state.benchSummary ?? {}), rows: [...rows, row] };
  return state.benchSummary.rows;
}

// ---------------------------------------------------------------- events
function bindEvents() {
  $("#btn-load-model").addEventListener("click", async () => {
    try { await ensureModel($("#model-config").value); }
    catch (e) { setStatus("#model-status", `模型加载失败：${e.message}`, "err"); }
  });
  $("#model-config").addEventListener("change", () => { /* 下次操作时按新配置重新加载 */ });

  $("#btn-create-kb").addEventListener("click", async () => {
    const name = $("#kb-name").value.trim() || `知识库 ${state.kbs.length + 1}`;
    try { await createKb(name); $("#kb-name").value = ""; }
    catch (e) { setStatus("#kb-status", `创建失败：${e.message}`, "err"); }
  });
  $("#kb-select").addEventListener("change", (e) => {
    state.currentKbId = e.target.value;
    localStorage.setItem("stepfun.kb", state.currentKbId);
    setStatus("#kb-status", `已切换知识库：${state.kbs.find((k) => k.id === state.currentKbId)?.name ?? "-"}`);
  });
  $("#btn-delete-kb").addEventListener("click", () => deleteCurrentKb().catch((e) => setStatus("#kb-status", e.message, "err")));

  $("#btn-sample").addEventListener("click", async () => {
    try {
      const ds = state.dataset ?? (state.dataset = await api("/api/dataset"));
      const sample = ds.docs.slice(0, 12);
      $("#import-text").value = sample.map((d) => `【${d.title}】${d.text}`).join("\n\n");
      setStatus("#import-status", `已载入示例语料 ${sample.length} 篇（主题：${[...new Set(sample.map((d) => d.topic))].join("、")}）`);
    } catch (e) { setStatus("#import-status", e.message, "err"); }
  });
  $("#btn-clear-text").addEventListener("click", () => { $("#import-text").value = ""; $("#file-input").value = ""; });

  $("#btn-import").addEventListener("click", async () => {
    $("#btn-import").disabled = true;
    try { await importItems(await collectImportItems()); }
    catch (e) { setStatus("#import-status", `导入失败：${e.message}`, "err"); }
    finally { $("#btn-import").disabled = false; }
  });

  $("#btn-search").addEventListener("click", async () => {
    $("#btn-search").disabled = true;
    try { await search($("#query").value); }
    catch (e) { setStatus("#search-status", `检索失败：${e.message}`, "err"); }
    finally { $("#btn-search").disabled = false; }
  });
  $("#query").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#btn-search").click(); });

  $("#btn-bench").addEventListener("click", () => startBenchmark().catch((e) => { setStatus("#bench-status", e.message, "err"); logBench(`评测失败：${e.message}`); }));
  $("#btn-bench-clear").addEventListener("click", () => { $("#bench-log").textContent = ""; });
}

// ---------------------------------------------------------------- automation hook
async function demo({ docs = 12, query = "西湖附近安静适合看书的咖啡馆", config = "auto" } = {}) {
  const model = await ensureModel(config);
  const existing = state.kbs.find((k) => k.name === "示例知识库 · 杭州生活指南");
  const kb = existing ?? (await createKb("示例知识库 · 杭州生活指南"));
  state.currentKbId = kb.id;
  localStorage.setItem("stepfun.kb", kb.id);
  const ds = await api("/api/dataset");
  const items = ds.docs.slice(0, docs).map((d) => ({ name: d.title, text: d.text }));
  const imp = await importItems(items);
  const res = await search(query, { quiet: false });
  await refreshHealth();
  return {
    kb: kb.name, kbId: kb.id, docs: imp.chunks, embedMs: imp.embedMs,
    backend: `${model.device}/${model.dtype}`, query, topK: res.results.ids.length,
    queryEmbedMs: res.queryEmbedMs, searchMs: res.searchMs, e2eMs: res.e2eMs,
  };
}

window.__app = {
  state,
  api,
  ensureModel,
  ensureKb,
  createKb,
  refreshKbs,
  refreshHealth,
  importItems,
  search,
  startBenchmark,
  demo,
  runBenchmark,
  metrics: { recallAtK, ndcgAtK, percentile },
  configs: { CONFIGS, BENCH_CONFIGS, BENCH_CONFIG_LABELS, MODEL_ID, MODEL_DIM, MODEL_FILE_BYTES, AUX_FILE_BYTES, DTYPE_BYTES },
};

// ---------------------------------------------------------------- boot
(async function boot() {
  bindEvents();
  await refreshKbs().catch((e) => setStatus("#kb-status", `读取知识库失败：${e.message}`, "err"));
  await refreshHealth();

  // surface WebGPU availability immediately
  state.gpu = await detectWebGPU();
  if (!state.gpu.available) badge("badge-backend", `WebGPU 不可用（${state.gpu.reason.slice(0, 30)}），将使用 WASM/INT8`, "warn");

  const params = new URLSearchParams(location.search);
  const autorun = params.get("autorun");
  if (autorun === "demo") {
    demo().catch((e) => setStatus("#search-status", `自动演示失败：${e.message}`, "err"));
  } else if (autorun === "bench") {
    const configs = (params.get("configs") || BENCH_CONFIGS.join(",")).split(",").filter((c) => BENCH_CONFIGS.includes(c));
    startBenchmark(configs.length ? configs : BENCH_CONFIGS).catch((e) => { setStatus("#bench-status", e.message, "err"); });
  }
})();