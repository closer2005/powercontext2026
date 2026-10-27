/* CiteSeek 知源 · 作品展示站交互（原生 JS，无任何依赖） */
(function () {
  "use strict";

  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var header = document.querySelector(".site-header");
  var toggle = document.querySelector(".nav-toggle");
  var nav = document.getElementById("site-nav");

  /* ---------- 1. 移动端导航折叠 ---------- */
  function navOpen(open) {
    if (!toggle || !nav) return;
    nav.classList.toggle("is-open", open);
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
  }
  if (toggle && nav) {
    navOpen(false);
    toggle.addEventListener("click", function () {
      navOpen(toggle.getAttribute("aria-expanded") !== "true");
    });
    nav.addEventListener("click", function (e) {
      if (e.target.closest("a")) navOpen(false);
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && toggle.getAttribute("aria-expanded") === "true") {
        navOpen(false);
        toggle.focus();
      }
    });
    document.addEventListener("click", function (e) {
      if (!header || header.contains(e.target)) return;
      navOpen(false);
    });
    window.addEventListener("resize", function () {
      if (window.innerWidth > 860) navOpen(false);
    });
  }

  /* ---------- 2. 平滑滚动（尊重减少动效偏好） ---------- */
  function offsetTop(el) {
    var fixed = window.innerWidth > 0 ? 64 : 0;
    return el.getBoundingClientRect().top + window.pageYOffset - fixed - 12;
  }
  function scrollToTarget(target) {
    var top = Math.max(0, offsetTop(target));
    window.scrollTo({ top: top, behavior: reduceMotion ? "auto" : "smooth" });
    if (!target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
    window.setTimeout(function () {
      target.focus({ preventScroll: true });
    }, reduceMotion ? 0 : 420);
  }
  document.addEventListener("click", function (e) {
    var a = e.target.closest('a[href^="#"]');
    if (!a) return;
    var id = a.getAttribute("href");
    if (!id || id === "#") return;
    var target = document.querySelector(id);
    if (!target) return;
    e.preventDefault();
    scrollToTarget(target);
    if (window.history && window.history.replaceState) {
      window.history.replaceState(null, "", id);
    }
  });

  /* ---------- 3. 导航高亮当前区块 ---------- */
  var navAnchors = [].slice.call(document.querySelectorAll(".nav-links a[href^='#']"));
  var sections = navAnchors
    .map(function (a) { return document.querySelector(a.getAttribute("href")); })
    .filter(Boolean);

  if ("IntersectionObserver" in window && sections.length) {
    var io = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          navAnchors.forEach(function (a) {
            var on = a.getAttribute("href") === "#" + entry.target.id;
            if (on) a.setAttribute("aria-current", "true");
            else a.removeAttribute("aria-current");
          });
        });
      },
      { rootMargin: "-72px 0px -55% 0px", threshold: 0 }
    );
    sections.forEach(function (s) { io.observe(s); });
  }

  /* ---------- 4. 占位图交互：点击提示待替换文件名 ---------- */
  var toast = document.getElementById("site-toast");
  var toastTimer = null;
  function showToast(text) {
    if (!toast) return;
    toast.textContent = text;
    toast.classList.add("is-on");
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(function () {
      toast.classList.remove("is-on");
    }, 2800);
  }
  [].slice.call(document.querySelectorAll(".ph-frame[data-file]")).forEach(function (frame) {
    frame.addEventListener("click", function () {
      var file = frame.getAttribute("data-file");
      showToast("占位图：" + file + " · 替换 assets/ 下同名文件后刷新即可");
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(file).catch(function () {});
      }
    });
  });

  /* ---------- 5. 细节：当前年份 ---------- */
  var yearEls = document.querySelectorAll("[data-year]");
  var year = String(new Date().getFullYear());
  [].slice.call(yearEls).forEach(function (el) { el.textContent = year; });
})();