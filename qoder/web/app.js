/* CiteSeek 知源 · 前端逻辑 */
(function () {
  "use strict";

  // ─── 工具函数 ───
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  function toast(msg, isError) {
    const el = $("#toast");
    el.textContent = msg;
    el.className = "toast is-on" + (isError ? " error" : "");
    clearTimeout(el._timer);
    el._timer = setTimeout(() => { el.className = "toast"; }, 4000);
  }

  async function apiFetch(path, opts) {
    try {
      const res = await fetch(path, opts);
      if (!res.ok) {
        let detail = "";
        try {
          const j = await res.json();
          detail = j.detail || JSON.stringify(j);
        } catch (_) {
          detail = await res.text();
        }
        throw new Error(detail || ("HTTP " + res.status));
      }
      return await res.json();
    } catch (e) {
      if (e.name === "TypeError" && e.message === "Failed to fetch") {
        throw new Error("网络错误：无法连接后端服务");
      }
      throw e;
    }
  }

  function escapeHtml(str) {
    const d = document.createElement("div");
    d.textContent = str;
    return d.innerHTML;
  }

  function highlightText(text, query) {
    if (!query || !text) return escapeHtml(text || "");
    const escaped = escapeHtml(text);
    const q = query.trim();
    if (q.length < 2) return escaped;
    const substrs = [];
    for (let i = 0; i < q.length; i++) {
      for (let len = 2; len <= q.length - i; len++) {
        substrs.push(q.substring(i, i + len));
      }
    }
    substrs.sort((a, b) => b.length - a.length);
    const unique = [...new Set(substrs)].filter(s => s.length >= 2);
    if (!unique.length) return escaped;
    const pattern = unique.map(s => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|");
    const re = new RegExp("(" + pattern + ")", "gi");
    return escaped.replace(re, "<mark>$1</mark>");
  }

  // ─── Tab 切换 ───
  function switchView(name) {
    $$(".tab-btn").forEach((b) => b.setAttribute("aria-selected", b.dataset.view === name));
    $$(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + name));
    if (name === "library") loadLibrary();
    if (name === "review") loadReview();
  }

  $$(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => switchView(btn.dataset.view));
  });

  // ─── 技术面板 ───
  const techToggle = $("#tech-toggle");
  const techPanel = $("#tech-panel");
  techToggle.addEventListener("click", () => {
    const collapsed = techPanel.classList.toggle("collapsed");
    techToggle.setAttribute("aria-expanded", !collapsed);
    techToggle.querySelector("span").textContent = collapsed ? "▲" : "▼";
  });

  async function loadTechPanel() {
    try {
      const health = await apiFetch("/api/health");
      const h = health.seekdb || {};
      const e = health.embed || {};
      $("#tech-health").innerHTML =
        '<h4>系统状态</h4>' +
        techRow("seekdb", h.connected ? "已连接" : "未连接", h.connected ? "ok" : "err") +
        techRow("数据库", escapeHtml(h.database || "-")) +
        techRow("Collection", escapeHtml(h.collection || "-")) +
        techRow("向量数", String(h.count || 0)) +
        techRow("嵌入模式", escapeHtml(e.mode || "-")) +
        techRow("维度", String(e.dim || "-")) +
        techRow("降级", e.degraded ? "是" : "否", e.degraded ? "warn" : "ok");
    } catch (e) {
      $("#tech-health").innerHTML = '<h4>系统状态</h4><div class="tech-row"><span class="value err">加载失败</span></div>';
    }

    try {
      const stats = await apiFetch("/api/stats");
      $("#tech-stats").innerHTML =
        '<h4>Collection 统计</h4>' +
        techRow("笔记数", String(stats.notes || 0)) +
        techRow("Chunk 数", String(stats.chunks || 0)) +
        techRow("复习条目", String(stats.review_items || 0)) +
        techRow("今日待复习", String(stats.review_due || 0)) +
        techRow("检索次数", String(stats.searches || 0)) +
        techRow("平均耗时", (stats.avg_latency_ms || 0) + " ms");
    } catch (e) {
      $("#tech-stats").innerHTML = '<h4>统计</h4><div class="tech-row"><span class="value err">加载失败</span></div>';
    }

    try {
      const logs = await apiFetch("/api/logs/search?limit=5");
      const items = (logs.items || []);
      if (!items.length) {
        $("#tech-logs").innerHTML = '<h4>最近检索日志</h4><div style="font-size:.78rem;color:var(--ink3)">暂无记录</div>';
        return;
      }
      let html = '<h4>最近检索日志</h4><table class="log-table"><thead><tr>' +
        '<th>查询</th><th>耗时</th><th>结果</th><th>向量</th><th>全文</th></tr></thead><tbody>';
      items.forEach((it) => {
        html += '<tr>' +
          '<td>' + escapeHtml((it.query || "").substring(0, 20)) + '</td>' +
          '<td>' + (it.took_ms || 0) + 'ms</td>' +
          '<td>' + (it.result_count || 0) + '</td>' +
          '<td>' + (it.used_vector ? '✓' : '-') + '</td>' +
          '<td>' + (it.used_fulltext ? '✓' : '-') + '</td></tr>';
      });
      html += '</tbody></table>';
      $("#tech-logs").innerHTML = html;
    } catch (e) {
      $("#tech-logs").innerHTML = '<h4>检索日志</h4><div class="tech-row"><span class="value err">加载失败</span></div>';
    }
  }

  function techRow(label, value, cls) {
    return '<div class="tech-row"><span class="label">' + label +
      '</span><span class="value ' + (cls || "") + '">' + value + '</span></div>';
  }

  // ─── 检索视图 ───
  const searchInput = $("#search-input");
  const searchBtn = $("#search-btn");
  const searchResults = $("#search-results");
  const searchEmpty = $("#search-empty");
  const searchStatus = $("#search-status");

  async function loadCourseOptions() {
    try {
      const data = await apiFetch("/api/notes?limit=1000");
      const courses = new Set();
      const topics = new Set();
      (data.notes || []).forEach((n) => {
        if (n.course) courses.add(n.course);
        if (n.topic) topics.add(n.topic);
      });
      fillSelect("#filter-course", courses);
      fillSelect("#filter-topic", topics);
      fillSelect("#lib-filter-course", courses);
    } catch (_) {}
  }

  function fillSelect(sel, items) {
    const el = $(sel);
    const first = el.options[0].outerHTML;
    el.innerHTML = first;
    [...items].sort().forEach((v) => {
      const opt = document.createElement("option");
      opt.value = v;
      opt.textContent = v;
      el.appendChild(opt);
    });
  }

  async function doSearch() {
    const query = searchInput.value.trim();
    if (!query) { toast("请输入搜索内容", true); return; }

    searchBtn.disabled = true;
    searchEmpty.style.display = "none";
    searchResults.innerHTML = '<div class="loading"><span class="spinner"></span> 检索中…</div>';
    searchStatus.textContent = "";

    const body = {
      query: query,
      course: $("#filter-course").value,
      topic: $("#filter-topic").value,
      k: parseInt($("#filter-k").value, 10) || 8,
      mode: "hybrid",
    };

    try {
      const data = await apiFetch("/api/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      renderSearchResults(data, query);
      loadTechPanel();
    } catch (e) {
      searchResults.innerHTML = '';
      toast("检索失败：" + e.message, true);
    } finally {
      searchBtn.disabled = false;
    }
  }

  function renderSearchResults(data, query) {
    const results = data.results || [];
    const dbg = data.debug || {};

    let metaHtml = '<div class="search-meta">';
    metaHtml += '<span>耗时 <strong>' + (data.took_ms || 0) + ' ms</strong></span>';
    metaHtml += '<span>模式 <strong>' + escapeHtml(data.mode || "hybrid") + '</strong></span>';
    metaHtml += '<span>命中 <strong>' + results.length + '</strong> 条</span>';
    if (dbg.knn_hits != null) metaHtml += '<span>向量 <strong>' + dbg.knn_hits + '</strong></span>';
    if (dbg.fulltext_hits != null) metaHtml += '<span>全文 <strong>' + dbg.fulltext_hits + '</strong></span>';
    if (dbg.degraded) metaHtml += '<span class="badge badge-fulltext">降级模式</span>';
    metaHtml += '</div>';

    if (!results.length) {
      searchResults.innerHTML = metaHtml +
        '<div class="hint-box">未找到相关结果。建议换个说法或放宽课程/主题筛选条件。</div>';
      searchStatus.textContent = "";
      return;
    }

    searchStatus.innerHTML = metaHtml;

    const topScore = results[0].score || 0.001;
    let html = "";
    results.forEach((r) => {
      const pct = topScore > 0 ? Math.min(100, Math.round((r.score / topScore) * 100)) : 0;
      const badges = (r.matched_by || []).map((m) =>
        '<span class="badge badge-' + (m === "vector" ? "vector" : "fulltext") + '">' +
        (m === "vector" ? "向量" : "全文") + '</span>'
      ).join("");

      html += '<div class="card result-card">' +
        '<div class="result-header">' +
          '<span class="result-title">' + escapeHtml(r.title || "无标题") + '</span>' +
          '<span class="result-tags">' +
            (r.course ? '<span class="tag tag-course">' + escapeHtml(r.course) + '</span>' : '') +
            (r.topic ? '<span class="tag tag-topic">' + escapeHtml(r.topic) + '</span>' : '') +
          '</span>' +
          badges +
        '</div>' +
        '<div class="result-text">' + highlightText(r.text || "", query) + '</div>' +
        '<div class="result-footer">' +
          '<div class="score-bar-wrap">' +
            '<div class="score-bar"><div class="score-bar-fill" style="width:' + pct + '%"></div></div>' +
            '<span class="score-val">' + (r.score != null ? r.score.toFixed(4) : "-") + '</span>' +
          '</div>' +
          (r.seq != null ? '<span>第 ' + (r.seq + 1) + ' 段</span>' : '') +
          (r.distance != null ? '<span>距离 ' + r.distance.toFixed(4) + '</span>' : '') +
          '<button class="btn btn-sm btn-ghost review-add-btn" data-chunk-id="' + escapeHtml(r.chunk_id) + '">加入复习</button>' +
        '</div>' +
      '</div>';
    });

    searchResults.innerHTML = html;

    searchResults.querySelectorAll(".review-add-btn").forEach((btn) => {
      btn.addEventListener("click", () => addReview(btn.dataset.chunkId, btn));
    });
  }

  searchBtn.addEventListener("click", doSearch);
  searchInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") doSearch();
  });

  async function addReview(chunkId, btn) {
    try {
      await apiFetch("/api/review/" + encodeURIComponent(chunkId) + "/add", { method: "POST" });
      btn.textContent = "已加入";
      btn.disabled = true;
      toast("已加入复习队列");
    } catch (e) {
      toast("加入失败：" + e.message, true);
    }
  }

  // ─── 载入示例数据 ───
  async function seedSamples(btn) {
    const origText = btn.textContent;
    btn.disabled = true;
    btn.textContent = "导入中…";
    try {
      const data = await apiFetch("/api/import/samples", { method: "POST" });
      toast("导入完成：新增 " + data.imported + " 篇，跳过 " + data.skipped + " 篇");
      loadCourseOptions();
      loadTechPanel();
      if ($("#view-library").classList.contains("active")) loadLibrary();
    } catch (e) {
      toast("导入失败：" + e.message, true);
    } finally {
      btn.disabled = false;
      btn.textContent = origText;
    }
  }

  $("#seed-btn-search").addEventListener("click", function () { seedSamples(this); });
  $("#seed-btn-library").addEventListener("click", function () { seedSamples(this); });

  // ─── 资料库视图 ───
  async function loadLibrary() {
    try {
      const stats = await apiFetch("/api/stats");
      $("#library-stats").innerHTML =
        '<div class="stat-chip"><strong>' + (stats.notes || 0) + '</strong>笔记</div>' +
        '<div class="stat-chip"><strong>' + (stats.chunks || 0) + '</strong>chunks</div>' +
        '<div class="stat-chip"><strong>' + (stats.review_items || 0) + '</strong>复习</div>';
    } catch (_) {}

    const course = $("#lib-filter-course").value;
    try {
      const data = await apiFetch("/api/notes?limit=200&course=" + encodeURIComponent(course));
      const notes = data.notes || [];
      if (!notes.length) {
        $("#note-list").innerHTML = '<li style="padding:16px;color:var(--ink3);font-size:.88rem">暂无笔记</li>';
        return;
      }
      let html = "";
      notes.forEach((n) => {
        html += '<li class="note-item">' +
          '<div class="note-info">' +
            '<div class="note-info-title">' + escapeHtml(n.title) + '</div>' +
            '<div class="note-info-meta">' +
              escapeHtml(n.course || "") +
              (n.topic ? " · " + escapeHtml(n.topic) : "") +
              " · " + (n.chunk_count || 0) + " chunks" +
            '</div>' +
          '</div>' +
          '<button class="btn btn-sm btn-danger note-del-btn" data-id="' + escapeHtml(n.id) + '">删除</button>' +
        '</li>';
      });
      $("#note-list").innerHTML = html;
      $("#note-list").querySelectorAll(".note-del-btn").forEach((btn) => {
        btn.addEventListener("click", () => deleteNote(btn.dataset.id));
      });
    } catch (e) {
      $("#note-list").innerHTML = '<li style="padding:16px;color:#ef4444">加载失败：' + escapeHtml(e.message) + '</li>';
    }
  }

  async function deleteNote(id) {
    if (!confirm("确定删除此笔记？关联的 chunks 和复习条目也会被删除。")) return;
    try {
      await apiFetch("/api/notes/" + encodeURIComponent(id), { method: "DELETE" });
      toast("已删除");
      loadLibrary();
      loadTechPanel();
    } catch (e) {
      toast("删除失败：" + e.message, true);
    }
  }

  $("#lib-filter-course").addEventListener("change", loadLibrary);
  $("#refresh-library").addEventListener("click", loadLibrary);

  $("#import-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = {
      title: $("#imp-title").value.trim(),
      content: $("#imp-content").value,
      course: $("#imp-course").value.trim(),
      topic: $("#imp-topic").value.trim(),
      tags: $("#imp-tags").value.trim(),
      source: $("#imp-source").value.trim(),
    };
    if (!body.title || !body.content) { toast("标题和正文不能为空", true); return; }
    try {
      const res = await apiFetch("/api/notes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      toast("导入成功：" + (res.chunk_count || 0) + " 个片段");
      e.target.reset();
      loadLibrary();
      loadCourseOptions();
      loadTechPanel();
    } catch (e2) {
      toast("导入失败：" + e2.message, true);
    }
  });

  // ─── 复习视图 ───
  let reviewItems = [];
  let reviewIdx = 0;

  async function loadReview() {
    try {
      const data = await apiFetch("/api/review/due?limit=20");
      reviewItems = data.items || [];
      reviewIdx = 0;
      renderReview();
    } catch (e) {
      $("#review-area").innerHTML = '<div class="hint-box">加载失败：' + escapeHtml(e.message) + '</div>';
    }
  }

  function renderReview() {
    const area = $("#review-area");
    const empty = $("#review-empty");
    const progress = $("#review-progress");

    if (!reviewItems.length) {
      area.innerHTML = "";
      empty.style.display = "";
      progress.textContent = "";
      return;
    }
    empty.style.display = "none";

    if (reviewIdx >= reviewItems.length) {
      area.innerHTML = '<div class="empty-state"><h3>今日复习完成！</h3><p>太棒了，明天继续。</p></div>';
      progress.textContent = "";
      return;
    }

    const item = reviewItems[reviewIdx];
    progress.innerHTML = '剩余 <strong>' + (reviewItems.length - reviewIdx) + '</strong> / 共 ' + reviewItems.length + ' 条';

    area.innerHTML =
      '<div class="card review-card">' +
        '<div class="review-text">' + escapeHtml(item.text || "（无内容）") + '</div>' +
        '<div class="review-source">' +
          '出处：' + escapeHtml(item.title || "未知") +
          (item.course ? ' · ' + escapeHtml(item.course) : '') +
          ' · 已复习 ' + (item.reps || 0) + ' 次' +
        '</div>' +
        '<div class="review-buttons">' +
          '<button class="review-btn" data-grade="0" type="button">忘了</button>' +
          '<button class="review-btn" data-grade="1" type="button">模糊</button>' +
          '<button class="review-btn" data-grade="2" type="button">记住了</button>' +
          '<button class="review-btn" data-grade="3" type="button">很熟练</button>' +
        '</div>' +
      '</div>';

    area.querySelectorAll(".review-btn").forEach((btn) => {
      btn.addEventListener("click", () => answerReview(item.chunk_id, parseInt(btn.dataset.grade, 10)));
    });
  }

  async function answerReview(chunkId, grade) {
    try {
      await apiFetch("/api/review/" + encodeURIComponent(chunkId) + "/answer", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ grade: grade }),
      });
      reviewIdx++;
      renderReview();
      loadTechPanel();
    } catch (e) {
      toast("评分失败：" + e.message, true);
    }
  }

  // ─── 初始化 ───
  loadCourseOptions();
  loadTechPanel();
})();
