# 作品网站内容简报（给 site-builder）

> 目标：做一个**中文**作品展示网站，作为 OceanBase 2026 数据库大赛 Qoder 赛题（题目 600078）的参赛作品页面。
> 评审通过这个网站了解项目、按运行说明复现、核对 seekdb 技术作用和 Qoder 开发过程。
> 必须：静态站点（纯 HTML/CSS/JS，无构建、无 CDN 外链），未登录可访问；移动端可用。
> 放置目录：`D:\OceanBase_seekdb\qoder_work\site\`（index.html + assets/），后续通过 Qoder Sites 发布。

## 一、评审会检查的硬性内容（必须都有）

1. **项目简介**：一句话讲清是什么、给谁用。
2. **解决的问题**：具体痛点，不要空话。
3. **核心功能**：检索 / 资料导入 / 检索即复习 / 技术证据面板。
4. **演示**：截图（先放占位图，后续替换真实截图）+ 一段演示视频或 GIF 的位置。
5. **代码仓库链接**：`https://github.com/closer2005/powercontext2026/tree/2026-competition-ecosystem/qoder`（先按此放，若调整我再改）。
6. **体验入口**：本地运行地址 `http://localhost:8000`（评审复现后使用）。
7. **运行说明**：环境要求（Docker）、`docker compose up -d --build`、打开 `http://localhost:8000`、载入示例数据。
8. **验证样例**：至少一组"初始数据 → 输入 → 预期结果 → seekdb 证据"的可执行样例（和 docs/VERIFY.md 一致）。
9. **Qoder 开发记录**：时间线 + Qoder 做的工作（需求拆解/编码/调试/发布），放截图位置（后续替换），并有 Qoder 账号 UID 展示位置。
10. **seekdb 技术结合**：说明 seekdb 在项目里的实际作用：向量检索 + 全文检索 + 结构化过滤 → RRF 融合；复习进度/检索日志结构化存储；给出可核对证据（检索日志、collection 统计）。
11. 页脚：参赛信息（2026 OceanBase 数据库大赛 · Qoder 赛题）、免责/材料说明。

## 二、建议页面结构（单页滚动 + 顶部锚点导航）

1. **Hero**
   - 标题：**CiteSeek 知源**
   - 副标题：可溯源的笔记混合检索助手 —— 用一句话找回笔记里的那句话，并告诉你它出自哪里。
   - 标签：`Qoder 开发` `seekdb 混合检索` `学习提效`
   - 两个按钮：`查看演示`（滚到演示区）/ `代码仓库`（GitHub 链接）
   - 右侧：产品截图（占位）
2. **痛点（Problem）**：3 张卡片，配 1 句场景文案。
3. **功能（Features）**：4 个功能卡片，每个配截图占位。
4. **演示（Demo）**：大截图 + 视频/GIF 占位框 + 一段"输入问题 → 返回带出处结果"的对话式示例。
5. **技术（Under the hood）**：架构图（用 CSS/SVG 画，不要外链图片）、seekdb 的三个职责、RRF 融合流程、embedding 模型说明、降级策略。
6. **技术证据（Evidence）**：检索日志表格（真实数据，后续替换：query / 耗时 / 结果数 / 向量+全文标记）、collection 统计卡片、可复现的 SQL/命令。
7. **Qoder 开发记录（Build with Qoder）**：时间线 5-7 个节点（需求拆解 → 数据层 → 检索 API → 前端 → 测试 → 修复 → 发布），每节点一句话 + 截图占位；展示 Qoder 账号 UID 位置（`UID: <待填>`）。
8. **运行说明（Run it）**：命令块 + 预期输出。
9. **验证样例（Verify）**：编号步骤 + 预期结果 + 技术证据。
10. **页脚**：仓库、许可、参赛信息。

## 三、视觉与文案要求

- 浅色主题：背景 `#f8fafc`，主色 `#0f766e`（teal），强调色 `#f59e0b`，正文 `#0f172a`，次要文字 `#475569`。
- 卡片：白底、圆角 14px、细边框 `#e2e8f0`、hover 轻微上移。
- 字体：`system-ui, -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif`。
- 文案：中文、简洁、可信，**不夸大**（不要出现"第一""最强"），数字必须有来源或标注"示例"。
- 所有截图区域用带说明文字的占位块（灰底 + 说明），命名清楚（如 `assets/search.png`），后续我替换真实截图。
- 无外部字体/图标/JS 依赖；图标用内联 SVG。
- 页面加载无需网络（除跳转 GitHub 链接）。
- `assets/` 下预留：`demo-search.png`、`demo-review.png`、`demo-stats.png`、`dev-record-1.png`、`dev-record-2.png`、`dev-record-3.png`、`demo.gif`。

## 四、额外要求

- `site/README.md` 写：如何本地预览（python -m http.server）、如何部署到 Qoder Sites、需要替换的占位资源清单。
- 无障碍：图片有 alt（占位块用 `<figure>` + `<figcaption>`），对比度足够。
- 页面标题：`CiteSeek 知源 · 用 Qoder + seekdb 打造的笔记混合检索助手`。
- SEO/meta：description、og:title/description（无外链图片）。
- 不要写真实密钥、邮箱、手机号。