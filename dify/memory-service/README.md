# 离谱法庭 · 书记员服务（memory-service）

《离谱法庭 · The Absurd Court》的配套后端，负责 **seekdb 应用数据存储（案卷库）**：
立案、先例检索、判决归档、原告案底统计。Dify Chatflow 通过 HTTP Request 节点调用本服务；
所有接口一律返回 `text/plain; charset=utf-8` 纯文本，Dify 节点直接读取 `body` 字符串，避免 JSON 解析兼容问题。

技术栈刻意保持极简：**Python 3.10+ 标准库 `http.server` + PyMySQL**，除 `PyMySQL` 外无第三方依赖。

## 1. 接口契约

| 方法 | 路径 | 请求体（JSON） | 返回文本 |
|---|---|---|---|
| POST | `/api/cases` | `{"plaintiff","defendant","charge","claim","evidence"}` | `案号：#0042`（入库 `status=open`） |
| POST | `/api/cases/verdict` | `{"case_no","verdict","penalty","judgment"}` | `⚖️ 已归档：案卷 #0042 · 判决：罪名成立（本院累计已结 N 案）` |
| POST | `/api/cases/search` | `{"plaintiff","q","limit"}` | 多行先例；无先例时 `【先例】首次出现的被告类型，无历史判例。` |
| POST | `/api/stats` | `{"plaintiff"}` | 多行案底统计 |
| GET | `/healthz` | – | `ok`（数据库不可用时 `503 degraded: ...`） |

设计约定：

- **业务错误也返回 HTTP 200 + 文本**（如 `⚠️ 归档失败：未找到案卷 #0042`），保证 Chatflow 在异常场景下仍能继续对话而不是整条工作流报错；只有 `/healthz` 在数据库失联时返回 503。
- **案号规则**：`#` + 4 位零填充自增 id（`#0001`）。先插入临时唯一案号拿自增 id，再回写正式案号，保证并发安全。
- **先例检索**：先匹配原告自己的已结案件（`★原告旧案` 标记，体现"法官记仇"），不足 `limit` 条再用全库 `defendant/charge` 关键词模糊匹配补齐；最近案件优先。
- **称号规则**：0 案 = 法庭新鲜人；1-2 案 = 偶尔较真的市民；3-5 案 = 法庭常客；6-9 案 = 无理取闹大师；≥10 案 = 让法官都害怕的原告；特例（≥3 案且从未胜诉）= 屡战屡败的执着原告。

## 2. 目录

```
memory-service/
├── app.py                 # 服务本体（标准库 http.server + PyMySQL）
├── schema.sql             # 建库建表：absurd_court.cases（在 seekdb 上执行）
├── requirements.txt       # 仅 PyMySQL
├── config.example.env     # 配置示例（复制为 config.env，勿提交真实密码）
├── run.ps1                # Windows 启动脚本（支持 -InitDb）
├── run.sh                 # Linux/macOS 启动脚本
└── README.md
```

## 3. 快速开始

### 3.1 准备（首次）

```bash
cd memory-service
python -m venv .venv                      # 可选，推荐
# Windows: .venv\Scripts\activate    Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

cp config.example.env config.env          # 修改 DB_PASSWORD 为你的 seekdb 密码
```

### 3.2 初始化表结构

```bash
# 方式 A：服务自带（推荐，幂等）
python app.py --init-db
# 方式 B：mysql 客户端
mysql -h127.0.0.1 -P2881 -uroot -p < schema.sql
```

### 3.3 启动

```powershell
# Windows（自动从 config.example.env 生成 config.env，可 -InitDb 顺带建表）
.\run.ps1
```

```bash
# Linux / macOS
./run.sh
```

启动日志示例：

```
[2026-..-.. ..:..:..] seekdb 连接正常：root@127.0.0.1:2881/absurd_court
[2026-..-.. ..:..:..] 离谱法庭书记员服务已开庭：http://0.0.0.0:8899  （版本 1.0.0）
```

> **Dify 在 Docker 里，本服务在宿主机**：必须监听 `0.0.0.0`（默认），Dify 侧用
> `http://host.docker.internal:8899` 访问。Windows / macOS 的 Docker Desktop 自带该主机名；
> Linux 上需要在 compose 里给 api 服务加 `extra_hosts: ["host.docker.internal:host-gateway"]`。

## 4. 配置项

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DB_HOST` | `127.0.0.1` | seekdb 地址 |
| `DB_PORT` | `2881` | seekdb MySQL 协议端口 |
| `DB_USER` | `root` | seekdb 用户 |
| `DB_PASSWORD` | 空 | seekdb 密码（示例占位 `<SEEKDB_PASSWORD>`） |
| `DB_NAME` | `absurd_court` | 案卷库名 |
| `HOST` | `0.0.0.0` | HTTP 监听地址 |
| `PORT` | `8899` | HTTP 监听端口 |
| `LOG_FILE` | 空 | 设置后同时把访问日志追加到文件（便于留存运行证据） |

加载顺序：环境变量 > 同目录 `config.env` > 内置默认值。

## 5. 手工验收（curl / Invoke-RestMethod）

```bash
# 健康检查
curl -s http://127.0.0.1:8899/healthz
# ok

# 立案
curl -s -X POST http://127.0.0.1:8899/api/cases \
  -H "Content-Type: application/json" \
  -d '{"plaintiff":"user-demo","defendant":"充电线","charge":"通敌","claim":"要求它当庭道歉","evidence":"半夜偷偷发烫"}'
# 案号：#0001

# 先例检索
curl -s -X POST http://127.0.0.1:8899/api/cases/search \
  -H "Content-Type: application/json" \
  -d '{"plaintiff":"user-demo","q":"充电线 通敌","limit":3}'
# 【先例】首次出现的被告类型，无历史判例。

# 归档判决
curl -s -X POST http://127.0.0.1:8899/api/cases/verdict \
  -H "Content-Type: application/json" \
  -d '{"case_no":"#0001","verdict":"罪名成立","penalty":"罚它唱三夜摇篮曲","judgment":"本院认为……"}'
# ⚖️ 已归档：案卷 #0001 · 判决：罪名成立（本院累计已结 1 案）

# 案底统计
curl -s -X POST http://127.0.0.1:8899/api/stats \
  -H "Content-Type: application/json" -d '{"plaintiff":"user-demo"}'
```

PowerShell 等价写法：

```powershell
$body = @{ plaintiff='user-demo'; defendant='充电线'; charge='通敌'; claim='要求它当庭道歉'; evidence='半夜偷偷发烫' } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8899/api/cases -ContentType 'application/json' -Body $body
```

## 6. 在 Dify Chatflow 中的绑定

- 四个 HTTP Request 节点 URL 形如 `http://host.docker.internal:8899/api/cases`，method=POST，Body 类型 JSON。
- 服务返回纯文本，节点输出取 `body`（字符串）即可；`create_case` 的 `body` 直接就是 `#0042` 这样的干净案号，无需再截取。
- 若改端口/主机：在 Dify 画布中逐个编辑 4 个 HTTP 节点 URL（或在 `apps/build_dsl.py` 里改 `CLERK_BASE` 后重新生成 DSL 导入）。

## 7. 已知限制

- 单机单进程并发足够本作品使用；`ThreadingHTTPServer` 每请求新建一条 MySQL 连接（无连接池），高并发场景请自行替换为连接池/WSGI 服务。
- `plaintiff` 直接使用 Dify 传入的 `sys.user_id`（未做登录鉴权），本作品定位为本地演示，未设计多租户安全边界。
- `schema.sql` 依据 seekdb（MySQL 协议兼容）编写；如某版本不支持 `ON UPDATE CURRENT_TIMESTAMP`，删除该子句即可（`updated_at` 由服务端 UPDATE 时自然刷新，非功能必需）。