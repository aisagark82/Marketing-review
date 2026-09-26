import { api, formatTime } from "../api.js";
import { ACTIVE_RUN, CRAWLERS, RUN_KINDS, RUN_STATUS_CLASS as STATUS_CLASS } from "../labels.js";
import RunDetail, { AssetView } from "./run-detail.js";

const { ref, computed, onMounted, onBeforeUnmount } = Vue;

const RunList = {
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
      if (!ACTIVE_RUN.has(run.status)) unwatch(run.id);
    };

    const watch = (run) => {
      if (!ACTIVE_RUN.has(run.status) || watchers.has(run.id)) return;
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

    const open = (run) => (location.hash = `#/runs/${run.id}`);

    return {
      runs, error, starting, startSelftest, cancel, percent, formatTime, open,
      STATUS_CLASS, ACTIVE_RUN, RUN_KINDS, CRAWLERS,
    };
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
          <tr v-for="run in runs" :key="run.id" class="clickable" @click="open(run)">
            <td><a :href="'#/runs/' + run.id" @click.stop>{{ run.id }}</a></td>
            <td>
              {{ RUN_KINDS[run.kind] || run.kind }}
              <span v-if="run.params?.crawler" class="muted"> · {{ CRAWLERS[run.params.crawler]?.label }}</span>
              <div v-if="run.site_name"><a :href="'#/sites/' + run.site_id" class="small" @click.stop>{{ run.site_name }}</a></div>
            </td>
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
              <button v-if="ACTIVE_RUN.has(run.status)" :disabled="run.cancel_requested" @click.stop="cancel(run)">
                {{ run.cancel_requested ? 'Cancelling…' : 'Cancel' }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  `,
};

// #/runs, #/runs/12 (a run) or #/runs/12/assets/34 (a crawled page)
export default {
  components: { RunList, RunDetail, AssetView },
  props: { system: Object, param: String },
  setup(props) {
    const parts = computed(() => (props.param || "").split("/").filter(Boolean));
    const runId = computed(() => Number(parts.value[0]) || null);
    const assetId = computed(() => (parts.value[1] === "assets" ? Number(parts.value[2]) : null));
    return { runId, assetId };
  },
  template: `
    <AssetView v-if="assetId" :run-id="runId" :asset-id="assetId" :key="'a' + assetId" />
    <RunDetail v-else-if="runId" :run-id="runId" :key="'r' + runId" />
    <RunList v-else :system="system" />
  `,
};
