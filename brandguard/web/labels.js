// Display names and pill colours shared across screens.

export const READINESS = {
  needs_preflight: { text: "Pre-flight needed", cls: "warn" },
  stale: { text: "Re-check needed", cls: "warn" },
  blocked: { text: "Blocked", cls: "bad" },
  needs_ack: { text: "Awaiting acknowledgement", cls: "warn" },
  ready: { text: "Ready to crawl", cls: "ok" },
};

export const RUN_KINDS = {
  selftest: "Self-test",
  preflight: "Pre-flight check",
  crawl: "Crawl",
  evaluate: "Re-evaluation",
};

export const ACTIVE_RUN = new Set(["queued", "running"]);

export const RUN_STATUS_CLASS = {
  queued: "",
  running: "warn",
  completed: "ok",
  failed: "bad",
  cancelled: "",
  interrupted: "bad",
  blocked: "bad",
};

export const CRAWLERS = {
  crawlee: {
    label: "Crawlee",
    about: "Crawling framework with its own request queue. More setup, more control.",
  },
  crawl4ai: {
    label: "Crawl4AI",
    about: "AI-oriented crawler. Less code; BrandGuard runs its browser with plain settings.",
  },
};

export const SKIP_REASONS = {
  subdomain: "Other subdomain",
  third_party: "Other website",
  robots: "Disallowed by robots.txt",
  excluded: "Matches a skip pattern",
  not_included: "Outside the include patterns",
  page_limit: "Beyond the page limit",
  not_http: "Not a web link",
  redirected_subdomain: "Redirects to another subdomain",
  redirected_third_party: "Redirects to another website",
};

export const VISIBILITY = {
  visible: { text: "Visible", cls: "ok" },
  hidden: { text: "Hidden", cls: "warn" },
  metadata: { text: "Metadata", cls: "" },
  spoken: { text: "Spoken", cls: "" },
};

export const FINDING_KINDS = {
  casing: "Wrong letter case",
  disallowed: "Known misspelling",
  split: "Name split in two",
  near_miss: "Possible misspelling",
  wrong_market_form: "Another market's name",
};

export const FINDING_STATUS = {
  violation: { text: "Violation", cls: "bad" },
  ambiguous: { text: "To review", cls: "warn" },
};

export const CHANGE = {
  new: { text: "New", cls: "bad" },
  persisting: { text: "Still there", cls: "" },
};

const SOURCES = {
  text: "Page text", heading: "Heading", link: "Link text", button: "Button",
  form_label: "Form label", form_option: "Form option", svg_text: "SVG text",
  css_content: "CSS-generated text", noscript: "No-JavaScript text", hidden_input: "Hidden form value",
  title: "Page title", json_ld: "Structured data (JSON-LD)",
  "attr:alt": "Image alt text", "attr:title": "Tooltip (title)", "attr:aria-label": "Accessibility label",
  "attr:aria-description": "Accessibility description", "attr:placeholder": "Placeholder",
  pdf_text: "PDF text", pdf_bookmark: "PDF bookmark", pasted: "Pasted text",
};

export function sourceLabel(source) {
  if (SOURCES[source]) return SOURCES[source];
  if (source.startsWith("meta:")) return `Meta tag ${source.slice(5)}`;
  if (source.startsWith("pdf_meta:")) return `PDF ${source.slice(9)}`;
  return source;
}

export const ASSET_KINDS = { page: "Web pages", pdf: "PDFs" };
