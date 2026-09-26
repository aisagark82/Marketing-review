import { api } from "../api.js";

const { ref, onMounted } = Vue;

const STORAGE = {
  keychain: "the operating system's keychain (Windows Credential Manager)",
  database: "BrandGuard's local database, because this computer has no keychain",
};

export default {
  setup() {
    const settings = ref(null);
    const key = ref(null);
    const newKey = ref("");
    const models = ref([]);
    const usage = ref(null);
    const test = ref(null);
    const busy = ref("");
    const message = ref(null);
    const error = ref(null);

    const act = async (name, fn) => {
      busy.value = name;
      error.value = message.value = null;
      try { await fn(); } catch (e) { error.value = e.message; } finally { busy.value = ""; }
    };
    const load = async () => {
      const body = await api.get("/ai/settings");
      settings.value = body.settings;
      key.value = body.key;
      usage.value = await api.get("/ai/usage");
    };
    onMounted(() => act("load", load));

    const saveKey = () => act("key", async () => {
      key.value = await api.put("/ai/key", { api_key: newKey.value });
      newKey.value = "";
      message.value = "API key saved.";
    });
    const removeKey = () => act("key", async () => {
      key.value = await (await fetch("/api/ai/key", { method: "DELETE" })).json();
      message.value = "API key removed.";
    });
    const loadModels = () => act("models", async () => { models.value = await api.get("/ai/models"); });
    const runTest = () => act("test", async () => {
      test.value = await api.post("/ai/test");
      usage.value = await api.get("/ai/usage");
    });
    const save = () => act("save", async () => {
      settings.value = await api.put("/ai/settings", settings.value);
      message.value = "Gemini settings saved. They apply to the next crawl or re-evaluation.";
    });
    return { settings, key, newKey, models, usage, test, busy, message, error, saveKey, removeKey,
             loadModels, runTest, save, STORAGE };
  },
  template: `
    <div class="card section" v-if="settings">
      <h2>Gemini</h2>
      <p class="muted">Gemini reviews possible misspellings and, if you allow it, reads text in images.
        Only public page text and images are sent.</p>

      <div class="field">
        <label for="gm-key">API key (Google AI Studio)</label>
        <div class="toolbar">
          <input id="gm-key" type="password" v-model.trim="newKey" autocomplete="off"
                 :placeholder="key?.set ? 'Saved: ' + key.hint + ' (paste a new key to replace it)' : 'Paste your key'" class="grow" />
          <button class="primary" :disabled="newKey.length < 20 || busy === 'key'" @click="saveKey">Save key</button>
          <button v-if="key?.set" :disabled="busy === 'key'" @click="removeKey">Remove</button>
        </div>
        <div class="hint" v-if="key?.set">Stored in {{ STORAGE[key.storage] }}. It is never shown again or sent to the browser.</div>
        <div class="hint" v-else>Create one at aistudio.google.com → Get API key. A paid-tier key is recommended.</div>
      </div>

      <div class="grid-2 section">
        <div class="field">
          <label for="gm-model">Model</label>
          <div class="toolbar">
            <select id="gm-model" v-model="settings.model" class="grow">
              <option v-if="!models.includes(settings.model)" :value="settings.model">{{ settings.model }}</option>
              <option v-for="m in models" :key="m" :value="m">{{ m }}</option>
            </select>
            <button :disabled="!key?.set || busy === 'models'" @click="loadModels">Load models</button>
          </div>
          <div class="hint">gemini-2.5-flash is the default: fast and inexpensive for these short tasks.</div>
        </div>
        <div class="field">
          <label>Connection</label>
          <div class="toolbar">
            <button :disabled="!key?.set || busy === 'test'" @click="runTest">{{ busy === 'test' ? 'Testing…' : 'Test connection' }}</button>
            <span v-if="test" :class="test.ok ? 'notice' : 'error-text'">
              {{ test.ok ? 'Works' : 'Unexpected answer' }} · {{ test.model }} · {{ test.latency_ms }} ms
              · {{ test.input_tokens }} + {{ test.output_tokens }} tokens · {{ test.lines.join(' / ') }}
            </span>
          </div>
        </div>
      </div>

      <fieldset>
        <legend>What Gemini does</legend>
        <label class="check"><input type="checkbox" v-model="settings.review_near_misses" />
          Review possible misspellings after each crawl (confirm, dismiss, or leave for you)</label>
        <label class="check"><input type="checkbox" v-model="settings.read_images" />
          Read text in images (logos, banners): downloads the site's images at the crawl's pace</label>
        <div class="field" v-if="settings.read_images">
          <label for="gm-max">Images per crawl, at most</label>
          <input id="gm-max" type="number" min="0" max="5000" v-model.number="settings.max_images_per_crawl" />
          <div class="hint">Visible images go first. Icons under 48 px are skipped; SVG text is read without Gemini.</div>
        </div>
      </fieldset>

      <fieldset>
        <legend>Limits and cost</legend>
        <div class="grid-2">
          <div class="field"><label for="gm-rpm">Requests per minute</label>
            <input id="gm-rpm" type="number" min="1" v-model.number="settings.requests_per_minute" /></div>
          <div class="field"><label for="gm-day">Requests per day (then Gemini steps pause)</label>
            <input id="gm-day" type="number" min="1" v-model.number="settings.daily_request_limit" /></div>
          <div class="field"><label for="gm-pin">Price per million input tokens (USD)</label>
            <input id="gm-pin" type="number" min="0" step="0.01" v-model.number="settings.price_input_per_million" /></div>
          <div class="field"><label for="gm-pout">Price per million output tokens (USD)</label>
            <input id="gm-pout" type="number" min="0" step="0.01" v-model.number="settings.price_output_per_million" /></div>
        </div>
        <div class="hint">Prices are only used for the estimate below; check Google's current prices for your model.</div>
      </fieldset>

      <div class="toolbar section">
        <button class="primary" :disabled="busy === 'save'" @click="save">Save Gemini settings</button>
        <span v-if="message" class="notice">{{ message }}</span>
      </div>
      <p v-if="error" class="error-text">{{ error }}</p>

      <div v-if="usage" class="section">
        <div class="label">Usage, last 30 days</div>
        <p class="muted small">Today: {{ usage.today_calls }} of {{ usage.daily_limit }} requests ·
          estimated cost over 30 days: {{ usage.total_cost.toFixed(4) }} {{ usage.currency }}</p>
        <table v-if="usage.days.length" class="kv">
          <thead><tr><th>Day</th><th>Requests</th><th>Tokens in / out</th><th>Estimated cost</th><th>For</th></tr></thead>
          <tbody><tr v-for="d in usage.days" :key="d.date">
            <td>{{ d.date }}</td>
            <td>{{ d.calls }}<span v-if="d.failed" class="muted"> ({{ d.failed }} failed)</span></td>
            <td>{{ d.input_tokens.toLocaleString() }} / {{ d.output_tokens.toLocaleString() }}</td>
            <td>{{ d.cost.toFixed(4) }}</td>
            <td class="small">{{ Object.entries(d.stages).map(([s, n]) => s + ' ' + n).join(', ') }}</td>
          </tr></tbody>
        </table>
      </div>
    </div>
  `,
};
