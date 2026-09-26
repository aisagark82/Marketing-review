import { api, formatTime } from "../api.js";
import { BarList, StatTile } from "../charts.js";
import { ASSET_KINDS, CRAWLERS, FINDING_KINDS, VISIBILITY, sourceLabel } from "../labels.js";

const { ref, computed, watch, onMounted } = Vue;

const toItems = (obj, name = (k) => k) =>
  Object.entries(obj || {}).sort((a, b) => b[1] - a[1]).map(([k, v]) => [name(k), v]);

export const ComplianceSummary = {
  components: { StatTile },
  props: { c: Object },
  setup(props) {
    const changes = computed(() => props.c.changes || {});
    return { changes };
  },
  template: `
    <div class="kpis">
      <StatTile hero label="Compliance score" :value="c.score" detail="100 = no violations; 10 points per high-severity violation on a page or PDF" />
      <StatTile label="Pages and PDFs without a high-severity violation" :value="c.clean_share + '%'"
                :detail="(c.assets_checked - c.assets_with_violations) + ' of ' + c.assets_checked + ' fully clean'" />
      <StatTile label="Violations" :value="c.violations" :detail="c.assets_with_violations + ' pages or PDFs affected'" />
      <StatTile label="To review" :value="c.to_review" detail="possible misspellings" />
      <StatTile v-if="changes.previous_run_id" label="Since the previous crawl"
                :value="'+' + changes.new + ' / −' + changes.fixed"
                :detail="changes.new + ' new, ' + changes.fixed + ' fixed, ' + changes.persisting + ' still there'" />
    </div>
  `,
};

export default {
  components: { ComplianceSummary, BarList },
  props: { system: Object, param: String },
  setup() {
    const runs = ref([]);
    const runId = ref(null);
    const c = ref(null);
    const error = ref(null);
    onMounted(async () => {
      runs.value = await api.get("/finding-runs");
      runId.value = runs.value[0]?.id ?? null;
    });
    watch(runId, async (id) => {
      if (!id) return;
      try { c.value = await api.get(`/runs/${id}/compliance`); error.value = null; } catch (e) { error.value = e.message; }
    });
    const charts = computed(() => c.value && {
      visibility: toItems(c.value.by_visibility, (k) => `${VISIBILITY[k]?.text || k} text`),
      assets: toItems(c.value.by_asset_kind, (k) => ASSET_KINDS[k] || k),
      sources: toItems(c.value.by_source, sourceLabel),
      kinds: toItems(c.value.by_kind, (k) => FINDING_KINDS[k] || k),
      spellings: (c.value.top_matches || []).map(([t, n]) => [`“${t}”`, n]),
    });
    return { runs, runId, c, charts, error, formatTime, CRAWLERS, ASSET_KINDS };
  },
  template: `
    <p v-if="error" class="error-text">{{ error }}</p>
    <div v-if="!runs.length" class="card placeholder">
      <h2>Nothing to show yet</h2><p>Crawl a site first; its compliance appears here when the crawl finishes.</p>
    </div>
    <template v-else>
      <div class="toolbar">
        <select v-model="runId" aria-label="Crawl">
          <option v-for="r in runs" :key="r.id" :value="r.id">
            Crawl #{{ r.id }} · {{ r.site_name }} · {{ CRAWLERS[r.crawler]?.label }} · {{ formatTime(r.started_at) }}
          </option>
        </select>
        <a class="button" :href="'#/findings'">All findings</a>
      </div>
      <template v-if="c">
        <ComplianceSummary :c="c" />
        <p class="muted small">Rules: <span v-for="r in c.run.rules" :key="r.id"><a :href="'#/rules/' + r.id">{{ r.key }}</a> version {{ r.version }} </span>
          · hidden text and metadata count fully (D8) · findings to review don't count until confirmed</p>
        <div class="grid-2 section">
          <div class="card"><h2>Violations by where in the page</h2><BarList :items="charts.visibility" /></div>
          <div class="card"><h2>Violations by type</h2><BarList :items="charts.kinds" /></div>
          <div class="card"><h2>Violations by text source</h2><BarList :items="charts.sources" /></div>
          <div class="card"><h2>Violations in pages and PDFs</h2><BarList :items="charts.assets" /></div>
          <div class="card"><h2>Most frequent wrong spellings</h2><BarList :items="charts.spellings" /></div>
        </div>
        <div class="card section">
          <h2>Lowest-scoring pages and PDFs</h2>
          <p v-if="!c.worst_assets.length" class="muted">No violations.</p>
          <table v-else>
            <thead><tr><th>Score</th><th>Page or PDF</th><th>Violations</th></tr></thead>
            <tbody><tr v-for="a in c.worst_assets" :key="a.id">
              <td class="num">{{ a.score }}</td>
              <td><a :href="'#/runs/' + c.run.id + '/assets/' + a.id">{{ a.title || a.url }}</a>
                <div class="muted mono small">{{ a.url }}</div></td>
              <td>{{ a.violations }} <span class="muted small">{{ ASSET_KINDS[a.kind] === 'PDFs' ? '(PDF)' : '' }}</span></td>
            </tr></tbody>
          </table>
        </div>
      </template>
    </template>
  `,
};
