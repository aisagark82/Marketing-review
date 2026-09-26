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
};

export const ACTIVE_RUN = new Set(["queued", "running"]);
