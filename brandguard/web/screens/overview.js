import { formatTime } from "../api.js";

export default {
  props: { system: Object },
  setup() {
    return { formatTime };
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
          Compliance results for www.pfizer.com will appear here once sites, crawling and rules are
          built. To check that everything is wired up, open <a href="#/runs">Runs</a> and start a self-test.
        </p>
      </div>
    </template>
  `,
};
