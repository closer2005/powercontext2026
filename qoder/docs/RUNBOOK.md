# CiteSeek 知源 · 运行说明（RUNBOOK）

> 适用版本：v1（对应 [DESIGN.md](DESIGN.md)）
> 目标：评审 / 新成员在 10 分钟内从零启动、载入示例数据、看到「可溯源」的混合检索结果。
> 相关文档：[DESIGN.md](DESIGN.md)（权威规格）、[VERIFY.md](VERIFY.md)（验证样例）、[ARCHITECTURE.md](ARCHITECTURE.md)（架构说明）、[示例数据说明](../data/samples/README.md)。

## 1. 环境要求

| 项目 | 要求 | 说明 |
|---|---|---|
| 操作系统 | Windows 10/11 + Docker Desktop；macOS 13+；Linux + Docker Engine | 全部服务跑在容器里 |
| Docker | Docker 24+ 与 Compose v2 | `docker compose version` 能输出 v2.x；**不需要本机 Python / Node** |
| 资源 | 空闲内存 ≥ 4 GB，磁盘 ≥ 5 GB | 镜像、seekdb 数据、模型缓存 |
| 端口 | `8000`、`2881`、`2886` 空闲 | 8000 应用；2881 seekdb MySQL 协议；2886 seekdb 内部端口（以 compose 为准） |
| 浏览器 | Chrome / Edge 最新版 | 前端无 CDN 依赖，离线可用 |
| 网络 | 仅首次启动需要 | 拉镜像、装依赖、下载 BGE ONNX 模型；离线方案见 §6 |

启动前自检：

```bash
docker --version
docker compose version
docker info          # 能连上 Docker daemon
```

## 2. 获取代码与目录约定

```bash
git clone <参赛仓库地址>
cd <参赛仓库>/qoder        # 含 docker-compose.yml 的目录
```

> 说明：当前工作副本目录名为 `qoder_work/`，提交到参赛仓库（`2026-competition-ecosystem/qoder`）后目录名为 `qoder/`。下文所有命令都在**包含 `docker-compose.yml` 的目录**执行。

## 3. 一键启动

### 3.1 准备配置

```bash
cp .env.example .env          # Windows PowerShell: Copy-Item .env.example .env -Force
```

默认配置即可本地运行（`EMBED_MODE=auto`、`APP_PORT=8000`）。要改端口或离线模式见 §5、§6。

### 3.2 构建并启动

```bash
docker compose up -d --build
docker compose ps
```

- 首次构建要下载镜像、安装依赖、下载模型，实测约 `3–6 分钟（本机实测约 5 分钟：镜像构建 + seekdb 启动 + 嵌入模型下载 + 27 篇示例数据入库）`；之后启动为秒级。
- `docker compose ps` 应看到 `seekdb`（healthy）与 `citeseek`（healthy）。citeseek 的 healthcheck 通过 `python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')"` 探活 `/api/health`；seekdb 的 healthcheck 为 `mysqladmin ping -h 127.0.0.1 -P 2881`。
- 查看启动日志：`docker compose logs -f citeseek`，出现 `Application startup complete` 即可。

### 3.3 等待就绪并验证

应用启动时会**等待 seekdb 就绪（最多 60s 重试）**，随后自动建库建表、初始化 collection。

```bash
curl http://localhost:8000/api/health
```

健康时的响应（字段级）：

```json
{
  "status": "ok",
  "seekdb": {
    "connected": true,
    "database": "citeseek",
    "collection": "citeseek_chunks_v1",
    "count": 0
  },
  "embed": {
    "mode": "onnx",
    "model": "BAAI/bge-small-zh-v1.5",
    "dim": 512,
    "degraded": false
  },
  "version": "..."
}
```

判据：`status=ok`、`seekdb.connected=true`、`embed.dim=512`。

说明：

- `embed.mode` / `embed.model` 反映**实际**使用的嵌入器：ONNX 正常时为 `mode=onnx`、`model=BAAI/bge-small-zh-v1.5`；hash 兜底或主动 hash 模式为 `mode=hash`、`model=hash-ngram`，`embed.reason` 给出降级原因。
- `embed.degraded=true`：模型加载 / API 调用失败已降级为 hash，功能仍可用但语义召回变弱（见 §5.2、§7.3）。
- `status=degraded`：seekdb 未就绪（`connected=false`），见 §7.1。

一行轮询：

```bash
# bash / macOS / Linux / Git Bash
until curl -s http://localhost:8000/api/health | grep -q '"connected":true'; do sleep 2; done
curl -s http://localhost:8000/api/health
```

```powershell
# Windows PowerShell
while (-not (curl.exe -s http://localhost:8000/api/health | Select-String '"connected":true')) { Start-Sleep -Seconds 2 }
curl.exe -s http://localhost:8000/api/health
```

### 3.4 打开页面

浏览器访问 **<http://localhost:8000>**。页面有三个主视图（顶部 tab）：**检索 / 资料库 / 复习**；底部是**技术面板**，展示 seekdb 状态、最近检索日志（耗时 / 结果数 / 向量与全文标记）和 collection 统计。

## 4. 首次使用：示例数据

**默认行为**：`docker-compose.yml` 默认注入 `SEED_ON_START=1`，首次 `docker compose up -d --build` 后应用启动时**自动导入示例数据**（按 title 幂等判重）。等 `/api/health` 就绪后查 `/api/stats` 应看到 `notes=27`；若仍为 `0`，看 `docker compose logs citeseek` 中的 seed 日志（导入失败会记录原因），或按方式 A / B 手动导入一次（效果相同、幂等）。

### 方式 A：页面按钮

数据被清空、想手动再导入时：「资料库」→ 点「载入示例数据」。返回 `{"imported":27,"skipped":0}`；再点一次返回 `{"imported":0,"skipped":27}`（幂等）。

### 方式 B：命令行

```bash
curl -X POST http://localhost:8000/api/import/samples
```

### 方式 C：关闭启动自动导入

`SEED_ON_START` 默认 `1`（compose 注入）。如需关闭自动导入（例如自己准备数据），按 compose 的覆盖方式设为 `0`（修改 compose 的 `environment`，或让 compose 用 `${SEED_ON_START:-1}` 变量替换后由 `.env` 设置），再执行 `docker compose up -d`；之后用方式 A / B 手动导入。

验证：

```bash
curl -s http://localhost:8000/api/stats
```

判据：`notes=27`；`chunks` 实测约 **62**（当前 300/50 切块参数，随参数浮动），DESIGN §11 验收要求 `chunks>=60`。

数据说明：27 篇中文笔记，课程分布为 数据库系统 7 / 机器学习 8 / 高等数学 3 / 概率论与数理统计 3 / 科研方法 6，详见 [data/samples/README.md](../data/samples/README.md)。

## 5. 配置项

应用从环境变量读取配置（Docker 下由 `.env` 与 `docker-compose.yml` 注入），默认值来自 DESIGN §9：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `SEEKDB_HOST` | `127.0.0.1` | seekdb 主机；Docker Compose 内由编排覆盖为 `seekdb` |
| `SEEKDB_PORT` | `2881` | seekdb MySQL 协议端口 |
| `SEEKDB_USER` | `root` | 数据库用户 |
| `SEEKDB_PASSWORD` | 空 | 本地演示默认空密码；若镜像要求密码则填写 |
| `SEEKDB_DATABASE` | `citeseek` | 业务库名，启动时自动创建 |
| `EMBED_MODE` | `auto` | 嵌入模式，取值与降级行为见 §5.2 |
| `EMBED_MODEL` | `BAAI/bge-small-zh-v1.5` | 512 维中文嵌入模型 |
| `EMBED_CACHE_DIR` | `~/.cache/citeseek/models` | 模型缓存目录；Docker 内为 `/root/.cache/citeseek/models`，挂在 `citeseek_model_cache` 卷上 |
| `HF_ENDPOINT` | `https://hf-mirror.com` | 模型下载镜像；国内网络建议保留 |
| `EMBED_API_BASE` | 空 | `EMBED_MODE=api` 时必填，OpenAI 兼容 base URL |
| `EMBED_API_KEY` | 空 | `EMBED_MODE=api` 时必填 |
| `EMBED_API_MODEL` | 空 | `EMBED_MODE=api` 时的模型名 |
| `APP_PORT` | `8000` | 容器内监听端口；改宿主机端口请同时改 compose 的 `ports` 映射 |
| `SEED_ON_START` | `1`（compose 默认；`.env.example` 为 `0`） | `1` = 启动时自动导入示例数据（幂等）；`0` = 关闭自动导入。DESIGN §9 未列出该变量，以 `docker-compose.yml` 实际值为准 |

### 5.1 修改配置

Docker 方式下，compose 通过 `env_file: .env` 读取项目根目录的 `.env`；若同一变量在 `environment` 与 `.env` 中都出现，**以 compose `environment` 为准**。改完执行：

```bash
docker compose up -d          # 环境变量变化会重建容器使其生效
```

仅 `docker compose restart` 不一定重新读取环境变量，建议用 `up -d`。

### 5.2 EMBED_MODE 四种取值与降级行为

| 取值 | 行为 | 失败 / 异常时 | `/api/health` 观测 |
|---|---|---|---|
| `auto`（默认） | 优先加载本地 BGE ONNX；缓存缺失时从 `HF_ENDPOINT` 下载 | 退化为 hash（512 维字符 n-gram 哈希，确定性、离线可用），`degraded=true` 并给出原因；全文检索不受影响 | `embed.mode=hash`、`degraded=true` |
| `onnx` | 强制 BGE ONNX；加载失败时同样兜底为 hash（当前实现），便于先排查日志 | 退化为 hash，`degraded=true`，原因写入 `embed.reason` | `mode=hash`、`degraded=true` |
| `hash` | 直接用 hash，不联网、不下载模型；CI / 无网环境使用 | — | `mode=hash`、`dim=512`；主动选择 hash 不算降级 |
| `api` | 调用 `EMBED_API_BASE` 的 OpenAI 兼容 `/embeddings` 接口 | `EMBED_API_BASE` 未配置或调用失败 → 退化为 hash，`degraded=true` | `mode=api` 或 `hash`，`degraded` 标记 |

说明：实现口径是**任何模式加载失败都兜底为 hash**（`auto` / `onnx` / `api` 一致），并通过 `/api/health` 的 `embed.degraded`、`embed.reason` 显式暴露；主动选择 `EMBED_MODE=hash` 不算降级。降级后仍完整可用：全文关键词检索、结构化过滤、RRF 融合（向量一路质量下降）、复习、检索日志。

## 6. 无网络环境

- **首选 `EMBED_MODE=hash`**：不联网即可完整跑通导入 / 检索 / 复习；语义召回明显变弱，演示「换说法」请改用字面关键词（VERIFY §1.5 有对照说明）。
- **模型缓存持久化**：模型下载到 `citeseek_model_cache` 卷（实测约 `96 MB（BGE-small-zh-v1.5 ONNX 模型 94.8 MB + tokenizer 等）`），`docker compose restart` / `up -d` 不会重复下载。
- **完全离线复现**：先在联网机器完成一次 `docker compose up -d --build`（镜像与模型都就绪），再迁移镜像：

```bash
docker save -o citeseek-offline.tar oceanbase/seekdb:latest <citeseek 应用镜像名>
# 离线机器
docker load -i citeseek-offline.tar
```

- 或把已下载的模型目录拷贝到离线机器的 `EMBED_CACHE_DIR` / 缓存卷，配合 `EMBED_MODE=onnx`。
- 若镜像也无法迁移，仍可用 `EMBED_MODE=hash` 完成功能验证（降级不崩）。

## 7. 常见问题（FAQ）

### 7.1 seekdb 未就绪 / `seekdb.connected=false`

- 首次启动 seekdb 初始化较慢，应用会自动重试 60s；先等 30–60 秒再查。
- `docker compose ps` 看 seekdb 是否 healthy；`docker compose logs --tail=100 seekdb` 看初始化进度。
- 仍失败时：`docker compose restart citeseek`，或 `docker compose down && docker compose up -d`（不要随手删卷）。
- 若日志提示密码 / 权限错误，检查 `SEEKDB_PASSWORD` 与 compose 中 seekdb 的初始化参数是否一致。

### 7.2 端口冲突（8000 / 2881 / 2886）

- 查占用：
  - Windows PowerShell：`netstat -ano | Select-String ':8000'` 或 `Get-NetTCPConnection -LocalPort 8000`
  - macOS / Linux：`lsof -i :8000`
- 改端口：改 `.env` 的 `APP_PORT`，并同步改 `docker-compose.yml` 的 `ports`（如 `"8080:8000"`）；2881 冲突时同样改映射。
- 改完执行 `docker compose up -d`，用新端口访问。

### 7.3 模型下载失败 / `embed.degraded=true`

- 看日志：`docker compose logs citeseek | Select-String -Pattern 'embed|model|hf'`（bash 用 `grep -Ei 'embed|model|hf'`）。
- 检查网络与 `HF_ENDPOINT=https://hf-mirror.com`；公司代理环境需给 Docker 配代理。
- 临时方案：`.env` 设置 `EMBED_MODE=hash` 后 `docker compose up -d`，先跑通全流程，之后再切回 `auto`。
- 下载成功后的模型进缓存卷，重建容器不会重复下载。

### 7.4 如何彻底清理数据

```bash
# 停止容器并删除 named volumes（seekdb_data + citeseek_model_cache）
docker compose down -v

# 重新构建并启动（SEED_ON_START=1 时会自动重新导入示例数据）
docker compose up -d --build
```

注意：

- seekdb 数据与模型缓存都在 compose 管理的 **named volume** 里（`seekdb_data`、`citeseek_model_cache`），不是 bind mount 目录。
- `docker compose down`（不带 `-v`）只删容器，数据卷保留；**只删容器不会清数据**。
- 只想清业务数据、保留模型缓存：先 `docker compose down`，再 `docker volume rm <compose项目名>_seekdb_data`（用 `docker volume ls` 查实际卷名），然后 `docker compose up -d`。
- 清理后重启会按 `SEED_ON_START=1` 自动重新导入示例数据（也可手动点「载入示例数据」）。

### 7.5 载入示例数据后检索不到 / 结果很少

- 确认 `/api/stats` 的 `notes`、`chunks` 已增加；若 `chunks=0`，说明切块或写入失败，看 `docker compose logs citeseek`。
- seekdb 向量索引异步构建：导入流程在每篇写入 collection 后都会调用 `refresh_index()`；若手工写库或异常中断，可重启 `citeseek` 再试。
- `EMBED_MODE=hash` 下换说法召回弱属预期降级，改用字面关键词验证。
- 过滤条件过严（course + topic 同时限制）时结果可能为空，属正常行为；放宽一个条件再搜。

### 7.6 容器反复重启

```bash
docker compose logs --tail=200 citeseek
docker compose logs --tail=200 seekdb
```

常见原因：seekdb 未就绪、数据库连接参数错误、端口冲突、模型加载异常。按日志报错处理。

### 7.7 前端页面空白 / 接口 404

- 确认访问的是 `http://localhost:8000/`，而不是其它端口或子路径。
- `curl -s http://localhost:8000/api/health` 是否正常；前端静态文件由 FastAPI 托管，**不需要**额外起前端服务或执行构建。

## 8. 非 Docker 本地开发

适合改代码调试；仍需 Docker 提供 seekdb。

### 8.1 只启动 seekdb

```bash
docker compose up -d seekdb
docker compose ps            # 等 seekdb healthy
```

### 8.2 Python 环境（Python 3.11+）

```bash
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 8.3 设置环境变量并启动

bash：

```bash
export SEEKDB_HOST=127.0.0.1
export SEEKDB_PORT=2881
export SEEKDB_DATABASE=citeseek
export EMBED_MODE=auto        # 无网 / 无模型时改成 hash
uvicorn app.main:app --reload --port 8000
```

PowerShell：

```powershell
$env:SEEKDB_HOST='127.0.0.1'; $env:SEEKDB_PORT='2881'; $env:SEEKDB_DATABASE='citeseek'; $env:EMBED_MODE='auto'
uvicorn app.main:app --reload --port 8000
```

打开 <http://127.0.0.1:8000>。数据库不存在时应用会尝试创建（账号需有建库权限）。

### 8.4 测试

```bash
pytest -q                                                    # 全部；seekdb 不可用时 API 测试自动 skip
pytest -q tests/test_chunking.py tests/test_embeddings.py    # 不依赖 seekdb 的单元测试
```

### 8.5 与 Docker 方式的差异

- 本机开发 `SEEKDB_HOST=127.0.0.1`；容器内是 compose 服务名 `seekdb`。
- 模型缓存目录按 `EMBED_CACHE_DIR` 解析，与 Docker 的 named volume 不是同一份。
- 前端静态文件由 FastAPI 托管，不需要 `npm run dev` 之类的前端构建步骤。

## 9. 停止、重启与升级

```bash
docker compose stop                 # 停止所有服务
docker compose start                # 再启动
docker compose restart citeseek     # 只重启应用
docker compose down                 # 删除容器（保留数据卷）
docker compose up -d --build        # 代码变更后重建应用镜像
docker compose ps                   # 查看状态
```

数据持久化：seekdb 数据在 named volume `seekdb_data`，模型缓存在 `citeseek_model_cache` 卷；重建只影响应用容器。

## 10. 评审现场检查清单

- [ ] `docker compose up -d --build` 成功，`/api/health` 返回 `status=ok`、`seekdb.connected=true`、`embed.dim=512`
- [ ] 启动自动导入（或点「载入示例数据」）后 `/api/stats` 的 `notes=27`、`chunks` 实测约 62（DESIGN 验收要求 `>=60`）
- [ ] 搜索「隔离级别」返回带出处的片段，`took_ms` 有值
- [ ] 技术面板可见 seekdb 状态、最近检索日志与 collection 统计
- [ ] 按 [VERIFY.md](VERIFY.md) 完成语义检索、结构化过滤、检索即复习三组验证
- [ ] `EMBED_MODE=hash` 下仍能完成关键词检索（验证降级不崩）

## 11. 假设与已知差异

本文按 `docs/DESIGN.md` v1 编写；仓库中的 `docker-compose.yml`、`.env.example`、`app/config.py` 是最终事实来源。若变量名 / 端口 / 镜像名与实际文件不一致，以实际文件为准，并在 `docs/DECISIONS.md` 记录差异。当前明确标注的假设：

1. `SEED_ON_START` 默认 `1`（由 `docker-compose.yml` 注入，DESIGN §10 提到该变量、§9 未列出），启动时自动导入示例数据；如需关闭，按 compose 覆盖方式设为 `0`；
2. 任何 `EMBED_MODE` 加载失败都会兜底为 hash，`degraded=true` 并在 `embed.reason` 说明（DESIGN 只要求 `auto` / `api` 降级，此处为实现选择）；
3. 宿主机端口 `8000 / 2881 / 2886` 与 compose 映射一致，`seekdb` 服务名即容器内主机名；
4. 示例数据首次导入恰为 27 篇且 `imported=27`（若新增 / 删除 `data/samples/` 文件，数字随文件数变化）；
5. seekdb 数据与模型缓存使用 compose 的 named volume（DESIGN §10 示例为 bind mount，实际 compose 用 named volume）。