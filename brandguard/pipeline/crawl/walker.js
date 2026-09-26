// BrandGuard DOM walker. Runs inside the rendered page (page.evaluate) and returns every
// piece of text with where it came from and whether a visitor can see it (design §4, §5.2).
//
// Text is grouped per "container": the nearest ancestor that is not display:inline, so
// "Welcome to <b>Pfizer</b>" stays one segment while nested blocks get their own.
() => {
  const MAX_SEGMENTS = 20000;
  const MAX_TEXT = 5000;
  const SKIP_TAGS = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "IFRAME", "OBJECT", "EMBED"]);
  const ATTRS = ["alt", "title", "aria-label", "aria-description", "placeholder"];
  const FILE_KINDS = [
    [/\.pdf$/i, "pdf"],
    [/\.(docx?|pptx?|xlsx?|odt|odp|ods|rtf)$/i, "office"],
    [/\.(jpe?g|png|gif|webp|avif|svg|bmp|tiff?)$/i, "image"],
    [/\.(mp4|webm|mov|m4v|m3u8|ogv)$/i, "video"],
    [/\.(mp3|wav|m4a|aac|oga|ogg|flac)$/i, "audio"],
    [/\.(vtt|srt)$/i, "subtitle"],
  ];

  const segments = [];
  const links = new Map();
  const resources = new Map();
  const styleCache = new Map();

  const style = (el) => {
    let s = styleCache.get(el);
    if (!s) {
      s = getComputedStyle(el);
      styleCache.set(el, s);
    }
    return s;
  };
  const clean = (text) => text.replace(/\s+/g, " ").trim().slice(0, MAX_TEXT);
  const add = (seg) => {
    if (segments.length < MAX_SEGMENTS && seg.text) segments.push(seg);
  };

  const absUrl = (value) => {
    try {
      const url = new URL(value, document.baseURI);
      return ["http:", "https:"].includes(url.protocol) ? url.href : null;
    } catch {
      return null;
    }
  };
  const fileKind = (url) => {
    const path = new URL(url).pathname;
    for (const [pattern, kind] of FILE_KINDS) if (pattern.test(path)) return kind;
    return null;
  };
  const addResource = (value, kind, tag, visible) => {
    const url = absUrl(value);
    if (!url || resources.has(url)) return;
    resources.set(url, { url, kind: kind || fileKind(url) || "other", tag, visible });
  };

  // --- selectors and geometry -------------------------------------------------------------
  const cssPath = (el) => {
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && parts.length < 12) {
      if (node.id && document.querySelectorAll(`#${CSS.escape(node.id)}`).length === 1) {
        parts.unshift(`#${CSS.escape(node.id)}`);
        break;
      }
      const tag = node.tagName.toLowerCase();
      if (tag === "html" || tag === "body") {
        parts.unshift(tag);
        break;
      }
      let index = 1;
      for (let sib = node.previousElementSibling; sib; sib = sib.previousElementSibling) {
        if (sib.tagName === node.tagName) index++;
      }
      parts.unshift(`${tag}:nth-of-type(${index})`);
      node = node.parentElement;
    }
    return parts.join(" > ");
  };
  const bbox = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) return null;
    return [
      Math.round(r.left + scrollX),
      Math.round(r.top + scrollY),
      Math.round(r.width),
      Math.round(r.height),
    ];
  };

  // --- visibility -------------------------------------------------------------------------
  const visibilityCache = new Map();
  const isVisible = (el) => {
    if (visibilityCache.has(el)) return visibilityCache.get(el);
    let visible = el.checkVisibility
      ? el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })
      : style(el).display !== "none" && style(el).visibility !== "hidden";
    if (visible) {
      const r = el.getBoundingClientRect();
      if (r.right + scrollX < 0 || r.bottom + scrollY < 0) visible = false; // pushed off-page
    }
    if (visible) {
      // "Screen-reader only" text: a tiny box that clips its content.
      for (let a = el, i = 0; a && i < 6; a = a.parentElement, i++) {
        const r = a.getBoundingClientRect();
        if (r.width <= 1 && r.height <= 1 && style(a).overflow !== "visible") {
          visible = false;
          break;
        }
      }
    }
    visibilityCache.set(el, visible);
    return visible;
  };

  // --- text grouping ----------------------------------------------------------------------
  const isContainer = (el) => {
    if (el.namespaceURI === "http://www.w3.org/2000/svg") return el.tagName.toLowerCase() === "text";
    const display = style(el).display;
    return display !== "inline" && display !== "contents";
  };
  const containerCache = new Map();
  const containerOf = (el) => {
    const start = el;
    const path = [];
    while (el && !containerCache.has(el)) {
      path.push(el);
      if (isContainer(el) || !el.parentElement) break;
      el = el.parentElement;
    }
    const found = containerCache.has(el) ? containerCache.get(el) : el || start;
    for (const p of path) containerCache.set(p, found);
    return found;
  };
  const sourceOf = (container) => {
    if (container.closest("svg")) return "svg_text";
    if (/^H[1-6]$/.test(container.tagName) || container.closest("h1,h2,h3,h4,h5,h6")) return "heading";
    if (container.closest("button,[role=button],input[type=submit],input[type=button]")) return "button";
    if (container.closest("a[href]")) return "link";
    if (container.closest("label,legend")) return "form_label";
    if (container.closest("option,select")) return "form_option";
    return "text";
  };

  const groups = new Map(); // container -> {visible: [...parts], hidden: [...parts]}
  const pendingBreak = new Set();
  const append = (container, visibility, text) => {
    let group = groups.get(container);
    if (!group) {
      group = { visible: [], hidden: [], order: groups.size };
      groups.set(container, group);
    }
    const parts = group[visibility];
    if (pendingBreak.has(container) && parts.length) parts.push(" ");
    pendingBreak.delete(container);
    parts.push(text);
  };

  // No filter callback on the TreeWalker: Chromium refuses to call back into page scripts when
  // JavaScript is disabled, so skipped subtrees are stepped over by hand instead.
  const skipSubtree = (walker) => {
    for (;;) {
      const sibling = walker.nextSibling();
      if (sibling) return sibling;
      if (!walker.parentNode()) return null;
    }
  };
  const walkRoot = (root) => {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
    for (let node = walker.currentNode; node; ) {
      if (node !== root && node.nodeType === 1 && SKIP_TAGS.has(node.tagName)) {
        node = skipSubtree(walker);
        continue;
      }
      node = visit(node, walker);
    }
  };
  // Handles one node and returns the next one in document order.
  const visit = (node, walker) => {
    if (node.nodeType === 3) {
      const parent = node.parentElement;
      if (!parent) return walker.nextNode();
      if (node.data.trim()) {
        append(containerOf(parent), isVisible(parent) ? "visible" : "hidden", node.data);
      } else if (/\s/.test(node.data)) {
        // Whitespace-only nodes still separate words.
        const group = groups.get(containerOf(parent));
        if (group) (isVisible(parent) ? group.visible : group.hidden).push(" ");
      }
      return walker.nextNode();
    }
    if (node.nodeType === 1) {
      if (node.shadowRoot) walkRoot(node.shadowRoot);
      if (node.tagName === "BR" || node.tagName === "HR") {
        pendingBreak.add(containerOf(node));
      } else if (node.parentElement && isContainer(node)) {
        pendingBreak.add(containerOf(node.parentElement)); // a block interrupts its parent's text
      }
    }
    return walker.nextNode();
  };
  walkRoot(document.body || document.documentElement);

  const ordered = [...groups.entries()].sort((a, b) => a[1].order - b[1].order);
  for (const [container, group] of ordered) {
    for (const visibility of ["visible", "hidden"]) {
      const text = clean(group[visibility].join(""));
      if (!text) continue;
      const transform = style(container).textTransform;
      add({
        text,
        source: sourceOf(container),
        visibility,
        transform: transform && transform !== "none" ? transform : null,
        locator: {
          selector: cssPath(container),
          bbox: visibility === "visible" ? bbox(container) : null,
        },
      });
    }
  }

  // --- attributes, CSS generated content, form values, resources --------------------------
  const all = [];
  const collect = (root) => {
    for (const el of root.querySelectorAll("*")) {
      all.push(el);
      if (el.shadowRoot) collect(el.shadowRoot);
    }
  };
  collect(document);

  for (const el of all) {
    const tag = el.tagName;
    if (tag === "SCRIPT" || tag === "STYLE" || tag === "TEMPLATE") continue;
    for (const name of ATTRS) {
      const value = el.getAttribute(name);
      if (value && value.trim()) {
        add({
          text: clean(value),
          source: `attr:${name}`,
          visibility: "metadata",
          transform: null,
          locator: { selector: cssPath(el), attribute: name, bbox: isVisible(el) ? bbox(el) : null },
        });
      }
    }
    if (tag === "INPUT") {
      const type = (el.getAttribute("type") || "text").toLowerCase();
      if (type === "hidden" && el.value.trim()) {
        add({ text: clean(el.value), source: "hidden_input", visibility: "hidden", transform: null,
              locator: { selector: cssPath(el) } });
      } else if (["submit", "button", "reset"].includes(type) && el.value.trim()) {
        add({ text: clean(el.value), source: "button", visibility: isVisible(el) ? "visible" : "hidden",
              transform: null, locator: { selector: cssPath(el), bbox: bbox(el) } });
      } else if (type === "image" && el.src) {
        addResource(el.src, "image", "input", isVisible(el));
      }
    }
    if (style(el).display !== "none") {
      for (const pseudo of ["::before", "::after"]) {
        const content = getComputedStyle(el, pseudo).content;
        const match = content && content.match(/^"((?:[^"\\]|\\.)*)"$/);
        if (match && match[1].trim()) {
          add({ text: clean(match[1].replace(/\\(.)/g, "$1")), source: "css_content",
                visibility: isVisible(el) ? "visible" : "hidden", transform: null,
                locator: { selector: cssPath(el), pseudo } });
        }
      }
      const bg = style(el).backgroundImage;
      if (bg && bg !== "none") {
        for (const m of bg.matchAll(/url\(["']?([^"')]+)["']?\)/g)) {
          if (!m[1].startsWith("data:")) addResource(m[1], "image", "css-background", isVisible(el));
        }
      }
    }
    if (tag === "NOSCRIPT") {
      const doc = new DOMParser().parseFromString(el.textContent || "", "text/html");
      const text = clean(doc.body ? doc.body.textContent : "");
      if (text) add({ text, source: "noscript", visibility: "hidden", transform: null,
                      locator: { selector: cssPath(el) } });
    }

    // Resources: images, media, frames, embeds.
    if (tag === "IMG") addResource(el.currentSrc || el.src, "image", "img", isVisible(el));
    if (tag === "SOURCE" && el.parentElement) {
      const parentTag = el.parentElement.tagName;
      const kind = parentTag === "VIDEO" ? "video" : parentTag === "AUDIO" ? "audio" : "image";
      addResource(el.src || (el.srcset || "").split(/\s+/)[0], kind, "source", isVisible(el.parentElement));
    }
    if (tag === "VIDEO" && el.getAttribute("src")) addResource(el.src, "video", "video", isVisible(el));
    if (tag === "AUDIO" && el.getAttribute("src")) addResource(el.src, "audio", "audio", isVisible(el));
    if (tag === "TRACK" && el.src) addResource(el.src, "subtitle", "track", false);
    if (tag === "IFRAME" && el.src) addResource(el.src, "frame", "iframe", isVisible(el));
    if ((tag === "EMBED" && el.src) || (tag === "OBJECT" && el.data)) {
      addResource(el.src || el.data, null, tag.toLowerCase(), isVisible(el));
    }
    if ((tag === "A" || tag === "AREA") && el.getAttribute("href")) {
      const url = absUrl(el.getAttribute("href"));
      if (url) {
        const kind = fileKind(url);
        if (kind) addResource(url, kind, "a", isVisible(el));
        else if (!links.has(url.split("#")[0])) links.set(url.split("#")[0], clean(el.textContent || ""));
      }
    }
  }

  // --- metadata ---------------------------------------------------------------------------
  if (document.title.trim()) {
    add({ text: clean(document.title), source: "title", visibility: "metadata", transform: null,
          locator: { selector: "head > title" } });
  }
  for (const meta of document.querySelectorAll("meta[content]")) {
    const key = (meta.getAttribute("name") || meta.getAttribute("property") || meta.getAttribute("itemprop") || "").toLowerCase();
    if (!key || /viewport|charset|robots|verification|theme-color|format-detection|csrf/.test(key)) continue;
    const value = meta.getAttribute("content");
    if (value && value.trim() && !/^https?:\/\//.test(value.trim())) {
      add({ text: clean(value), source: `meta:${key}`, visibility: "metadata", transform: null,
            locator: { selector: `meta[${meta.hasAttribute("name") ? "name" : meta.hasAttribute("property") ? "property" : "itemprop"}="${key}"]` } });
    }
  }
  const walkJson = (value, path, index) => {
    if (typeof value === "string") {
      if (value.trim() && !/^https?:\/\//.test(value.trim())) {
        add({ text: clean(value), source: "json_ld", visibility: "metadata", transform: null,
              locator: { selector: `script[type="application/ld+json"]:nth-of-type(${index + 1})`, path } });
      }
    } else if (Array.isArray(value)) {
      value.forEach((item, i) => walkJson(item, `${path}[${i}]`, index));
    } else if (value && typeof value === "object") {
      for (const [key, item] of Object.entries(value)) {
        if (!["@context", "@type", "@id"].includes(key)) walkJson(item, path ? `${path}.${key}` : key, index);
      }
    }
  };
  document.querySelectorAll('script[type="application/ld+json"]').forEach((script, index) => {
    try {
      walkJson(JSON.parse(script.textContent), "", index);
    } catch {
      /* invalid JSON-LD is ignored */
    }
  });

  const doc = document.documentElement;
  return {
    url: location.href,
    title: document.title || null,
    language: doc.getAttribute("lang") || null,
    size: [Math.max(doc.scrollWidth, document.body ? document.body.scrollWidth : 0),
           Math.max(doc.scrollHeight, document.body ? document.body.scrollHeight : 0)],
    segments,
    truncated: segments.length >= MAX_SEGMENTS,
    links: [...links.entries()].map(([url, text]) => ({ url, text })),
    resources: [...resources.values()],
  };
};
