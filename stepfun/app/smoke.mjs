#!/usr/bin/env node
/**
 * Connectivity smoke test: seekdb server + seekdb-js (no browser, no model needed).
 * Creates a temporary collection with a tiny 8-dim HNSW index + ik fulltext index,
 * writes two rows, runs one hybridSearch, then drops the collection.
 *
 *   node smoke.mjs
 */
import { SeekdbClient, Schema, VectorIndexConfig, FulltextIndexConfig } from "seekdb";

const client = new SeekdbClient({
  host: process.env.SEEKDB_HOST ?? "127.0.0.1",
  port: Number(process.env.SEEKDB_PORT ?? 2881),
  user: process.env.SEEKDB_USER ?? "root",
  password: process.env.SEEKDB_PASSWORD ?? "",
  database: process.env.SEEKDB_DATABASE ?? "test",
});

const name = `smoke_${Date.now()}`;
const DIM = 8;
try {
  const schema = new Schema({
    vectorIndex: new VectorIndexConfig({ hnsw: { dimension: DIM, distance: "cosine" } }),
    fulltextIndex: new FulltextIndexConfig("ik"),
  });
  const col = await client.createCollection({ name, schema, embeddingFunction: null });
  console.log("created collection:", col.name, "dimension:", col.dimension);

  const vec = (i) => Array.from({ length: DIM }, (_, k) => (k === i ? 1 : 0));
  await col.add({
    ids: ["a", "b"],
    documents: ["端侧推理与向量检索", "全文检索使用 ik 分词"],
    embeddings: [vec(0), vec(1)],
    metadatas: [{ kind: "vector" }, { kind: "fulltext" }],
  });
  await col.refresh_index();

  const r = await col.hybridSearch({
    query: { whereDocument: { $contains: "全文" }, nResults: 5 },
    knn: { queryEmbeddings: vec(0), nResults: 5 },
    rank: { rrf: {} },
    nResults: 2,
    include: ["documents", "metadatas", "distances"],
  });
  console.log("hybridSearch ids:", r.ids[0]);
  console.log("hybridSearch docs:", r.documents?.[0]);
  console.log("SMOKE OK");
} finally {
  try { await client.deleteCollection(name); } catch { /* ignore */ }
  await client.close();
}