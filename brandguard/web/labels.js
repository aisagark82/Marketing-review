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
