# 一页技术说明：端侧 AI 推理 × seekdb 混合检索

> 题目：600073（seekdb × 阶跃星辰「端侧 AI 推理性能优化与 seekdb 混合检索」）
> 测试环境：Windows 11 / Edge 156.0.4314.42（Chromium 156）/ 18 逻辑核 / WebGPU 可用且支持 `shader-f16`；
> seekdb 1.4.0（Docker server 模式，本机 2881）；Node 24；语料 64 篇中文文档、24 条查询。

## 1. 模型与量化

**模型**：[Xenova/bge-small-zh-v1.5](https://huggingface.co/Xenova/bge-small-zh-v1.5)（BAAI bge-small-zh-v1.5 的 ONNX 转换版，中文，512 维，
开源许可见模型卡），随应用以本地文件提供；`scripts/fetch-model.mjs` 可复现下载。

| 精度 | 权重大小（ONNX） | 应用内算入 tokenizer/config 后 | 相对 fp32 |
| --- | --- | --- | --- |
| fp32（基线） | 94,851,877 B（90.46 MiB） | 91.0 MB | 1.00× |
| FP16 | 47,497,427 B（45.30 MiB） | 45.8 MB | **1.99×** |
| INT8（q8） | 24,010,842 B（22.90 MiB） | 23.4 MB | **3.88×** |

- **INT8 方案**：ONNX Runtime 动态量化权重文件 `onnx/model_quantized.onnx`（权重 INT8、激活运行时量化），
  由 Transformers.js 的 `dtype: 'q8'` 直接加载。
- **FP16 方案**：`onnx/model_fp16.onnx` 半精度权重；仅在 WebGPU 且适配器支持 `shader-f16` 时启用
  （Transformers.js 在 `device=webgpu` 下会校验该特性，不支持则抛错并触发降级）。
- **检索质量**（同一 64 篇语料、24 条带二元相关性标注的查询；Recall@K = 命中数/相关数，nDCG@10 取二元增益，
  按查询平均；评测集由 `scripts/gen_eval_data.py` 生成，无训练）：

| 配置 | 混合检索 R@5 | R@10 | nDCG@10 | 向量单路 R@5 | R@10 | nDCG@10 |
| --- | --- | --- | --- | --- | --- | --- |
| fp32 基线 | 0.972 | 0.972 | 0.943 | 0.917 | 0.972 | 0.938 |
| INT8(q8) | 0.951（**−0.021**） | 0.972（0） | 0.941（**−0.002**） | 0.917 | 0.972 | 0.938 |
| FP16 | 0.972（0） | 0.972（0） | 0.943（0） | 0.917 | 0.972 | 0.938 |

## 2. 端侧运行（WebGPU / WASM 降级）

- 运行时：**Transformers.js 3.8.1**（内含 ONNX Runtime Web），`pipeline('feature-extraction', ...)`；
  文档与查询向量均在浏览器主线程计算（批量间 `await` 让出 UI），无任何云端推理请求。
- **显式后端选择**：先 `navigator.gpu` + `requestAdapter()` 检测；可用且支持 `shader-f16` 时用
  `{ device: 'webgpu', dtype: 'fp16' }`，否则用 `{ device: 'wasm', dtype: 'q8' }`。
- **自动降级**：`device=webgpu` 初始化/推理抛错时，捕获异常后用 `{ device: 'wasm', dtype: 'q8' }` 重建
  pipeline，并记录 `fallbackReason`；界面徽标显示 `WEBGPU · fp16` 或 `WASM · q8`。
- **降级验证**：注入 `Object.defineProperty(navigator, 'gpu', { get: () => undefined })` 后重新打开页面，
  显式请求 FP16/WebGPU 的实际结果为 `wasm/q8`、`fallback=true`，原因
  `does not support fp16`；完整记录见 `results/verify-fallback-and-state.json`，
  截图见 `results/shot-webgpu-unavailable.png`。

## 3. seekdb 使用

- 接入方式：`seekdb-js` 1.4.0，**server 模式**（Docker `oceanbase/seekdb`，`127.0.0.1:2881`，`test` 库）。
- 集合结构：每个知识库一个集合，`Schema` = 全文索引 `FulltextIndexConfig('ik')`（中文分词）
  + HNSW 向量索引 `VectorIndexConfig({ hnsw: { dimension: 512, distance: 'cosine' } })`（默认 M/ef 参数）；
  `embeddingFunction: null`——向量一律由浏览器算好后传入。
- 写入：`upsert({ ids, documents, embeddings, metadatas })`，随后 `await refresh_index()`（seekdb 1.3+ 默认异步
  维护向量索引）；一次批量导入结束后刷新一次，避免逐条刷新。
- **混合检索（必须在库内完成）**：每次查询只发一次
  ```js
  collection.hybridSearch({
    query: { whereDocument: { $contains: 用户查询原文 }, nResults: 20 }, // 全文
    knn:   { queryEmbeddings: 浏览器算好的查询向量, nResults: 20 },      // 向量
    rank:  { rrf: {} },                                                 // seekdb 内 RRF 融合
    nResults: 5, include: ['documents', 'metadatas', 'distances'],
  })
  ```
  不在客户端分别取两路结果再拼合。
- 增量与刷新：`upsert` 按内容哈希 id 去重；基准中增量写入 2 条 → `refresh_index()` → 新增内容可检索
  （`results/bench-*.json` 的 `incremental.foundAfterRefresh=true`）。

## 4. 状态管理与优化结果

- **状态**：一个知识库 = 一个 seekdb 集合；服务端 `app/storage/kbs.json` 维护 KB 注册表并在启动时与
  `sdk_collections` 对齐；前端用 `localStorage` 记住当前 KB。切换 KB 后检索只针对当前集合。
  验证：两个 KB 用同一查询返回互不重叠的结果，切回原 KB 后排序完全一致（`verify-fallback-and-state.json`）。
- **批处理**：语料按 batch=8 向量化（可调 1/8/16/32）；基准中把 24 条查询合并成一次调用时，
  FP16/WebGPU 平均 4.5 ms/条，fp32/WASM 36.4 ms/条。
- **模型加载/缓存**：模型文件默认本地提供，浏览器 Cache Storage 缓存；冷加载（清缓存）vs 热加载：
  fp32 3216 → 509 ms，INT8 704 → 212 ms，FP16 1710 → 442 ms。
- **关键对比**（4 轮取中位数；延迟为客户端 `performance.now()`，包含 localhost HTTP 与 seekdb 服务端耗时）：

| 指标 | fp32/WASM | INT8/WASM | FP16/WebGPU |
| --- | --- | --- | --- |
| 语料向量化吞吐 | 11.95 docs/s | 16.51 docs/s（1.38×） | **70.95 docs/s（5.94×）** |
| 查询向量化 p50 | 39.2 ms | 25.9 ms | 52.9 ms |
| 批量查询 24 条 | 874 ms（36.4/item） | 572 ms（23.8/item） | **107 ms（4.5/item，8.2×）** |
| seekdb hybridSearch p50/p95 | 51/133 ms | 38/95 ms | 45/84 ms |
| 端到端 p50/p95（查询向量化+hybridSearch） | 94/183 ms | 65/136 ms | 102/213 ms |
| 增量写入后刷新可检索 | ✓ | ✓ | ✓ |

**结论**：INT8 以 1/3.9 体积换来 +38% 向量化吞吐、R@10 与 nDCG@10 基本不变（R@5 −0.021），是端侧默认档；
FP16/WebGPU 在**批量**向量化（导入、批量查询）上快 5.9~8.2 倍，单条查询因 GPU 调度开销与 WASM 同量级。
因此实现中"优先 WebGPU、不可用自动降级 WASM"：能用 GPU 时获得导入吞吐，单条查询也不劣化到不可用；
无 GPU 时自动降级并明确提示。

**局限/说明**：数据在共享开发机采集（同时运行其他应用），跨轮延迟波动较大（原始 4 轮数据
`results/raw-bench-run-*.json` 已保留，质量指标各轮一致）；`写入+refresh` 含首次建集合 DDL 与 HTTP 传输，
不作为精度对比结论；模型文件需联网下载（本地文件优先、镜像兜底），推理位置不变。