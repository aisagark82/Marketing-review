import { api, formatTime } from "../api.js";
import { FINDING_KINDS } from "../labels.js";

const { ref, computed, watch } = Vue;

const EXCEPTIONS = {
  urls: "Web addresses (https://…, www.…)",
  emails: "Email addresses",
  domains: "Domain names (pfizer.com)",
  file_names: "File names (report.pdf)",
  handles: "Social handles (@name)",
  hashtags: "Hashtags (#name)",
};
const LANGUAGES = { "": "Not specified", en: "English", ja: "Japanese", "zh-Hans": "Chinese (Simplified)",
  "zh-Hant": "Chinese (Traditional)", es: "Spanish", de: "German" };
const LIST_FIELDS = ["allowed_casings", "disallowed", "ignore_words"];

const lines = (text) => text.split("\n").map((l) => l.trim()).filter(Boolean);

// The form keeps lists as one-per-line text.
function toForm(rule) {
  const c = rule.config;
  return {
    name: rule.name, severity: rule.severity, enabled: rule.enabled,
    canonical: c.canonical,
    ...Object.fromEntries(LIST_FIELDS.map((k) => [k, (c[k] || []).join("\n")])),
    attached_forms_ok: c.attached_forms_ok,
    fuzzy_enabled: c.fuzzy.enabled, max_edit_distance: c.fuzzy.max_edit_distance,
    exceptions: [...c.exceptions],
    locales: Object.entries(c.locales || {}).map(([code, v]) => ({
      code, approved: v.approved.join("\n"), disallowed: v.disallowed.join("\n"),
    })),
    cross_market: c.cross_market,
  };
}

function toConfig(form) {
  return {
    canonical: form.canonical.trim(),
    ...Object.fromEntries(LIST_FIELDS.map((k) => [k, lines(form[k])])),
    attached_forms_ok: form.attached_forms_ok,
    fuzzy: { enabled: form.fuzzy_enabled, max_edit_distance: Number(form.max_edit_distance) },
    exceptions: form.exceptions,
    locales: Object.fromEntries(form.locales.filter((l) => l.code.trim()).map((l) => [
      l.code.trim(), { approved: lines(l.approved), disallowed: lines(l.disallowed) },
    ])),
    cross_market: form.cross_market,
  };
}

// Split text into plain and highlighted parts for the given matches.
export function highlight(text, matches) {
  const parts = [];
  let at = 0;
  for (const m of [...matches].sort((a, b) => a.start - b.start)) {
    if (m.start < at) continue;
    if (m.start > at) parts.push({ text: text.slice(at, m.start) });
    parts.push({ text: text.slice(m.start, m.end), match: m });
    at = m.end;
  }
  if (at < text.length) parts.push({ text: text.slice(at) });
  return parts;
}

export const Highlighted = {
  props: { text: String, matches: Array },
  setup(props) {
    const parts = computed(() => highlight(props.text, props.matches || []));
    return { parts, FINDING_KINDS };
  },
  template: `<span><template v-for="(p, i) in parts" :key="i"><mark v-if="p.match" :class="p.match.status"
    :title="(FINDING_KINDS[p.match.kind] || p.match.kind) + ': expected ' + p.match.expected">{{ p.text }}</mark><template
    v-else>{{ p.text }}</template></template></span>`,
};

const RuleForm = {
  props: { form: Object },
  setup() {
    const addLocale = (form) => form.locales.push({ code: "", approved: "", disallowed: "" });
    return { EXCEPTIONS, addLocale };
  },
  template: `
    <div class="form wide">
      <div class="grid-2">
        <div class="field"><label for="r-name">Rule name</label>
          <input id="r-name" type="text" v-model="form.name" /></div>
        <div class="field"><label for="r-sev">Severity of a violation</label>
          <select id="r-sev" v-model="form.severity">
            <option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option>
          </select></div>
      </div>
      <label class="check"><input type="checkbox" v-model="form.enabled" /> Rule is active</label>

      <fieldset>
        <legend>The brand name</legend>
        <div class="grid-2">
          <div class="field"><label for="r-canon">Correct spelling</label>
            <input id="r-canon" type="text" v-model="form.canonical" /></div>
          <div class="field"><label for="r-casings">Allowed letter cases</label>
            <textarea id="r-casings" rows="2" v-model="form.allowed_casings"></textarea>
            <div class="hint">One per line, e.g. Pfizer and PFIZER. Any other case is a violation.</div></div>
        </div>
        <div class="field"><label for="r-dis">Known misspellings</label>
          <textarea id="r-dis" rows="3" v-model="form.disallowed"></textarea>
          <div class="hint">One per line. Always a violation, in any letter case.</div></div>
        <label class="check"><input type="checkbox" v-model="form.attached_forms_ok" />
          Accept the name inside longer words (Pfizer's, Pfizer-BioNTech, PfizerPro) when the name part is right</label>
      </fieldset>

      <fieldset>
        <legend>Near-miss spellings</legend>
        <label class="check"><input type="checkbox" v-model="form.fuzzy_enabled" />
          Flag words that are almost the name (e.g. Pfzier) for review</label>
        <div class="grid-2" v-if="form.fuzzy_enabled">
          <div class="field"><label for="r-dist">How close</label>
            <select id="r-dist" v-model="form.max_edit_distance">
              <option :value="1">1 letter off (recommended)</option><option :value="2">Up to 2 letters off</option>
            </select></div>
          <div class="field"><label for="r-ignore">Real words to ignore</label>
            <textarea id="r-ignore" rows="2" v-model="form.ignore_words"></textarea></div>
        </div>
      </fieldset>

      <fieldset>
        <legend>Not checked</legend>
        <label class="check" v-for="(label, id) in EXCEPTIONS" :key="id">
          <input type="checkbox" :value="id" v-model="form.exceptions" /> {{ label }}</label>
      </fieldset>

      <fieldset>
        <legend>Names in local scripts, per market</legend>
        <div class="hint">For Chinese and Japanese pages. Latin forms are covered by the settings above.</div>
        <div class="locale-row" v-for="(loc, i) in form.locales" :key="i">
          <div class="field"><label>Market</label><input type="text" v-model="loc.code" placeholder="ja" /></div>
          <div class="field"><label>Approved</label><textarea rows="2" v-model="loc.approved"></textarea></div>
          <div class="field"><label>Disallowed</label><textarea rows="2" v-model="loc.disallowed"></textarea></div>
          <button type="button" @click="form.locales.splice(i, 1)" aria-label="Remove market">Remove</button>
        </div>
        <div class="toolbar">
          <button type="button" @click="addLocale(form)">Add market</button>
          <label for="r-cross">Another market's name on a page:</label>
          <select id="r-cross" v-model="form.cross_market">
            <option value="off">Ignore</option><option value="low">Low severity</option>
            <option value="medium">Medium severity</option><option value="high">High severity</option>
          </select>
        </div>
      </fieldset>
    </div>
  `,
};

const Sandbox = {
  components: { Highlighted },
  props: { rule: Object, form: Object },
  setup(props) {
    const text = ref("At pfizer we work with Phizer. Pfizer's PFIZER and Pfzier. Visit www.pfizer.com or @pfizer.");
    const language = ref("");
    const result = ref(null);
    const error = ref(null);
    const busy = ref(false);
    const run = async (request) => {
      busy.value = true;
      error.value = null;
      try { result.value = await request(); } catch (e) { error.value = e.message; result.value = null; }
      finally { busy.value = false; }
    };
    const checkText = () => run(() => api.post(`/rules/${props.rule.id}/test`, {
      text: text.value, language: language.value || null,
      config: toConfig(props.form), severity: props.form.severity,
    }));
    const checkFile = (event) => {
      const file = event.target.files[0];
      if (!file) return;
      const body = new FormData();
      body.append("file", file);
      body.append("config", JSON.stringify(toConfig(props.form)));
      if (language.value) body.append("language", language.value);
      run(async () => {
        const response = await fetch(`/api/rules/${props.rule.id}/test-file`, { method: "POST", body });
        const data = await response.json();
        if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Could not check the file");
        return data;
      });
      event.target.value = "";
    };
    return { text, language, result, error, busy, checkText, checkFile, LANGUAGES, FINDING_KINDS };
  },
  template: `
    <p class="muted">Uses the settings in the form, including unsaved changes, so you can try them before saving.</p>
    <div class="field"><label for="sb-text">Text</label>
      <textarea id="sb-text" rows="4" v-model="text" class="prose"></textarea></div>
    <div class="toolbar">
      <select v-model="language" aria-label="Language of the text">
        <option v-for="(label, code) in LANGUAGES" :key="code" :value="code">{{ label }}</option>
      </select>
      <button class="primary" :disabled="busy" @click="checkText">Check text</button>
      <label class="button">Check a PDF…<input type="file" accept="application/pdf,.pdf" hidden @change="checkFile" /></label>
    </div>
    <p v-if="error" class="error-text">{{ error }}</p>
    <div v-if="result" class="card section">
      <p><strong>{{ result.matches }}</strong> finding(s) in {{ result.segments_checked }} piece(s) of text.</p>
      <p v-for="n in result.notes" :key="n" class="banner">{{ n }}</p>
      <div v-for="(s, i) in result.segments" :key="i" class="tested">
        <div class="muted small" v-if="s.source !== 'pasted'">{{ s.source }}<span v-if="s.page"> · page {{ s.page }}</span></div>
        <div class="prose"><Highlighted :text="s.text" :matches="s.matches" /></div>
        <ul class="plain small">
          <li v-for="(m, j) in s.matches" :key="j">
            <span class="pill" :class="m.status === 'violation' ? 'bad' : 'warn'">{{ FINDING_KINDS[m.kind] || m.kind }}</span>
            “{{ m.matched }}” → {{ m.expected }} <span class="muted">· {{ m.note }} · {{ m.severity }}</span>
          </li>
        </ul>
      </div>
    </div>
  `,
};

const RuleEditor = {
  components: { RuleForm, Sandbox },
  props: { ruleId: Number },
  setup(props) {
    const rule = ref(null);
    const form = ref(null);
    const tab = ref("settings");
    const yaml = ref("");
    const versions = ref([]);
    const notice = ref(null);
    const error = ref(null);
    const saving = ref(false);
    const load = async () => {
      rule.value = await api.get(`/rules/${props.ruleId}`);
      form.value = toForm(rule.value);
    };
    const save = async () => {
      saving.value = true;
      error.value = notice.value = null;
      try {
        rule.value = await api.put(`/rules/${props.ruleId}`, {
          name: form.value.name, severity: form.value.severity, enabled: form.value.enabled,
          config: toConfig(form.value),
        });
        form.value = toForm(rule.value);
        notice.value = `Saved as version ${rule.value.version}. Re-evaluate a crawl to apply it to crawled text.`;
      } catch (e) {
        error.value = e.message;
      } finally {
        saving.value = false;
      }
    };
    watch(tab, async (t) => {
      if (t === "yaml") yaml.value = await (await fetch(`/api/brands/${rule.value.brand_id}/rules.yaml`)).text();
      if (t === "history") versions.value = await api.get(`/rules/${props.ruleId}/versions`);
    });
    load();
    return { rule, form, tab, yaml, versions, notice, error, saving, save, formatTime };
  },
  template: `
    <p><a href="#/rules">← All rules</a></p>
    <template v-if="rule && form">
      <div class="title-row">
        <h2 class="page-title">{{ rule.name }}</h2>
        <span class="pill">{{ rule.key }} · version {{ rule.version }}</span>
        <span class="pill" :class="rule.enabled ? 'ok' : ''">{{ rule.enabled ? 'Active' : 'Off' }}</span>
      </div>
      <div class="tabs" role="tablist">
        <button role="tab" :class="{ active: tab === 'settings' }" @click="tab = 'settings'">Settings</button>
        <button role="tab" :class="{ active: tab === 'test' }" @click="tab = 'test'">Test</button>
        <button role="tab" :class="{ active: tab === 'yaml' }" @click="tab = 'yaml'">YAML</button>
        <button role="tab" :class="{ active: tab === 'history' }" @click="tab = 'history'">History</button>
      </div>
      <template v-if="tab === 'settings'">
        <RuleForm :form="form" />
        <p v-if="error" class="error-text section">{{ error }}</p>
        <p v-if="notice" class="notice section">{{ notice }}</p>
        <div class="toolbar section"><button class="primary" :disabled="saving" @click="save">Save as new version</button></div>
      </template>
      <Sandbox v-else-if="tab === 'test'" :rule="rule" :form="form" />
      <template v-else-if="tab === 'yaml'">
        <div class="toolbar"><a class="button" :href="'/api/brands/' + rule.brand_id + '/rules.yaml'" download>Download YAML</a>
          <span class="muted">Read-only. Edit the rule in Settings.</span></div>
        <pre class="yaml">{{ yaml }}</pre>
      </template>
      <div v-else class="table-wrap">
        <table>
          <thead><tr><th>Version</th><th>Saved</th><th>Severity</th><th>Active</th><th>Misspellings listed</th></tr></thead>
          <tbody><tr v-for="v in versions" :key="v.version">
            <td>{{ v.version }}</td><td>{{ formatTime(v.created_at) }}</td><td>{{ v.severity }}</td>
            <td>{{ v.enabled ? 'yes' : 'no' }}</td><td class="small">{{ v.config.disallowed.join(', ') }}</td>
          </tr></tbody>
        </table>
      </div>
    </template>
  `,
};

const RuleList = {
  setup() {
    const brands = ref([]);
    const load = async () => {
      const all = await api.get("/brands");
      brands.value = await Promise.all(all.map(async (b) => ({ ...b, rules: await api.get(`/brands/${b.id}/rules`) })));
    };
    load();
    const open = (id) => (window.location.hash = `#/rules/${id}`);
    return { brands, open };
  },
  template: `
    <div v-for="b in brands" :key="b.id" class="card section">
      <h2>{{ b.name }}</h2>
      <table><tbody>
        <tr v-for="r in b.rules" :key="r.id" class="clickable" @click="open(r.id)">
          <td><a :href="'#/rules/' + r.id" @click.stop>{{ r.name }}</a><div class="muted small">{{ r.key }} · version {{ r.version }}</div></td>
          <td>{{ r.config.canonical }} <span class="muted small">({{ r.config.allowed_casings.join(', ') }})</span></td>
          <td><span class="pill" :class="r.enabled ? 'ok' : ''">{{ r.enabled ? 'Active' : 'Off' }}</span></td>
          <td>{{ r.severity }}</td>
        </tr>
      </tbody></table>
    </div>
  `,
};

export default {
  components: { RuleList, RuleEditor },
  props: { system: Object, param: String },
  template: `
    <RuleEditor v-if="param" :rule-id="Number(param)" :key="param" />
    <RuleList v-else />
  `,
};
