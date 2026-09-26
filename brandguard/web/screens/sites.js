import { api, formatTime } from "../api.js";
import { ACTIVE_RUN, READINESS } from "../labels.js";

const { ref, computed, watch, onBeforeUnmount } = Vue;

const LIST_FIELDS = ["start_urls", "allowed_domains", "include_patterns", "exclude_patterns"];
const CHECK_ICONS = { ok: "✓", info: "i", warn: "!", fail: "✕" };
const NEW_SITE = {
  name: "",
  brand_id: null,
  start_urls: [],
  allowed_domains: [],
  use_sitemap: true,
  include_patterns: [],
  exclude_patterns: [],
  max_pages: 500,
  render_js: "auto",
  expand_interactive: true,
  independent: true,
  request_interval_s: 2,
  respect_robots: true,
  stop_on_blocks: true,
};

// The form edits list fields as one-item-per-line text.
function toForm(site) {
  const form = {};
  for (const key of Object.keys(NEW_SITE)) {
    form[key] = LIST_FIELDS.includes(key) ? (site[key] || []).join("\n") : site[key];
  }
  return form;
}

function fromForm(form) {
  const payload = { ...form };
  for (const key of LIST_FIELDS) {
    payload[key] = form[key].split("\n").map((line) => line.trim()).filter(Boolean);
  }
  return payload;
}

const SiteList = {
  props: { sites: Array },
  emits: ["add"],
  setup() {
    const open = (id) => (window.location.hash = `#/sites/${id}`);
    return { READINESS, formatTime, open };
  },
  template: `
    <div class="toolbar">
      <button class="primary" @click="$emit('add')">Add site</button>
      <span class="muted">Every site needs a pre-flight check and your acknowledgement before it can be crawled.</span>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Site</th><th>Brand</th><th>Start URL</th><th>Status</th><th>Last check</th></tr></thead>
        <tbody>
          <tr v-if="!sites.length"><td colspan="5" class="muted">No sites yet.</td></tr>
          <tr v-for="s in sites" :key="s.id" class="clickable" @click="open(s.id)">
            <td><a :href="'#/sites/' + s.id">{{ s.name }}</a></td>
            <td>{{ s.brand_name }}</td>
            <td class="muted">{{ s.start_urls[0] }}</td>
            <td><span class="pill" :class="READINESS[s.readiness].cls">{{ READINESS[s.readiness].text }}</span></td>
            <td class="muted">{{ formatTime(s.preflight_at) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  `,
};

const PreflightReport = {
  props: { result: Object },
  setup() {
    return { CHECK_ICONS };
  },
  template: `
    <div class="card section">
      <h2>Checks</h2>
      <ul class="checks">
        <li v-for="c in result.checks" :key="c.id" :class="'check-' + c.status">
          <span class="check-icon" :aria-label="c.status">{{ CHECK_ICONS[c.status] }}</span>
          <div><strong>{{ c.label }}</strong><div class="muted">{{ c.detail }}</div></div>
        </li>
      </ul>
    </div>

    <div class="grid-2 section">
      <div class="card">
        <h2>robots.txt</h2>
        <p><a :href="result.robots.url" target="_blank" rel="noopener">{{ result.robots.url }}</a>
          <span class="muted"> · HTTP {{ result.robots.status_code ?? '—' }}</span></p>
        <p>Wait between requests: <strong>{{ result.effective_interval_s }} s</strong>
          <span v-if="result.robots.crawl_delay_s" class="muted"> (site asks for {{ result.robots.crawl_delay_s }} s)</span></p>
        <template v-if="result.robots.groups.length">
          <div class="label">Rules that apply to BrandGuard</div>
          <pre>{{ result.robots.groups.map(g =>
            g.user_agents.map(a => 'User-agent: ' + a).join('\\n') + '\\n' +
            g.rules.map(r => r[0] + ': ' + r[1]).join('\\n')).join('\\n\\n') }}</pre>
        </template>
        <p v-else-if="result.robots.found" class="muted">No rules apply to BrandGuard.</p>
        <details v-if="result.robots.raw">
          <summary>Full robots.txt</summary>
          <pre>{{ result.robots.raw }}</pre>
        </details>
      </div>

      <div class="card">
        <h2>Terms of use</h2>
        <ul v-if="result.terms_links.length" class="plain">
          <li v-for="t in result.terms_links" :key="t.url">
            <a :href="t.url" target="_blank" rel="noopener">{{ t.text }}</a>
          </li>
        </ul>
        <p v-else class="muted">No terms link was found automatically. Look for one on the site yourself.</p>
        <p class="muted">Read these before acknowledging. If they prohibit automated access, don't crawl the site.</p>
      </div>

      <div class="card" v-if="result.start_page">
        <h2>Start page</h2>
        <table class="kv"><tbody>
          <tr><th>Requested</th><td>{{ result.start_page.url }}</td></tr>
          <tr v-if="result.start_page.redirects.length"><th>Ended at</th><td>{{ result.start_page.final_url }}</td></tr>
          <tr><th>HTTP status</th><td>{{ result.start_page.status_code ?? result.start_page.error }}</td></tr>
          <tr v-if="result.start_page.title"><th>Title</th><td>{{ result.start_page.title }}</td></tr>
          <tr><th>In-scope links</th><td>{{ result.start_page.in_scope_links }}</td></tr>
          <tr v-if="result.start_page.bot_protection"><th>Bot protection</th><td class="error-text">{{ result.start_page.bot_protection }}</td></tr>
        </tbody></table>
      </div>

      <div class="card">
        <h2>Sitemap</h2>
        <ul v-if="result.sitemap.checked.length" class="plain">
          <li v-for="s in result.sitemap.checked" :key="s.url">
            <span class="mono">{{ s.url }}</span>
            <span class="muted"> · {{ s.error || (s.type === 'sitemapindex' ? s.entries + ' sitemap files' : s.entries + ' URLs') }}</span>
          </li>
        </ul>
        <p v-else class="muted">Not checked.</p>
        <template v-if="result.sitemap.sample_urls.length">
          <div class="label">Sample in-scope pages</div>
          <ul class="plain mono small"><li v-for="u in result.sitemap.sample_urls" :key="u">{{ u }}</li></ul>
        </template>
      </div>
    </div>

    <p class="muted small section">Crawler identity sent to the site: <span class="mono">{{ result.user_agent }}</span></p>
  `,
};

const SiteForm = {
  props: { site: Object, brands: Array },
  emits: ["saved"],
  setup(props, { emit }) {
    const form = ref(toForm(props.site));
    const saving = ref(false);
    const error = ref(null);
    watch(() => props.site, (site) => (form.value = toForm(site)));

    const save = async () => {
      saving.value = true;
      error.value = null;
      try {
        const payload = fromForm(form.value);
        const saved = props.site.id
          ? await api.put(`/sites/${props.site.id}`, payload)
          : await api.post("/sites", payload);
        emit("saved", saved);
      } catch (e) {
        error.value = e.message;
      } finally {
        saving.value = false;
      }
    };
    return { form, saving, error, save };
  },
  template: `
    <form class="form wide" @submit.prevent="save">
      <div class="grid-2">
        <div class="field">
          <label for="site-name">Name</label>
          <input id="site-name" type="text" v-model="form.name" required maxlength="100" />
        </div>
        <div class="field">
          <label for="site-brand">Brand</label>
          <select id="site-brand" v-model="form.brand_id" required>
            <option v-for="b in brands" :key="b.id" :value="b.id">{{ b.name }}</option>
          </select>
        </div>
      </div>

      <fieldset>
        <legend>Scope</legend>
        <div class="field">
          <label for="start-urls">Start URLs</label>
          <textarea id="start-urls" v-model="form.start_urls" rows="2" required placeholder="https://www.example.com/"></textarea>
          <div class="hint">One per line. Each must be on an allowed domain.</div>
        </div>
        <div class="field">
          <label for="domains">Allowed domains</label>
          <textarea id="domains" v-model="form.allowed_domains" rows="2" required placeholder="www.example.com"></textarea>
          <div class="hint">Exact host names, one per line. Other subdomains are skipped and logged.</div>
        </div>
        <div class="grid-2">
          <div class="field">
            <label for="include">Only crawl URLs matching (optional)</label>
            <textarea id="include" v-model="form.include_patterns" rows="2" placeholder="^https://www.example.com/en/"></textarea>
          </div>
          <div class="field">
            <label for="exclude">Skip URLs matching (optional)</label>
            <textarea id="exclude" v-model="form.exclude_patterns" rows="2" placeholder="\\?page="></textarea>
          </div>
        </div>
        <div class="hint">Regular expressions, one per line.</div>
        <div class="grid-2">
          <div class="field">
            <label for="max-pages">Page limit</label>
            <input id="max-pages" type="number" min="1" max="100000" v-model.number="form.max_pages" required />
          </div>
          <div class="field">
            <label for="render-js">Render JavaScript</label>
            <select id="render-js" v-model="form.render_js">
              <option value="auto">Automatically, when a page needs it</option>
              <option value="always">Always</option>
              <option value="never">Never</option>
            </select>
          </div>
        </div>
        <label class="check"><input type="checkbox" v-model="form.use_sitemap" /> Use the site's sitemap to find pages</label>
        <label class="check"><input type="checkbox" v-model="form.expand_interactive" /> Open accordions, tabs and carousels to read hidden content</label>
      </fieldset>

      <fieldset>
        <legend>Crawl politeness</legend>
        <label class="check"><input type="checkbox" v-model="form.independent" />
          Independent test (not done for the site owner): always respect robots.txt and wait at least 1 s between requests</label>
        <div class="field">
          <label for="interval">Seconds between requests</label>
          <input id="interval" type="number" step="0.5" :min="form.independent ? 1 : 0.5" max="60"
                 v-model.number="form.request_interval_s" required />
          <div class="hint">If robots.txt asks for a longer Crawl-delay, the longer wait is used.</div>
        </div>
        <label class="check"><input type="checkbox" v-model="form.respect_robots" :disabled="form.independent" />
          Respect robots.txt</label>
        <label class="check"><input type="checkbox" v-model="form.stop_on_blocks" />
          Pause the crawl if the site starts blocking requests</label>
      </fieldset>

      <p v-if="error" class="error-text">{{ error }}</p>
      <div class="toolbar">
        <button class="primary" type="submit" :disabled="saving">{{ site.id ? 'Save changes' : 'Create site' }}</button>
      </div>
    </form>
  `,
};

export default {
  components: { SiteList, PreflightReport, SiteForm },
  props: { system: Object, param: String },
  setup(props) {
    const sites = ref([]);
    const brands = ref([]);
    const site = ref(null);
    const tab = ref("preflight");
    const run = ref(null);
    const error = ref(null);
    const notice = ref(null);
    const reviewed = ref(false);
    let watcher = null;

    const stopWatching = () => {
      watcher?.close();
      watcher = null;
    };

    const watchRun = (active) => {
      stopWatching();
      run.value = active;
      if (!ACTIVE_RUN.has(active.status)) return;
      watcher = api.watchRun(active.id, async (update) => {
        run.value = update;
        if (!ACTIVE_RUN.has(update.status)) {
          stopWatching();
          site.value = await api.get(`/sites/${update.site_id}`);
        }
      });
    };

    const load = async () => {
      stopWatching();
      error.value = notice.value = run.value = null;
      reviewed.value = false;
      try {
        [sites.value, brands.value] = await Promise.all([api.get("/sites"), api.get("/brands")]);
        if (props.param === "new") {
          site.value = { ...NEW_SITE, brand_id: brands.value[0]?.id ?? null };
          tab.value = "settings";
        } else if (props.param) {
          site.value = await api.get(`/sites/${props.param}`);
          tab.value = "preflight";
          const runs = await api.get("/runs");
          const active = runs.find(
            (r) => r.kind === "preflight" && r.site_id === site.value.id && ACTIVE_RUN.has(r.status),
          );
          if (active) watchRun(active);
        } else {
          site.value = null;
        }
      } catch (e) {
        error.value = e.message;
      }
    };

    const startPreflight = async () => {
      error.value = notice.value = null;
      try {
        watchRun(await api.post(`/sites/${site.value.id}/preflight`));
      } catch (e) {
        error.value = e.message;
      }
    };

    const acknowledge = async () => {
      try {
        site.value = await api.post(`/sites/${site.value.id}/preflight/acknowledge`, {
          reviewed_robots_and_terms: true,
        });
      } catch (e) {
        error.value = e.message;
      }
    };

    const onSaved = (saved) => {
      const wasReady = site.value?.readiness === "ready";
      if (!site.value?.id) {
        location.hash = `#/sites/${saved.id}`;
        return;
      }
      site.value = saved;
      notice.value =
        saved.readiness === "stale"
          ? "Saved. The scope changed, so run the pre-flight check again."
          : wasReady && saved.readiness === "ready"
            ? "Saved. The site is still ready to crawl."
            : "Saved.";
    };

    const status = computed(() => site.value && READINESS[site.value.readiness]);
    const running = computed(() => run.value && ACTIVE_RUN.has(run.value.status));
    const percent = computed(() =>
      run.value?.total ? Math.round((100 * run.value.done) / run.value.total) : 0,
    );
    const hint = computed(() => {
      const s = site.value;
      if (!s?.readiness) return null;
      return {
        needs_preflight: "Run the pre-flight check before the first crawl.",
        stale: "The scope changed since the last check. Run the pre-flight check again.",
        blocked: s.preflight_result?.summary,
        needs_ack: "No blockers found. Review robots.txt and the terms of use below, then acknowledge.",
        ready: `Ready to crawl. You acknowledged the check on ${formatTime(s.preflight_acknowledged_at)}.`,
      }[s.readiness];
    });

    watch(() => props.param, load, { immediate: true });
    onBeforeUnmount(stopWatching);

    return {
      sites, brands, site, tab, run, error, notice, reviewed, status, running, percent, hint,
      startPreflight, acknowledge, onSaved, formatTime,
      addSite: () => (location.hash = "#/sites/new"),
    };
  },
  template: `
    <p v-if="error" class="error-text">{{ error }}</p>
    <SiteList v-if="!param" :sites="sites" @add="addSite" />

    <template v-else-if="site">
      <p><a href="#/sites">← All sites</a></p>
      <div class="title-row">
        <h2 class="page-title">{{ site.id ? site.name : 'New site' }}</h2>
        <span v-if="status" class="pill" :class="status.cls">{{ status.text }}</span>
        <span v-if="site.id && site.independent" class="pill">Independent test</span>
      </div>

      <div class="tabs" role="tablist" v-if="site.id">
        <button role="tab" :class="{ active: tab === 'preflight' }" @click="tab = 'preflight'">Pre-flight check</button>
        <button role="tab" :class="{ active: tab === 'settings' }" @click="tab = 'settings'">Settings</button>
      </div>

      <template v-if="site.id && tab === 'preflight'">
        <div class="banner" :class="status.cls">{{ hint }}</div>
        <div class="toolbar">
          <button class="primary" :disabled="running" @click="startPreflight">
            {{ site.preflight_result ? 'Run pre-flight check again' : 'Run pre-flight check' }}
          </button>
          <template v-if="running">
            <div class="progress grow"><div :style="{ width: percent + '%' }"></div></div>
            <span class="muted">{{ run.message }}</span>
          </template>
          <span v-else-if="site.preflight_at" class="muted">Last checked {{ formatTime(site.preflight_at) }}</span>
        </div>
        <p v-if="running" class="muted small">
          The check waits between requests to be polite, so it can take a little while.
        </p>
        <p v-if="run && run.status === 'failed'" class="error-text">{{ run.error }}</p>

        <div v-if="site.readiness === 'needs_ack'" class="card ack">
          <label class="check">
            <input type="checkbox" v-model="reviewed" />
            I have reviewed this site's robots.txt and terms of use, and they permit this automated review.
          </label>
          <button class="primary" :disabled="!reviewed" @click="acknowledge">Acknowledge</button>
        </div>

        <PreflightReport v-if="site.preflight_result" :result="site.preflight_result" />
      </template>

      <template v-else>
        <p v-if="notice" class="notice">{{ notice }}</p>
        <SiteForm :site="site" :brands="brands" @saved="onSaved" />
      </template>
    </template>
  `,
};
