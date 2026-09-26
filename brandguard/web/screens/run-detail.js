import { api, formatTime } from "../api.js";
import {
  ACTIVE_RUN, CRAWLERS, RUN_KINDS, RUN_STATUS_CLASS, SKIP_REASONS, VISIBILITY,
} from "../labels.js";

const { ref, computed, watch, onBeforeUnmount } = Vue;

const PAGE_SIZE = 50;
const VIEWS = {
  pages: { label: "Pages crawled", query: { kind: "page", status: "ok,failed,blocked" } },
  files: { label: "Files found", query: { status: "discovered" } },
  skipped: { label: "Not crawled", query: { status: "skipped" } },
};

const sum = (obj) => Object.values(obj || {}).reduce((a, b) => a + b, 0);
const reason = (value) => SKIP_REASONS[value] || value;

const StatsCards = {
  props: { stats: Object },
  setup() {
    return { sum, reason, CRAWLERS };
  },
  template: `
    <div class="cards section">
      <div class="card">
        <div class="label">Pages</div>
        <div class="value">{{ stats.pages.ok || 0 }} crawled</div>
        <div class="muted small">
          {{ stats.pages.failed || 0 }} failed · {{ stats.pages.blocked || 0 }} refused
          · {{ stats.pages.redirected_out_of_scope || 0 }} redirected away
        </div>
      </div>
      <div class="card">
        <div class="label">Files found</div>
        <div class="value">{{ sum(stats.files) }}</div>
        <div class="muted small">
          <span v-for="(n, kind) in stats.files" :key="kind">{{ kind }} {{ n }} · </span>
        </div>
      </div>
      <div class="card">
        <div class="label">Text segments</div>
        <div class="value">{{ sum(stats.segments) }}</div>
        <div class="muted small">
          {{ stats.segments.visible || 0 }} visible · {{ stats.segments.hidden || 0 }} hidden
          · {{ stats.segments.metadata || 0 }} metadata
        </div>
      </div>
      <div class="card" v-if="stats.runtime_s !== undefined">
        <div class="label">{{ CRAWLERS[stats.crawler]?.label || stats.crawler }} {{ stats.crawler_version }}</div>
        <div class="value">{{ Math.round(stats.runtime_s) }} s</div>
        <div class="muted small">
          peak memory {{ stats.peak_rss_mb }} MB · CPU {{ stats.cpu_s }} s · {{ stats.interval_s }} s between pages
        </div>
      </div>
    </div>
    <div class="grid-2 section" v-if="sum(stats.skipped) || stats.errors?.length">
      <div class="card" v-if="sum(stats.skipped)">
        <h2>Not crawled</h2>
        <table class="kv"><tbody>
          <tr v-for="(n, why) in stats.skipped" :key="why"><th>{{ reason(why) }}</th><td>{{ n }}</td></tr>
        </tbody></table>
      </div>
      <div class="card" v-if="stats.errors?.length">
        <h2>Errors</h2>
        <ul class="plain small mono"><li v-for="e in stats.errors" :key="e">{{ e }}</li></ul>
      </div>
    </div>
  `,
};

const AssetTable = {
  props: { runId: Number },
  setup(props) {
    const view = ref("pages");
    const q = ref("");
    const offset = ref(0);
    const page = ref({ total: 0, items: [] });
    const load = async () => {
      const params = new URLSearchParams({ ...VIEWS[view.value].query, limit: PAGE_SIZE, offset: offset.value });
      if (q.value) params.set("q", q.value);
      page.value = await api.get(`/runs/${props.runId}/assets?${params}`);
    };
    watch([view, q], () => { offset.value = 0; load(); });
    watch(offset, load);
    load();
    const open = (asset) => {
      if (asset.kind === "page" && asset.status === "ok") {
        location.hash = `#/runs/${props.runId}/assets/${asset.id}`;
      }
    };
    return { view, q, offset, page, open, VIEWS, PAGE_SIZE, reason, sum };
  },
  template: `
    <div class="toolbar section">
      <div class="tabs compact">
        <button v-for="(v, id) in VIEWS" :key="id" :class="{ active: view === id }" @click="view = id">{{ v.label }}</button>
      </div>
      <input type="text" v-model.lazy="q" placeholder="Filter by URL or title" class="grow" />
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>URL</th><th>Kind</th><th>Status</th><th v-if="view === 'pages'">Text segments</th></tr></thead>
        <tbody>
          <tr v-if="!page.items.length"><td colspan="4" class="muted">Nothing here.</td></tr>
          <tr v-for="a in page.items" :key="a.id" :class="{ clickable: a.kind === 'page' && a.status === 'ok' }" @click="open(a)">
            <td>
              <div v-if="a.title">{{ a.title }}</div>
              <div class="mono muted">{{ a.url }}</div>
            </td>
            <td>{{ a.kind }}</td>
            <td>
              <span class="pill" :class="{ ok: a.status === 'ok', bad: a.status === 'failed' || a.status === 'blocked' }">{{ a.status }}</span>
              <div class="muted small" v-if="a.status_reason">{{ reason(a.status_reason) }}</div>
            </td>
            <td v-if="view === 'pages'" class="small">
              <template v-if="a.info?.segments">
                {{ a.info.segments.visible || 0 }} visible · {{ a.info.segments.hidden || 0 }} hidden
                · {{ a.info.segments.metadata || 0 }} metadata
              </template>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="toolbar section" v-if="page.total > PAGE_SIZE">
      <button :disabled="offset === 0" @click="offset -= PAGE_SIZE">Previous</button>
      <span class="muted">{{ offset + 1 }}–{{ Math.min(offset + PAGE_SIZE, page.total) }} of {{ page.total }}</span>
      <button :disabled="offset + PAGE_SIZE >= page.total" @click="offset += PAGE_SIZE">Next</button>
    </div>
  `,
};

export const AssetView = {
  props: { runId: Number, assetId: Number },
  setup(props) {
    const asset = ref(null);
    const visibility = ref("");
    const source = ref("");
    const selected = ref(null);
    const img = ref(null);
    const scale = ref(0);
    const load = async () => {
      const params = new URLSearchParams();
      if (visibility.value) params.set("visibility", visibility.value);
      asset.value = await api.get(`/assets/${props.assetId}?${params}`);
    };
    watch(visibility, load);
    load();
    const sources = computed(() => [...new Set((asset.value?.segments || []).map((s) => s.text_source))].sort());
    const segments = computed(() =>
      (asset.value?.segments || []).filter((s) => !source.value || s.text_source === source.value));
    const onImage = () => (scale.value = img.value.clientWidth / img.value.naturalWidth);
    const box = computed(() => {
      const b = selected.value?.locator?.bbox;
      if (!b || !scale.value) return null;
      return { left: `${b[0] * scale.value}px`, top: `${b[1] * scale.value}px`,
               width: `${b[2] * scale.value}px`, height: `${b[3] * scale.value}px` };
    });
    const pick = (segment) => {
      selected.value = segment;
      if (box.value) img.value?.parentElement?.scrollTo({ top: parseFloat(box.value.top) - 80, behavior: "smooth" });
    };
    return { asset, visibility, source, sources, segments, selected, img, box, onImage, pick, VISIBILITY, formatTime };
  },
  template: `
    <p><a :href="'#/runs/' + runId">← Back to run {{ runId }}</a></p>
    <template v-if="asset">
      <div class="title-row"><h2 class="page-title">{{ asset.title || asset.url }}</h2></div>
      <p class="muted small">
        <a :href="asset.final_url || asset.url" target="_blank" rel="noopener" class="mono">{{ asset.final_url || asset.url }}</a>
        · HTTP {{ asset.http_status }} · language {{ asset.language || 'not declared' }}
        · crawled {{ formatTime(asset.fetched_at) }}
      </p>
      <div class="evidence">
        <div class="shot card" v-if="asset.screenshot_path">
          <div class="shot-scroll">
            <img ref="img" :src="'/files/' + asset.screenshot_path" @load="onImage" alt="Page screenshot" />
            <div v-if="box" class="highlight" :style="box"></div>
          </div>
          <p class="muted small">Pick a visible segment to see where it is on the page.</p>
        </div>
        <div class="card">
          <div class="toolbar">
            <div class="tabs compact">
              <button :class="{ active: !visibility }" @click="visibility = ''">All</button>
              <button v-for="(v, id) in VISIBILITY" :key="id" v-show="id !== 'spoken'"
                      :class="{ active: visibility === id }" @click="visibility = id">{{ v.text }}</button>
            </div>
            <select v-model="source" aria-label="Text source">
              <option value="">All sources</option>
              <option v-for="s in sources" :key="s" :value="s">{{ s }}</option>
            </select>
          </div>
          <p class="muted small">{{ segments.length }} segments</p>
          <ul class="segments">
            <li v-for="s in segments" :key="s.id" :class="{ selected: selected && selected.id === s.id }" @click="pick(s)">
              <div>{{ s.text }}</div>
              <div class="small muted">
                <span class="pill" :class="VISIBILITY[s.visibility]?.cls">{{ VISIBILITY[s.visibility]?.text }}</span>
                {{ s.text_source }}
                <span v-if="s.render_transform"> · shown as {{ s.render_transform }}</span>
                <span v-if="s.locator?.path"> · {{ s.locator.path }}</span>
              </div>
            </li>
          </ul>
        </div>
      </div>
      <div class="card section" v-if="asset.files.length">
        <h2>Files and embeds on this page</h2>
        <ul class="plain small">
          <li v-for="f in asset.files" :key="f.id">
            <span class="pill">{{ f.kind }}</span> <span class="mono">{{ f.url }}</span>
            <span class="muted"> · {{ f.status }}{{ f.status_reason ? ' (' + f.status_reason + ')' : '' }}</span>
          </li>
        </ul>
      </div>
    </template>
  `,
};

export default {
  components: { StatsCards, AssetTable },
  props: { runId: Number },
  setup(props) {
    const run = ref(null);
    const error = ref(null);
    let source = null;
    const close = () => { source?.close(); source = null; };
    const load = async () => {
      close();
      try {
        run.value = await api.get(`/runs/${props.runId}`);
        if (ACTIVE_RUN.has(run.value.status)) {
          source = api.watchRun(props.runId, (update) => {
            run.value = update;
            if (!ACTIVE_RUN.has(update.status)) close();
          });
        }
      } catch (e) {
        error.value = e.message;
      }
    };
    const cancel = async () => {
      try { run.value = await api.post(`/runs/${props.runId}/cancel`); } catch (e) { error.value = e.message; }
    };
    watch(() => props.runId, load, { immediate: true });
    onBeforeUnmount(close);
    const active = computed(() => run.value && ACTIVE_RUN.has(run.value.status));
    const percent = computed(() => (run.value?.total ? Math.round((100 * run.value.done) / run.value.total) : 0));
    return { run, error, active, percent, cancel, formatTime, RUN_KINDS, RUN_STATUS_CLASS, CRAWLERS };
  },
  template: `
    <p><a href="#/runs">← All runs</a></p>
    <p v-if="error" class="error-text">{{ error }}</p>
    <template v-if="run">
      <div class="title-row">
        <h2 class="page-title">{{ RUN_KINDS[run.kind] || run.kind }} #{{ run.id }}</h2>
        <span class="pill" :class="RUN_STATUS_CLASS[run.status]">{{ run.status }}</span>
        <span v-if="run.params?.crawler" class="pill">{{ CRAWLERS[run.params.crawler]?.label }}</span>
        <a v-if="run.site_name" :href="'#/sites/' + run.site_id">{{ run.site_name }}</a>
      </div>
      <p class="muted">{{ run.message }} · started {{ formatTime(run.started_at || run.created_at) }}</p>
      <div v-if="active" class="toolbar">
        <div class="progress grow"><div :style="{ width: percent + '%' }"></div></div>
        <span class="muted">{{ run.done }} / {{ run.total }} pages</span>
        <button :disabled="run.cancel_requested" @click="cancel">{{ run.cancel_requested ? 'Stopping…' : 'Stop' }}</button>
      </div>
      <p v-if="run.error" class="error-text">{{ run.error }}</p>
      <template v-if="run.kind === 'crawl' && run.stats">
        <StatsCards :stats="run.stats" />
        <AssetTable v-if="!active" :run-id="run.id" />
      </template>
    </template>
  `,
};
