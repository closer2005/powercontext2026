#!/usr/bin/env node
/**
 * stepfun demo server
 * - serves the static browser app (public/)
 * - exposes the local embedding model directory and Transformers.js bundle
 * - bridges the browser to seekdb through seekdb-js (the browser never talks MySQL directly)
 *
 * The browser computes every embedding locally (WebGPU or WASM).
 * This server only stores the browser-provided vectors/documents in seekdb and runs
 * hybridSearch (full-text + vector, RRF) inside seekdb.
 */
import express from "express";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { performance } from "node:perf_hooks";
import mysql from "mysql2/promise";
import {
  SeekdbClient,
  SeekdbNotFoundError,
  Schema,
  VectorIndexConfig,
  FulltextIndexConfig,
} from "seekdb";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const DATA_DIR = path.join(ROOT, "data");
const RESULTS_DIR = path.join(ROOT, "results");
const STORAGE_DIR = path.join(__dirname, "storage");
const PUBLIC_DIR = path.join(__dirname, "public");
const TRANSFORMERS_DIST = path.join(__dirname, "node_modules", "@huggingface", "transformers", "dist");

const PORT = Number(process.env.PORT ?? 3000);
const HOST = process.env.HOST ?? "127.0.0.1";
const SEEKDB = {
  host: process.env.SEEKDB_HOST ?? "127.0.0.1",
  port: Number(process.env.SEEKDB_PORT ?? 2881),
  user: process.env.SEEKDB_USER ?? "root",
  password: process.env.SEEKDB_PASSWORD ?? "",
  database: process.env.SEEKDB_DATABASE ?? "test",
};
const DEFAULT_DIM = 512;       // Xenova/bge-small-zh-v1.5
const COLLECTION_PREFIX = "kb_";

fs.mkdirSync(RESULTS_DIR, { recursive: true });
fs.mkdirSync(STORAGE_DIR, { recursive: true });

const REGISTRY_FILE = path.join(STORAGE_DIR, "kbs.json");
let registry = {};
try {
  registry = JSON.parse(fs.readFileSync(REGISTRY_FILE, "utf8"));
} catch {
  registry = {};
}
const saveRegistry = () => fs.writeFileSync(REGISTRY_FILE, JSON.stringify(registry, null, 1), "utf8");

const client = new SeekdbClient({
  host: SEEKDB.host,
  port: SEEKDB.port,
  user: SEEKDB.user,
  password: SEEKDB.password,
  database: SEEKDB.database,
});

const collectionCache = new Map();

async function withMysql(fn) {
  const conn = await mysql.createConnection({
    host: SEEKDB.host, port: SEEKDB.port, user: SEEKDB.user, password: SEEKDB.password,
    database: SEEKDB.database,
  });
  try { return await fn(conn); } finally { await conn.end().catch(() => {}); }
}

/**
 * seekdb-js 1.4.0's listCollections() returns [] on this server build, so we read the
 * SDK metadata table directly. Only used for bookkeeping (counts / registry recovery).
 * A brand-new seekdb has no `sdk_collections` table until the first collection is created.
 */
const isMissingSdkTable = (e) => /sdk_collections.*(doesn'?t|does not) exist|1146/i.test(String(e?.message ?? e));

async function listKbCollectionNames() {
  return withMysql(async (conn) => {
    const [rows] = await conn.query(
      "SELECT collection_name FROM sdk_collections WHERE collection_name LIKE ?",
      [`${COLLECTION_PREFIX}%`],
    );
    return rows.map((r) => r.collection_name);
  });
}

async function countExistingCollection(name) {
  const col = await client.getCollection({ name, embeddingFunction: null });
  return col.count();
}

function makeSchema(dim) {
  return new Schema({
    vectorIndex: new VectorIndexConfig({ hnsw: { dimension: dim, distance: "cosine" } }),
    fulltextIndex: new FulltextIndexConfig("ik"),
  });
}

async function getCollection(kbId) {
  const key = String(kbId);
  if (!/^[a-zA-Z0-9_-]{1,64}$/.test(key)) throw new HttpError(400, "invalid kb id");
  if (collectionCache.has(key)) return collectionCache.get(key);
  const name = COLLECTION_PREFIX + key;
  const dim = registry[key]?.dim ?? DEFAULT_DIM;
  const col = await client.getOrCreateCollection({
    name,
    schema: makeSchema(dim),
    embeddingFunction: null, // embeddings always come from the browser
  });
  collectionCache.set(key, col);
  return col;
}

class HttpError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

function newKbId() {
  return Date.now().toString(36) + "_" + Math.random().toString(36).slice(2, 7);
}

const app = express();
app.use(express.json({ limit: "128mb" }));
app.disable("x-powered-by");

// --- static assets ---------------------------------------------------------
app.use("/", express.static(PUBLIC_DIR, { extensions: ["html"] }));
app.use("/vendor/transformers", express.static(TRANSFORMERS_DIST));
app.use("/models", express.static(path.join(PUBLIC_DIR, "models")));

// --- api -------------------------------------------------------------------
app.get("/api/health", async (req, res) => {
  let version = null;
  let dbError = null;
  // transient connection failures can happen while the benchmark is hammering seekdb,
  // so retry a couple of times before reporting the instance as unhealthy
  for (let attempt = 0; attempt < 3 && version === null; attempt++) {
    try {
      const conn = await mysql.createConnection({
        host: SEEKDB.host, port: SEEKDB.port, user: SEEKDB.user, password: SEEKDB.password,
      });
      const [rows] = await conn.query("SELECT VERSION() AS v");
      version = rows[0]?.v ?? null;
      await conn.end();
      dbError = null;
    } catch (e) {
      dbError = String(e?.message ?? e);
      await new Promise((r) => setTimeout(r, 150));
    }
  }
  let collectionCount = null;
  try {
    collectionCount = (await listKbCollectionNames()).length;
  } catch (e) {
    if (isMissingSdkTable(e)) {
      collectionCount = 0; // brand-new instance: no collections yet
    } else if (!dbError) {
      dbError = String(e?.message ?? e);
    }
  }
  res.json({
    ok: version !== null,
    error: dbError,
    service: "stepfun-ondevice-kb",
    // user-visible knowledge bases (not transient benchmark collections)
    seekdb: { ...SEEKDB, version, collectionCount: Object.keys(registry).length, dbCollections: collectionCount, error: dbError },
    model: {
      id: "Xenova/bge-small-zh-v1.5",
      dimension: DEFAULT_DIM,
      localPath: "/models/Xenova/bge-small-zh-v1.5/",
      remoteFallback: "https://hf-mirror.com",
    },
  });
});

app.get("/api/kbs", async (req, res, next) => {
  try {
    const out = [];
    let changed = false;
    for (const [id, meta] of Object.entries(registry)) {
      let count = null;
      try {
        count = await countExistingCollection(COLLECTION_PREFIX + id);
      } catch (e) {
        if (e instanceof SeekdbNotFoundError || isMissingSdkTable(e)) {
          // the registry outlived its collection (e.g. the DB volume was reset)
          delete registry[id];
          collectionCache.delete(id);
          changed = true;
          continue;
        }
        count = null;
      }
      out.push({ id, name: meta.name, createdAt: meta.createdAt, dim: meta.dim ?? DEFAULT_DIM, count });
    }
    if (changed) saveRegistry();
    out.sort((a, b) => String(a.createdAt).localeCompare(String(b.createdAt)));
    res.json({ kbs: out });
  } catch (e) { next(e); }
});

app.post("/api/kbs", async (req, res, next) => {
  try {
    const name = String(req.body?.name ?? "").trim() || "我的知识库";
    const dim = Number(req.body?.dim ?? DEFAULT_DIM);
    const id = newKbId();
    const col = await client.createCollection({
      name: COLLECTION_PREFIX + id,
      schema: makeSchema(dim),
      embeddingFunction: null,
    });
    collectionCache.set(id, col);
    registry[id] = { name, createdAt: new Date().toISOString(), dim };
    saveRegistry();
    res.json({ kb: { id, name, dim, count: 0, createdAt: registry[id].createdAt } });
  } catch (e) { next(e); }
});

app.delete("/api/kbs/:id", async (req, res, next) => {
  try {
    const id = req.params.id;
    const name = COLLECTION_PREFIX + id;
    let lastErr = null;
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        await client.deleteCollection(name);
        lastErr = null;
        break;
      } catch (e) {
        lastErr = e;
        await new Promise((r) => setTimeout(r, 200));
      }
    }
    if (lastErr) {
      // only keep the registry entry if the collection is really still there
      const existing = await listKbCollectionNames().catch(() => []);
      if (existing.includes(name)) throw lastErr;
    }
    collectionCache.delete(id);
    delete registry[id];
    saveRegistry();
    res.json({ ok: true });
  } catch (e) { next(e); }
});

/**
 * Body: { kbId, docs: [{id, text, vector, meta}] }
 * The vectors were produced in the browser. We only persist them and refresh the index.
 */
app.post("/api/ingest", async (req, res, next) => {
  try {
    const { kbId, docs } = req.body ?? {};
    if (!kbId || !Array.isArray(docs) || docs.length === 0) throw new HttpError(400, "kbId and docs are required");
    for (const d of docs) {
      if (!d.id || typeof d.text !== "string" || !Array.isArray(d.vector)) {
        throw new HttpError(400, "each doc needs id/text/vector");
      }
    }
    const col = await getCollection(kbId);
    if (docs[0].vector.length !== col.dimension) {
      throw new HttpError(400, `vector dimension ${docs[0].vector.length} != collection dimension ${col.dimension}`);
    }

    const t0 = performance.now();
    await col.upsert({
      ids: docs.map((d) => String(d.id)),
      documents: docs.map((d) => d.text),
      embeddings: docs.map((d) => d.vector),
      metadatas: docs.map((d) => ({ ...(d.meta ?? {}), _kb: String(kbId) })),
    });
    const t1 = performance.now();
    await col.refresh_index();
    const t2 = performance.now();
    const count = await col.count();
    const t3 = performance.now();

    res.json({
      ok: true,
      written: docs.length,
      count,
      writeMs: +(t1 - t0).toFixed(1),
      refreshMs: +(t2 - t1).toFixed(1),
      countMs: +(t3 - t2).toFixed(1),
      totalMs: +(t3 - t0).toFixed(1),
    });
  } catch (e) { next(e); }
});

/**
 * Body: { kbId, queryText, vector, topK, nCandidates }
 * One hybridSearch call: full-text (whereDocument) + vector (browser embedding) fused by RRF inside seekdb.
 */
app.post("/api/search", async (req, res, next) => {
  try {
    const { kbId, queryText, vector, topK = 5, nCandidates = 20 } = req.body ?? {};
    if (!kbId || typeof queryText !== "string" || !Array.isArray(vector)) {
      throw new HttpError(400, "kbId, queryText and vector are required");
    }
    const col = await getCollection(kbId);
    if (vector.length !== col.dimension) throw new HttpError(400, "vector dimension mismatch");

    const t0 = performance.now();
    const result = await col.hybridSearch({
      query: { whereDocument: { $contains: queryText }, nResults: nCandidates },
      knn: { queryEmbeddings: vector, nResults: nCandidates },
      rank: { rrf: {} },
      nResults: Math.max(1, Math.min(50, Number(topK) || 5)),
      include: ["documents", "metadatas", "distances"],
    });
    const t1 = performance.now();

    res.json({
      ok: true,
      searchMs: +(t1 - t0).toFixed(1),
      nCandidates,
      results: {
        ids: result.ids?.[0] ?? [],
        documents: result.documents?.[0] ?? [],
        metadatas: result.metadatas?.[0] ?? [],
        distances: result.distances?.[0] ?? [],
      },
    });
  } catch (e) { next(e); }
});

/** Vector-only search (used by the quality benchmark to isolate embedding precision). */
app.post("/api/search/vector", async (req, res, next) => {
  try {
    const { kbId, vector, topK = 10 } = req.body ?? {};
    if (!kbId || !Array.isArray(vector)) throw new HttpError(400, "kbId and vector are required");
    const col = await getCollection(kbId);
    const t0 = performance.now();
    const result = await col.query({
      queryEmbeddings: vector,
      nResults: Math.max(1, Math.min(50, Number(topK) || 10)),
      include: ["documents", "metadatas", "distances"],
    });
    const t1 = performance.now();
    res.json({
      ok: true,
      searchMs: +(t1 - t0).toFixed(1),
      results: {
        ids: result.ids?.[0] ?? [],
        documents: result.documents?.[0] ?? [],
        metadatas: result.metadatas?.[0] ?? [],
        distances: result.distances?.[0] ?? [],
      },
    });
  } catch (e) { next(e); }
});

app.get("/api/kbs/:id/info", async (req, res, next) => {
  try {
    const col = await getCollection(req.params.id);
    const [info, count] = await Promise.all([col.describe(), col.count()]);
    res.json({ info, count });
  } catch (e) { next(e); }
});

app.get("/api/dataset", (req, res, next) => {
  try {
    const docs = JSON.parse(fs.readFileSync(path.join(DATA_DIR, "corpus", "docs.json"), "utf8"));
    const queries = JSON.parse(fs.readFileSync(path.join(DATA_DIR, "eval", "queries.json"), "utf8"));
    res.json({ docs, queries });
  } catch (e) { next(e); }
});

/** Persist benchmark outputs inside stepfun/results so the evidence ships with the repo. */
app.post("/api/results", (req, res, next) => {
  try {
    const { name, data } = req.body ?? {};
    if (!name || !/^[a-zA-Z0-9_.-]{1,80}$/.test(name)) throw new HttpError(400, "invalid result name");
    const file = path.join(RESULTS_DIR, name.endsWith(".json") ? name : name + ".json");
    fs.writeFileSync(file, JSON.stringify(data, null, 2), "utf8");
    res.json({ ok: true, file: path.basename(file) });
  } catch (e) { next(e); }
});

// --- errors ----------------------------------------------------------------
app.use((err, req, res, next) => { // eslint-disable-line no-unused-vars
  const status = err instanceof HttpError ? err.status : 500;
  if (status >= 500) console.error("[server]", err);
  res.status(status).json({ ok: false, error: String(err?.message ?? err) });
});

/** Recover the KB registry from seekdb metadata (e.g. after a fresh clone: storage/ is gitignored). */
async function syncRegistryFromDb() {
  let names;
  try {
    names = await listKbCollectionNames();
  } catch (e) {
    if (isMissingSdkTable(e)) {
      if (Object.keys(registry).length) { registry = {}; saveRegistry(); }
      console.log("[stepfun] fresh seekdb database; registry cleared");
      return;
    }
    console.warn("[stepfun] registry sync skipped:", String(e?.message ?? e));
    return;
  }
  try {
    const ids = new Set(names.map((n) => n.slice(COLLECTION_PREFIX.length)));
    let changed = false;
    for (const id of ids) {
      if (!registry[id]) {
        registry[id] = {
          name: `知识库 ${id.slice(0, 6)}`,
          createdAt: new Date().toISOString(),
          dim: DEFAULT_DIM,
        };
        changed = true;
      }
    }
    for (const id of Object.keys(registry)) {
      if (!ids.has(id)) { delete registry[id]; changed = true; }
    }
    // drop benchmark collections left behind by an interrupted run
    for (const [id, meta] of Object.entries(registry)) {
      if (!String(meta.name || "").startsWith("bench-")) continue;
      try {
        await client.deleteCollection(COLLECTION_PREFIX + id);
        console.log(`[stepfun] removed leftover benchmark collection kb_${id}`);
      } catch { /* keep it if the drop failed */ }
      delete registry[id];
      changed = true;
    }
    if (changed) saveRegistry();
    console.log(`[stepfun] registry synced: ${Object.keys(registry).length} knowledge base(s)`);
  } catch (e) {
    console.warn("[stepfun] registry sync skipped:", String(e?.message ?? e));
  }
}

const server = app.listen(PORT, HOST, () => {
  console.log(`[stepfun] http://${HOST}:${PORT}  (public: ${PUBLIC_DIR})`);
  console.log(`[stepfun] seekdb: ${SEEKDB.host}:${SEEKDB.port}/${SEEKDB.database}`);
  syncRegistryFromDb();
});

process.on("SIGINT", async () => {
  try { await client.close(); } catch {}
  server.close(() => process.exit(0));
});