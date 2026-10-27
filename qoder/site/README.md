# CiteSeek 知源 · 作品展示站

OceanBase 2026 数据库大赛 · Qoder 赛题（题目 600078）参赛作品页。
纯静态站点（HTML + CSS + JS，无构建、无 CDN 外链），可离线打开。

## 目录结构

```
site/
├── index.html          # 单页展示站（Hero / 痛点 / 功能 / 演示 / 技术 / 证据 / 开发记录 / 运行 / 验证 / 页脚）
├── README.md           # 本文件
└── assets/
    ├── style.css       # 全站样式（浅色主题，#0f766e + #f59e0b，响应式）
    ├── app.js          # 导航折叠、平滑滚动、占位图点击提示（无框架）
    └── *.png / *.gif   # 截图占位资源（见下方清单，待替换）
```

## 本地预览

```bash
cd site
python -m http.server 8080
# 浏览器打开 http://localhost:8080
```

也可以直接双击 `index.html`（`file://`）预览：页面不发起任何网络请求，只依赖相对路径的 `assets/`。
注意：页面里的 `http://localhost:8000` 是**应用本体**（CiteSeek 检索服务）的地址，不是本站地址。

## 部署到 Qoder Sites

1. 选择本 `site/` 目录作为站点根目录（静态站点，无需构建命令）。
2. 保持目录内相对路径不变：`index.html` 引用 `assets/style.css`、`assets/app.js`。
3. 上传后确认首屏、锚点导航、占位图点击提示（右下角 toast）正常。
4. 若站点需可通过外网访问，请确认没有开启任何依赖外部的资源（当前无 CDN / 外部字体 / 外部脚本）。

## 待替换的占位资源清单

所有截图目前是「灰底 + 说明 + 文件名」的占位块，替换同名文件即可自动生效，无需改 HTML。
建议宽度 1440px 以上，PNG 压缩；动图建议 ≤ 8 MB。

| 文件（`site/assets/`） | 位置 | 建议内容 |
|---|---|---|
| `demo-search.png` | Hero + 功能卡 + 演示区大图 | 检索视图：搜索框、结果片段、出处标签、融合分数 |
| `demo-import.png` | 功能卡「资料导入与分块」 | 资料库视图：导入表单与笔记列表 |
| `demo-review.png` | 功能卡「检索即复习」 | 复习视图：待复习片段与四个评分按钮 |
| `demo-stats.png` | 功能卡「技术证据面板」 | 底部技术面板：seekdb 状态、collection 统计、检索日志 |
| `demo.gif` | 演示区右侧 | 30 秒操作录屏：导入 → 检索 → 加入复习 |
| `dev-record-1.png` | 开发记录 · 阶段 02 | Qoder 生成建表 / collection 初始化代码的截图 |
| `dev-record-2.png` | 开发记录 · 阶段 03 | Qoder 实现 `/api/search` 混合检索的截图 |
| `dev-record-3.png` | 开发记录 · 阶段 05 | Qoder 跑 pytest / 修复索引刷新的截图 |

> `demo-import.png` 是在简报预留的 7 个文件之外补充的第 8 张。若只准备 7 张，可把它换成任意一张
> 资料库截图，或直接复用 `demo-search.png`（文件名需与 `index.html` 中的 `data-file` 一致）。

## 发布前还要改的地方

- `index.html` 中 Qoder 账号 UID 占位：搜索 `UID: &lt;待填&gt;`，替换为真实 UID。
- 全站检索日志与统计数字均标注为「示例数据」，替换真实截图后建议同步核对文案。
- 代码仓库链接：`https://github.com/closer2005/powercontext2026/tree/2026-competition-ecosystem/qoder`。

## 无障碍与兼容

- 语义化结构：`header/main/section/article/figure/figcaption`，跳转链接指向 `#main`。
- 占位块使用原生 `<button>`，可键盘聚焦，点击后 toast 提示待替换文件名（`aria-live="polite"`）。
- 支持 `prefers-reduced-motion`；焦点样式可见；对比度满足正文阅读。
- 响应式断点：1000px / 860px（导航折叠）/ 640px（单列）。
- 目标浏览器：Chrome / Edge / Safari / Firefox 最近两个大版本。