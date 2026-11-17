// Read the current course only when an attachment is requested or the extension is opened.
(() => {
  const clean = text => (text || "").replace(/\s+/g, " ").trim();
  const label = /^(?:교과목명|과목명|강좌명|강의명|교과목\s*명|course\s+(?:name|title))\s*[:：]?\s*$/i;
  const labelledValue = /^(?:교과목명|과목명|강좌명|강의명|course\s+(?:name|title))\s*[:：]\s*(.+)$/i;
  const acceptable = text => text.length >= 2 && text.length <= 80 &&
    !/^(?:강의자료|강의실|강의실 홈|과목명|강좌명|조선대학교|e-?class(?: system)?|공지사항|강좌 선택|과목 선택|home)$/i.test(text);

  function extract(doc) {
    const names = new Set();
    function add(value) {
      const name = clean(value);
      if (acceptable(name)) names.add(name);
    }
    for (const segment of doc.title.split(/[|｜]/)) {
      const match = clean(segment).match(labelledValue);
      if (match) add(match[1]);
    }
    for (const el of doc.querySelectorAll("meta[name='course-name'], meta[name='course-title'], [data-current-course-name], [aria-current='page'][data-course-name]")) {
      add(el.content || el.dataset.currentCourseName || el.dataset.courseName);
    }
    const selector = "#course-title, #course_name, #courseName, #subjtNm, .course-title, .course-name, .subjt_nm, .subject_name, [aria-label='강좌명'], [aria-label='과목명'], select[name='course_id'] option:checked";
    for (const el of doc.querySelectorAll(selector)) {
      if (el.getClientRects().length || el.closest("select")?.getClientRects().length) {
        add(el.innerText || el.textContent);
      }
    }
    const crumbs = doc.querySelectorAll("#breadcrumbs a[href], .breadcrumb a[href], nav[aria-label='breadcrumb' i] a[href]");
    for (const link of crumbs) {
      const url = new URL(link.href, doc.baseURI);
      if (url.origin === doc.location.origin &&
          (/^\/courses\/\d+\/?$/.test(url.pathname) ||
           (url.pathname.endsWith("/course/view.php") && /^\d+$/.test(url.searchParams.get("id") || "")))) {
        if (link.getClientRects().length) add(link.innerText);
      }
    }
    for (const el of doc.querySelectorAll("th,dt,label,strong,b,.field-label")) {
      if (!el.getClientRects().length) continue;
      const text = clean(el.textContent);
      const match = text.match(labelledValue);
      if (match) add(match[1]);
      else if (label.test(text) && el.nextElementSibling) add(el.nextElementSibling.innerText);
    }
    return names;
  }

  function snapshot() {
    const names = extract(document);
    let outer = window;
    try {
      while (outer !== outer.parent && outer.parent.location.origin === location.origin) {
        outer = outer.parent;
        for (const name of extract(outer.document)) names.add(name);
      }
    } catch { /* A cross-origin parent is outside the course page. */ }
    return {
      page: location.href,
      pageTitle: clean(document.title || outer.document.title).slice(0, 300),
      courseName: names.size === 1 ? [...names][0] : ""
    };
  }
  chrome.runtime.onMessage.addListener((message, sender, reply) => {
    if (message.type === "course-snapshot") reply(snapshot());
  });
  function click(event) {
    if (!event.isTrusted) return;
    const link = event.target.closest?.("a[href],button,[onclick],input[type=submit]");
    if (!link) return;
    const href = link.href;
    const target = href && /^https?:/i.test(href) && !href.startsWith(location.href.split("#")[0] + "#") ? href : "";
    chrome.runtime.sendMessage({type: "course-click", target, ...snapshot()}).catch(() => {});
  }
  document.addEventListener("click", click, true);
  document.addEventListener("auxclick", click, true);
})();
