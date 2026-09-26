import { api, formatTime } from "../api.js";
import {
  ASSET_KINDS, CHANGE, CRAWLERS, FINDING_KINDS, FINDING_STATUS, VISIBILITY, sourceLabel,
} from "../labels.js";
import { Highlighted } from "./rules.js";

const { ref, computed, watch, onMounted, nextTick } = Vue;

const PAGE_SIZE = 50;
const EXCERPT = 70;
const FACETS = {
  status: { label: "Status", names: (v) => FINDING_STATUS[v]?.text || v },
  kind: { label: "Type", names: (v) => FINDING_KINDS[v] || v },
  visibility: { label: "Where in the page", names: (v) => VISIBILITY[v]?.text || v },
  asset_kind: { label: "In", names: (v) => ASSET_KINDS[v] || v },
  change: { label: "Since last crawl", names: (v) => CHANGE[v]?.text || v },
  severity: { label: "Severity", names: (v) => v },
};

// A window of the segment text around the match, with the match's offsets shifted to fit.
function excerpt(finding) {
  const text = finding.segment.text;
  const from = Math.max(0, finding.start - EXCERPT);
  const to = Math.min(text.length, finding.end + EXCERPT);
  const prefix = from > 0 ? "…" : "";
  return {
    text: prefix + text.slice(from, to) + (to < text.length ? "…" : ""),
    matches: [{ ...finding, start: finding.start - from + prefix.length, end: finding.end - from + prefix.length }],
  };
}

const RunPicker = {
  props: { modelValue: Number, runs: Array },
  emits: ["update:modelValue"],
  setup() {
    return { CRAWLERS, formatTime };
  },
  template: `
    <select :value="modelValue" @change="$emit('update:modelValue', Number($event.target.value))" aria-label="Crawl">
      <option v-for="r in runs" :key="r.id" :value="r.id">
        Crawl #{{ r.id }} · {{ r.site_name }} · {{ CRAWLERS[r.crawler]?.label }} · {{ formatTime(r.started_at) }}
        · {{ r.violations }} violations
      </option>
    </select>
  `,
};

const FindingsList = {
  components: { Highlighted, RunPicker },
  setup() {
    const runs = ref([]);
    const runId = ref(null);
    const filters = ref({});
    const source = ref("");
    const q = ref("");
    const offset = ref(0);
    const page = ref(null);
    const error = ref(null);

    const params = () => {
      const p = new URLSearchParams({ run_id: runId.value, limit: PAGE_SIZE, offset: offset.value });
      for (const [name, value] of Object.entries(filters.value)) if (value) p.set(name, value);
      if (source.value) p.set("source", source.value);
      if (q.value) p.set("q", q.value);
      return p;
    };
    const load = async () => {
      if (!runId.value) return;
      try {
        page.value = await api.get(`/findings?${params()}`);
        error.value = null;
      } catch (e) {
        error.value = e.message;
      }
    };
    onMounted(async () => {
      runs.value = await api.get("/finding-runs");
      const remembered = Number(sessionStorage.getItem("findings.run"));
      runId.value = runs.value.some((r) => r.id === remembered) ? remembered : runs.value[0]?.id ?? null;
      if (!runId.value) page.value = { total: 0, items: [], facets: {} };
    });
    watch(runId, (id) => {
      try { sessionStorage.setItem("findings.run", id); } catch { /* storage unavailable */ }
      filters.value = {};
      offset.value = 0;
      load();
    });
    watch([filters, source, q], () => { offset.value = 0; load(); }, { deep: true });
    watch(offset, load);

    const toggle = (name, value) => {
      filters.value = { ...filters.value, [name]: filters.value[name] === value ? "" : value };
    };
    const open = (finding) => (location.hash = `#/findings/${finding.id}`);
    const csvUrl = computed(() => {
      const p = params();
      p.delete("limit");
      p.delete("offset");
      return `/api/findings.csv?${p}`;
    });
    const sources = computed(() => Object.keys(page.value?.facets?.source || {}).sort());
    return {
      runs, runId, filters, source, q, offset, page, error, toggle, open, csvUrl, sources,
      excerpt, sourceLabel, FACETS, FINDING_KINDS, FINDING_STATUS, VISIBILITY, CHANGE, PAGE_SIZE,
    };
  },
  template: `
    <p v-if="error" class="error-text">{{ error }}</p>
    <div v-if="page && !runs.length" class="card placeholder">
      <h2>No findings yet</h2>
      <p>Crawl a site (Sites → Crawl). Its text is checked against the brand rules when the crawl finishes.</p>
    </div>
    <template v-else-if="page">
      <div class="toolbar">
        <RunPicker v-model="runId" :runs="runs" />
        <input type="text" v-model.lazy="q" placeholder="Search found text, page text or URL" class="grow" />
        <a class="button" :href="csvUrl" download>Export CSV</a>
      </div>
      <p class="muted small" v-if="page.changes?.previous_run_id">
        Compared with crawl #{{ page.changes.previous_run_id }}: {{ page.changes.new }} new,
        {{ page.changes.persisting }} still there, {{ page.changes.fixed }} fixed (no longer found).
      </p>
      <div class="facets">
        <div v-for="(facet, name) in FACETS" :key="name" class="facet" v-show="Object.keys(page.facets[name] || {}).length">
          <span class="label">{{ facet.label }}</span>
          <button v-for="(n, value) in page.facets[name]" :key="value" class="chip"
                  :class="{ active: filters[name] === value }" :aria-pressed="filters[name] === value"
                  @click="toggle(name, value)">
            {{ facet.names(value) }}<span class="count">{{ n }}</span>
          </button>
        </div>
        <div class="facet" v-if="sources.length">
          <span class="label">Text source</span>
          <select v-model="source" aria-label="Text source">
            <option value="">All</option>
            <option v-for="s in sources" :key="s" :value="s">{{ sourceLabel(s) }} ({{ page.facets.source[s] }})</option>
          </select>
        </div>
      </div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Found</th><th>Type</th><th>Where</th><th>Status</th></tr></thead>
          <tbody>
            <tr v-if="!page.items.length"><td colspan="4" class="muted">No findings match these filters.</td></tr>
            <tr v-for="f in page.items" :key="f.id" class="clickable" @click="open(f)">
              <td class="excerpt">
                <Highlighted :text="excerpt(f).text" :matches="excerpt(f).matches" />
                <div class="small muted">“{{ f.matched_text }}” → {{ f.expected }}</div>
              </td>
              <td>{{ FINDING_KINDS[f.kind] || f.kind }}<div class="muted small">{{ f.severity }}</div></td>
              <td class="where">
                <div>{{ f.asset.title || f.asset.url }}</div>
                <div class="muted mono">{{ f.asset.url }}</div>
                <div class="muted">
                  <span class="pill" :class="VISIBILITY[f.segment.visibility]?.cls">{{ VISIBILITY[f.segment.visibility]?.text }}</span>
                  {{ sourceLabel(f.segment.source) }}<span v-if="f.segment.locator?.page"> · page {{ f.segment.locator.page }}</span>
                </div>
              </td>
              <td>
                <span class="pill" :class="FINDING_STATUS[f.status]?.cls">{{ FINDING_STATUS[f.status]?.text }}</span>
                <div v-if="f.change" class="small"><span class="pill" :class="CHANGE[f.change].cls">{{ CHANGE[f.change].text }}</span></div>
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
      <p v-else class="muted small section">{{ page.total }} finding(s)</p>
    </template>
  `,
};

// Screenshot with the finding's box, scrolled into view.
const ScreenshotEvidence = {
  props: { shot: Object },
  setup(props) {
    const img = ref(null);
    const box = ref(null);
    const place = () => {
      const scale = img.value.clientWidth / img.value.naturalWidth;
      const [x, y, w, h] = props.shot.bbox;
      const pad = 4;
      box.value = { left: `${x * scale - pad}px`, top: `${y * scale - pad}px`,
                    width: `${w * scale + 2 * pad}px`, height: `${h * scale + 2 * pad}px` };
      nextTick(() => img.value.parentElement.scrollTo({ top: Math.max(0, y * scale - 120) }));
    };
    return { img, box, place };
  },
  template: `
    <div class="evidence-shot">
      <img ref="img" :src="'/files/' + shot.path" @load="place" alt="Screenshot of the page when it was crawled" />
      <div v-if="box" class="highlight" :style="box"></div>
    </div>
  `,
};

// PDF page rendered with PDF.js, with the finding's line boxed.
const PdfEvidence = {
  props: { pdf: Object },
  setup(props) {
    const canvas = ref(null);
    const box = ref(null);
    const error = ref(null);
    onMounted(async () => {
      if (!props.pdf.page) return;
      try {
        const pdfjs = await import("../vendor/pdf.min.js");
        pdfjs.GlobalWorkerOptions.workerSrc = "/vendor/pdf.worker.min.js";
        const doc = await pdfjs.getDocument({ url: `/files/${props.pdf.file_path}` }).promise;
        const page = await doc.getPage(props.pdf.page);
        const viewport = page.getViewport({ scale: 1.5 });
        canvas.value.width = viewport.width;
        canvas.value.height = viewport.height;
        await page.render({ canvasContext: canvas.value.getContext("2d"), viewport, canvas: canvas.value }).promise;
        if (props.pdf.bbox) {
          // PDF boxes are [left, bottom, right, top] in points; convert both corners.
          const [left, bottom, right, top] = props.pdf.bbox;
          const [x1, y1] = viewport.convertToViewportPoint(left, bottom);
          const [x2, y2] = viewport.convertToViewportPoint(right, top);
          const scale = canvas.value.clientWidth / viewport.width;
          const pad = 4;
          box.value = { left: `${Math.min(x1, x2) * scale - pad}px`, top: `${Math.min(y1, y2) * scale - pad}px`,
                        width: `${Math.abs(x2 - x1) * scale + 2 * pad}px`, height: `${Math.abs(y2 - y1) * scale + 2 * pad}px` };
        }
      } catch (e) {
        error.value = `Could not show the PDF page: ${e.message}`;
      }
    });
    return { canvas, box, error };
  },
  template: `
    <p v-if="!pdf.page" class="muted">Found in the PDF's {{ pdf.property ? 'properties (' + pdf.property + ')' : 'bookmarks' }}, not on a page.</p>
    <template v-else>
      <p class="muted small">Page {{ pdf.page }}</p>
      <div class="pdf-canvas-wrap"><canvas ref="canvas"></canvas><div v-if="box" class="highlight" :style="box"></div></div>
      <p v-if="error" class="error-text">{{ error }}</p>
    </template>
    <p><a :href="'/files/' + pdf.file_path" target="_blank" rel="noopener">Open the downloaded PDF</a></p>
  `,
};

// The saved HTML of the element (hidden text, metadata), with the match highlighted.
const SnippetEvidence = {
  props: { snippet: Object, matched: String },
  setup(props) {
    const parts = computed(() => {
      const html = props.snippet.html;
      const out = [];
      let at = 0;
      for (let i = html.indexOf(props.matched); i !== -1 && props.matched; i = html.indexOf(props.matched, at)) {
        out.push({ text: html.slice(at, i) }, { text: props.matched, match: true });
        at = i + props.matched.length;
      }
      out.push({ text: html.slice(at) });
      return out;
    });
    return { parts };
  },
  template: `
    <div class="label">From the saved page</div>
    <pre class="snippet"><template v-for="(p, i) in parts" :key="i"><mark v-if="p.match" class="violation">{{ p.text }}</mark><template v-else>{{ p.text }}</template></template></pre>
    <p class="muted small">
      <span v-if="snippet.path">JSON path: <span class="mono">{{ snippet.path }}</span> · </span>
      <span v-if="snippet.attribute">Attribute: <span class="mono">{{ snippet.attribute }}</span> · </span>
      Element: <span class="mono">{{ snippet.selector }}</span>
    </p>
  `,
};

export const EvidenceView = {
  components: { Highlighted, ScreenshotEvidence, PdfEvidence, SnippetEvidence },
  props: { findingId: Number },
  setup(props) {
    const f = ref(null);
    const error = ref(null);
    const load = async () => {
      try { f.value = await api.get(`/findings/${props.findingId}`); } catch (e) { error.value = e.message; }
    };
    load();
    return { f, error, sourceLabel, FINDING_KINDS, FINDING_STATUS, VISIBILITY, CHANGE, CRAWLERS };
  },
  template: `
    <p v-if="error" class="error-text">{{ error }}</p>
    <template v-if="f">
      <div class="toolbar">
        <a href="#/findings">← All findings</a>
        <span class="grow"></span>
        <a v-if="f.previous_id" class="button" :href="'#/findings/' + f.previous_id">← Previous</a>
        <a v-if="f.next_id" class="button" :href="'#/findings/' + f.next_id">Next →</a>
      </div>
      <div class="title-row">
        <h2 class="page-title">{{ FINDING_KINDS[f.kind] || f.kind }}</h2>
        <span class="pill" :class="FINDING_STATUS[f.status]?.cls">{{ FINDING_STATUS[f.status]?.text }}</span>
        <span class="pill">{{ f.severity }} severity</span>
        <span v-if="f.change" class="pill" :class="CHANGE[f.change].cls">{{ CHANGE[f.change].text }}</span>
      </div>
      <div class="evidence">
        <div class="card">
          <ScreenshotEvidence v-if="f.evidence.screenshot" :shot="f.evidence.screenshot" />
          <PdfEvidence v-if="f.evidence.pdf" :pdf="f.evidence.pdf" />
          <div :class="{ section: f.evidence.screenshot }">
            <SnippetEvidence v-if="f.evidence.snippet" :snippet="f.evidence.snippet" :matched="f.matched_text" />
          </div>
          <p v-if="!f.evidence.screenshot && !f.evidence.pdf && !f.evidence.snippet" class="muted">
            No picture of this spot was saved; the text is shown on the right.
          </p>
        </div>
        <div class="card">
          <p class="big-match">“{{ f.matched_text }}” → {{ f.expected }}</p>
          <p class="muted">{{ f.note }}</p>
          <div class="label">The text it was found in</div>
          <p class="prose"><Highlighted :text="f.segment.text" :matches="[f]" /></p>
          <dl class="detail-list">
            <dt>Where</dt>
            <dd>
              <span class="pill" :class="VISIBILITY[f.segment.visibility]?.cls">{{ VISIBILITY[f.segment.visibility]?.text }}</span>
              {{ sourceLabel(f.segment.source) }}<span v-if="f.segment.locator?.page"> · PDF page {{ f.segment.locator.page }}</span>
            </dd>
            <dt>{{ f.asset.kind === 'pdf' ? 'PDF' : 'Page' }}</dt>
            <dd>{{ f.asset.title || '(no title)' }}<br />
              <a :href="f.evidence.live_url" target="_blank" rel="noopener" class="mono">{{ f.evidence.live_url }}</a></dd>
            <dt>Rule</dt>
            <dd><a :href="'#/rules/' + f.rule.id">{{ f.rule.name }}</a>, version {{ f.rule_version }}
              <span v-if="f.rule.current_version !== f.rule_version" class="muted">(current: {{ f.rule.current_version }})</span></dd>
            <dt>Crawl</dt>
            <dd><a :href="'#/runs/' + f.run.id">#{{ f.run.id }}</a> · {{ f.run.site_name }} · {{ CRAWLERS[f.run.crawler]?.label }}
              · <a :href="'#/runs/' + f.run.id + '/assets/' + f.asset.id">all text of this {{ f.asset.kind === 'pdf' ? 'PDF' : 'page' }}</a></dd>
            <dt>Confidence</dt><dd>{{ Math.round(f.confidence * 100) }}%</dd>
          </dl>
          <p v-if="f.status === 'ambiguous'" class="banner section">
            This is a possible misspelling. Gemini will help review these in a later step.
          </p>
        </div>
      </div>
    </template>
  `,
};

export default {
  components: { FindingsList, EvidenceView },
  props: { system: Object, param: String },
  template: `
    <EvidenceView v-if="param" :finding-id="Number(param)" :key="param" />
    <FindingsList v-else />
  `,
};
