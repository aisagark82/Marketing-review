import { api, formatTime } from "../api.js";
import { READINESS } from "../labels.js";

const { ref, onMounted } = Vue;

export default {
  props: { system: Object, param: String },
  setup() {
    const sites = ref([]);
    onMounted(async () => {
      try {
        sites.value = await api.get("/sites");
      } catch {
        sites.value = [];
      }
    });
    return { formatTime, sites, READINESS };
  },
  template: `
    <div v-if="!system" class="muted">Loading…</div>
    <template v-else>
      <div v-if="!system.worker.online" class="banner">
        The background worker is not running. Start the app with <code>brandguard start</code>,
        which launches both the web server and the worker.
      </div>
      <div class="cards">
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

      <div class="card section">
        <h2>Getting started</h2>
        <p class="muted">
          Before the first crawl, open <a href="#/sites/1">pfizer.com</a> and run the pre-flight check.
          Compliance results will appear here once crawling and rules are built (steps 3–5).
        </p>
      </div>
    </template>
  `,
};
