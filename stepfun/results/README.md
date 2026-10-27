# results —— 实测数据与验证记录

本目录保存参赛作品的实际运行证据。所有数字均来自本机真实运行（非估算、非虚构）。

## 文件说明

| 文件 | 内容 |
| --- | --- |
| `bench-summary.json` | **最近一轮**完整基准结果（含每配置的 per-query 结果、meta、原始耗时数组），与下方截图同一轮 |
| `bench-fp32_wasm.json` / `bench-int8_wasm.json` / `bench-fp16_webgpu.json` | 最近一轮按配置拆分的结果（应用每次点「运行基准评测」都会覆盖） |
| `raw-bench-run-D.json` … `raw-bench-run-G.json` | 用于**取中位数**的 4 轮独立原始结果 |
| `bench-aggregate.json` | 对上述 4 轮按配置取中位数的汇总（README / 技术说明中的表格即引用此文件），含每轮明细与相对 fp32 的对比 |
| `shot-full.png` | 应用全页截图：模型后端、知识库、导入耗时、混合检索结果、基准评测表格 |
| `shot-webgpu-unavailable.png` | 移除 `navigator.gpu` 后重新打开的页面：后端徽标为 `WASM · q8`，提示已自动降级 |
| `verify-fallback-and-state.json` | 降级与状态验证记录：WebGPU 不可用时的降级结果、两个知识库互相隔离且切回后排序一致、增量写入 + `refresh_index()` 后可检索 |

## 测试条件

- 设备/浏览器：Windows 11，Edge **156.0.4314.42**（Chromium 156），18 逻辑核；`navigator.gpu` 可用且支持 `shader-f16`
- seekdb：**1.4.0**（`5.7.25-OceanBase seekdb-v1.4.0.0`），Docker `oceanbase/seekdb`，server 模式 `127.0.0.1:2881`，`test` 库
- Node.js 24；应用服务 `127.0.0.1:3000`
- 模型：`Xenova/bge-small-zh-v1.5`（512 维）；ONNX 文件：fp32 94,851,877 B / FP16 47,497,427 B / INT8 24,010,842 B
- 数据：`data/corpus/docs.json` 64 篇中文文档；`data/eval/queries.json` 24 条查询（带二元相关性标注）
- 计时口径：客户端 `performance.now()`，包含 localhost HTTP 与 seekdb 服务端耗时；语料向量化取 3 次中位数，
  查询延迟取 24 次采样的 p50/p95；模型加载区分冷加载（清空浏览器 Cache Storage）与热加载。

## 方法学说明

1. 每轮依次测 `fp32 + WASM`、`INT8(q8) + WASM`、`FP16 + WebGPU`；每个配置创建独立集合，测完删除。
2. 语料向量化重复 3 次取中位数，避免首次预热偏差；24 条查询逐条计时，报告 p50/p95。
3. 质量指标：Recall@5/10、nDCG@10（二元增益），同一评价集对所有精度一致；各轮结果完全一致（嵌入是确定性的）。
4. 增量验证：每轮额外写入 2 篇文档 → `refresh_index()` → 用对应查询检索，确认 `foundAfterRefresh=true`。
5. `写入+refresh` 包含首次创建集合的 DDL 与 HTTP 传输，且受共享开发机负载影响，波动较大；
   精度对比结论以「语料向量化吞吐、模型体积、质量指标」为主。

## 波动说明（重要）

基准是在**共享开发机**上运行的（同时有浏览器、Docker、聊天软件等占用 CPU/GPU），跨轮绝对延迟波动较大
（例如 fp32 语料向量化 10.0~12.6 docs/s、单条端到端 49~183 ms）。因此：

- 本目录保留了全部 4 轮原始结果，README/技术说明使用**中位数**；
- `shot-full.png` 与 `bench-summary.json` 是其中**一轮**的展示，数字与中位数表可能略有差异；
- 相对结论（INT8 压 3.9 倍、FP16/WebGPU 批量向量化快 5~8 倍、质量几乎不变）在各轮间稳定。

## 重新生成

```bash
cd app && npm start                  # http://127.0.0.1:3000
# 浏览器点「运行基准评测」→ 生成 bench-*.json / bench-summary.json
# 反复运行多次后：
node ../scripts/aggregate-bench.mjs  # 读取 raw-bench-run-*.json → bench-aggregate.json
```

降级/状态验证依赖本仓库之外的 CDP 自动化脚本（用于移除 `navigator.gpu` 并驱动页面），
验证结果已固化在本目录 JSON 中；应用内的降级逻辑与界面提示可由人工在无 WebGPU 的浏览器中复现。