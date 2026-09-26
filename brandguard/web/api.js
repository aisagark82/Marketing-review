// Small fetch wrapper for the BrandGuard API.

async function request(method, path, body) {
  const response = await fetch(`/api${path}`, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = response.status === 204 ? null : await response.json();
  if (!response.ok) {
    const detail = Array.isArray(data?.detail)
      ? data.detail.map((d) => d.msg.replace(/^Value error, /, "")).join("; ")
      : data?.detail || response.statusText;
    throw new Error(detail);
  }
  return data;
}

export const api = {
  get: (path) => request("GET", path),
  post: (path, body) => request("POST", path, body),
  put: (path, body) => request("PUT", path, body),
  // Server-Sent Events for one run; returns the EventSource so callers can close it.
  watchRun(runId, onRun) {
    const source = new EventSource(`/api/runs/${runId}/events`);
    source.addEventListener("run", (event) => onRun(JSON.parse(event.data)));
    source.onerror = () => source.close();
    return source;
  },
};

export function formatTime(iso) {
  return iso ? new Date(iso).toLocaleString() : "—";
}
