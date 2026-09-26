import { api, formatTime } from "../api.js";
import { CRAWLERS, READINESS } from "../labels.js";
import { ComplianceSummary } from "./compliance.js";

const { ref, computed, onMounted } = Vue;

// Rows of the crawler comparison: [label, key, lower-is-better?]
const COMPARE_ROWS = [
  ["Pages crawled", "pages_ok", false],
  ["Pages failed", "pages_failed", true],
  ["Pages refused (blocked)", "pages_blocked", true],
  ["Files found", "files_found", false],
  ["PDFs read", "pdfs_read", false],
  ["Visible text segments", "segments_visible", false],
  ["Hidden text segments", "segments_hidden", false],
  ["Metadata segments", "segments_metadata", false],
  ["Violations found", "violations", null],
  ["To review", "to_review", null],
  ["Compliance score", "score", null],
  ["Time for pages (s)", "pages_runtime_s", true],
  ["Total time incl. PDFs and checks (s)", "runtime_s", true],
  ["Peak memory (MB)", "peak_rss_mb", true],
  ["CPU time (s)", "cpu_s", true],
  ["Errors", "errors", true],
];

export default {
  props: { system: Object, param: String },
  components: { ComplianceSummary },
  setup() {
    const sites = ref([]);
    const latest = ref(null);
    const comparison = ref(null);
    onMounted(async () => {
      try {
        [sites.value, latest.value] = await Promise.all([api.get("/sites"), api.get("/compliance")]);
        if (latest.value) comparison.value = await api.get(`/sites/${latest.value.run.site_id}/comparison`);
      } catch {
        sites.value = sites.value || [];
      }
    });
    const crawlers = computed(() => Object.keys(comparison.value?.crawlers || {}));
    // Mark the better value when both crawlers ran (only where "better" is clear-cut).
    const better = (key, lowerIsBetter) => {
      if (lowerIsBetter === null || crawlers.value.length !== 2) return null;
      const [a, b] = crawlers.value.map((c) => comparison.value.crawlers[c][key]);
      if (a === b || a == null || b == null) return null;
      return (lowerIsBetter ? a < b : a > b) ? crawlers.value[0] : crawlers.value[1];
    };
    return { formatTime, sites, latest, comparison, crawlers, better, READINESS, CRAWLERS, COMPARE_ROWS };
  },
  template: `
    <div v-if="!system" class="muted">Loading…</div>
    <template v-else>
      <div v-if="!system.worker.online" class="banner">
        The background worker is not running. Start the app with <code>brandguard start</code>,
        which launches both the web server and the worker.
      </div>
      <template v-if="latest">
        <div class="title-row">
          <h2 class="page-title">{{ latest.run.site_name }}</h2>
          <span class="muted">latest crawl <a :href="'#/runs/' + latest.run.id">#{{ latest.run.id }}</a>
            with {{ CRAWLERS[latest.run.crawler]?.label }} · {{ formatTime(latest.run.finished_at) }}</span>
        </div>
        <ComplianceSummary :c="latest" />
        <div class="toolbar section">
          <a class="button primary" href="#/findings">Review findings</a>
          <a class="button" href="#/compliance">Compliance dashboard</a>
        </div>

        <div class="card section" v-if="comparison">
          <h2>Crawlee vs Crawl4AI</h2>
          <p class="muted small" v-if="crawlers.length < 2">
            Crawl {{ latest.run.site_name }} with the other crawler too (Sites → Crawl) to compare them side by side.
          </p>
          <div class="table-wrap">
            <table class="compare">
              <thead><tr><th></th><th v-for="c in crawlers" :key="c">
                {{ CRAWLERS[c].label }} {{ comparison.crawlers[c].version }}
                <div class="muted small"><a :href="'#/runs/' + comparison.crawlers[c].run_id">crawl #{{ comparison.crawlers[c].run_id }}</a></div>
              </th></tr></thead>
              <tbody><tr v-for="[label, key, lower] in COMPARE_ROWS" :key="key">
                <th>{{ label }}</th>
                <td v-for="c in crawlers" :key="c" class="num">
                  {{ comparison.crawlers[c][key] ?? '—' }}
                  <span v-if="better(key, lower) === c" class="pill ok">better</span>
                </td>
              </tr></tbody>
            </table>
          </div>
          <template v-if="crawlers.length === 2">
            <div class="grid-2 section">
              <div v-for="c in crawlers" :key="c">
                <div class="label">Pages only {{ CRAWLERS[c].label }} reached ({{ comparison.only_in[c].length }})</div>
                <ul class="plain small mono"><li v-for="u in comparison.only_in[c]" :key="u">{{ u }}</li></ul>
              </div>
            </div>
          </template>
        </div>
      </template>
      <div v-else class="card section">
        <h2>Getting started</h2>
        <p class="muted">
          Open <a href="#/sites/1">pfizer.com</a>, run the pre-flight check, acknowledge it, then crawl
          it from the Crawl tab. Results appear here when the crawl finishes.
        </p>
      </div>

      <div class="cards section">
        <div class="card">
          <div class="label">Web server</div>
          <div class="value"><span class="pill ok">Running</span></div>
        </div>
        <div class="card">
          <div class="label">Background worker</div>
          <div class="value">
            <span class="pill" :class="system.worker.online ? 'ok' : 'warn'">
              {{ system.worker.online ? 'Online' : 'Offline' }}
            </span>
          </div>
          <div class="muted">Last seen: {{ formatTime(system.worker.last_seen) }}</div>
        </div>
        <div class="card">
          <div class="label">Version</div>
          <div class="value">{{ system.version }}</div>
          <div class="muted">Python {{ system.python }}</div>
        </div>
      </div>

      <div class="card section">
        <h2>Sites</h2>
        <table>
          <tbody>
            <tr v-for="s in sites" :key="s.id">
              <td><a :href="'#/sites/' + s.id">{{ s.name }}</a></td>
              <td class="muted">{{ s.start_urls[0] }}</td>
              <td><span class="pill" :class="READINESS[s.readiness].cls">{{ READINESS[s.readiness].text }}</span></td>
            </tr>
            <tr v-if="!sites.length"><td class="muted">No sites configured.</td></tr>
          </tbody>
        </table>
      </div>

      <div class="card section">
        <h2>Where your data lives</h2>
        <table>
          <tbody>
            <tr><th>Home folder</th><td>{{ system.home }}</td></tr>
            <tr><th>Database</th><td>{{ system.db_file }}</td></tr>
            <tr><th>Downloaded files</th><td>{{ system.data_dir }}</td></tr>
          </tbody>
        </table>
      </div>


    </template>
  `,
};
