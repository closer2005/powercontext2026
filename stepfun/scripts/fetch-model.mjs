#!/usr/bin/env node
/**
 * Download the embedding model files used by the demo into app/public/models.
 *
 *   node scripts/fetch-model.mjs                 # all precisions (fp32 + fp16 + int8)
 *   node scripts/fetch-model.mjs --dtypes q8     # only the INT8 file (smallest)
 *   HF_ENDPOINT=https://hf-mirror.com node scripts/fetch-model.mjs
 *
 * The model is Xenova/bge-small-zh-v1.5 (Apache-2.0, 512-dim Chinese embedding model).
 * The browser still performs the inference locally; these files only remove network
 * flakiness at load time.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const REPO = "Xenova/bge-small-zh-v1.5";
const BASE = (process.env.HF_ENDPOINT || "https://hf-mirror.com").replace(/\/$/, "");
const DEST = path.join(ROOT, "app", "public", "models", ...REPO.split("/"));

const args = process.argv.slice(2);
const dtypeArgIdx = args.indexOf("--dtypes");
const dtypes = dtypeArgIdx >= 0
  ? String(args[dtypeArgIdx + 1] || "q8").split(",").map((s) => s.trim()).filter(Boolean)
  : ["fp32", "fp16", "q8"];

const ONNX_FILES = {
  fp32: "onnx/model.onnx",
  fp16: "onnx/model_fp16.onnx",
  q8: "onnx/model_quantized.onnx",
};
const AUX_FILES = [
  "config.json",
  "tokenizer.json",
  "tokenizer_config.json",
  "special_tokens_map.json",
  "vocab.txt",
];

const files = [...AUX_FILES, ...dtypes.map((d) => {
  if (!ONNX_FILES[d]) throw new Error(`unknown dtype ${d} (use fp32/fp16/q8)`);
  return ONNX_FILES[d];
})];

async function download(rel) {
  const dst = path.join(DEST, rel.split("/").join(path.sep));
  fs.mkdirSync(path.dirname(dst), { recursive: true });
  if (fs.existsSync(dst) && fs.statSync(dst).size > 0) {
    console.log(`skip  ${rel} (${(fs.statSync(dst).size / 1024 / 1024).toFixed(1)} MB)`);
    return fs.statSync(dst).size;
  }
  const url = `${BASE}/${REPO}/resolve/main/${rel}`;
  process.stdout.write(`fetch ${rel} ... `);
  const t0 = Date.now();
  const res = await fetch(url, { redirect: "follow", headers: { "user-agent": "stepfun-demo" } });
  if (!res.ok) throw new Error(`${rel}: HTTP ${res.status}`);
  const buf = Buffer.from(await res.arrayBuffer());
  fs.writeFileSync(dst, buf);
  const sec = Math.max(0.001, (Date.now() - t0) / 1000);
  console.log(`${(buf.length / 1024 / 1024).toFixed(1)} MB in ${sec.toFixed(1)}s (${(buf.length / 1024 / 1024 / sec).toFixed(2)} MB/s)`);
  return buf.length;
}

console.log(`source: ${BASE}/${REPO}`);
console.log(`dest  : ${DEST}`);
const sizes = {};
for (const f of files) sizes[f] = await download(f);

const total = (k) => Object.entries(sizes).filter(([f]) => f === ONNX_FILES[k]).reduce((a, [, v]) => a + v, 0);
if (dtypes.includes("fp32") && dtypes.includes("q8")) {
  console.log(`\nINT8 compression: ${(total("fp32") / total("q8")).toFixed(2)}x  (${(total("fp32") / 1048576).toFixed(2)} MB -> ${(total("q8") / 1048576).toFixed(2)} MB)`);
}
if (dtypes.includes("fp32") && dtypes.includes("fp16")) {
  console.log(`FP16 compression: ${(total("fp32") / total("fp16")).toFixed(2)}x  (${(total("fp32") / 1048576).toFixed(2)} MB -> ${(total("fp16") / 1048576).toFixed(2)} MB)`);
}
console.log("done. restart `npm start` if already running.");