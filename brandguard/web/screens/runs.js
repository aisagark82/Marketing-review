import { api, formatTime } from "../api.js";

const { ref, onMounted, onBeforeUnmount } = Vue;

const STATUS_CLASS = {
  queued: "",
  running: "warn",
  completed: "ok",
  failed: "bad",
  cancelled: "",
  interrupted: "bad",
};
const ACTIVE = new Set(["queued", "running"]);

export default {
  props: { system: Object },
  setup() {
    const runs = ref([]);
    const error = ref(null);
    const starting = ref(false);
    const watchers = new Map();

    const upsert = (run) => {
      const index = runs.value.findIndex((r) => r.id === run.id);
      if (index === -1) runs.value.unshift(run);
      else runs.value[index] = run;
      if (!ACTIVE.has(run.status)) unwatch(run.id);
    };

    const watch = (run) => {
      if (!ACTIVE.has(run.status) || watchers.has(run.id)) return;
      watchers.set(run.id, api.watchRun(run.id, upsert));
    };

    const unwatch = (id) => {
      watchers.get(id)?.close();
      watchers.delete(id);
    };

    const load = async () => {
      try {
        runs.value = await api.get("/runs");
        runs.value.forEach(watch);
        error.value = null;
      } catch (e) {
        error.value = e.message;
      }
    };

    const startSelftest = async () => {
      starting.value = true;
      try {
        const run = await api.post("/runs", { kind: "selftest" });
        upsert(run);
        watch(run);
      } catch (e) {
        error.value = e.message;
      } finally {
        starting.value = false;
      }
    };

    const cancel = async (run) => {
      try {
        upsert(await api.post(`/runs/${run.id}/cancel`));
      } catch (e) {
        error.value = e.message;
      }
    };

    const percent = (run) => (run.total ? Math.round((100 * run.done) / run.total) : 0);

    onMounted(load);
    onBeforeUnmount(() => [...watchers.keys()].forEach(unwatch));

    return { runs, error, starting, startSelftest, cancel, percent, formatTime, STATUS_CLASS, ACTIVE };
  },
  template: `
    <div class="toolbar">
      <button class="primary" :disabled="starting" @click="startSelftest">Run self-test</button>
      <span class="muted">Checks the database, file storage and background worker end to end.</span>
    </div>
    <div v-if="system && !system.worker.online" class="banner">
      The worker is offline, so new runs will wait in the queue until it starts.
    </div>
    <p v-if="error" class="error-text">{{ error }}</p>

    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>#</th><th>Type</th><th>Status</th><th>Progress</th><th>Details</th><th>Started</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-if="!runs.length"><td colspan="7" class="muted">No runs yet.</td></tr>
          <tr v-for="run in runs" :key="run.id">
            <td>{{ run.id }}</td>
            <td>{{ run.kind }}</td>
            <td><span class="pill" :class="STATUS_CLASS[run.status]">{{ run.status }}</span></td>
            <td>
              <div class="progress" :title="percent(run) + '%'"><div :style="{ width: percent(run) + '%' }"></div></div>
            </td>
            <td>
              <div>{{ run.message || '—' }}</div>
              <div v-if="run.error" class="error-text">{{ run.error }}</div>
            </td>
            <td class="muted">{{ formatTime(run.started_at || run.created_at) }}</td>
            <td>
              <button v-if="ACTIVE.has(run.status)" :disabled="run.cancel_requested" @click="cancel(run)">
                {{ run.cancel_requested ? 'Cancelling…' : 'Cancel' }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  `,
};
