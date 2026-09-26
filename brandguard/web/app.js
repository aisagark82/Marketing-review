import { api } from "./api.js";
import ComplianceScreen from "./screens/compliance.js";
import FindingsScreen from "./screens/findings.js";
import OverviewScreen from "./screens/overview.js";
import PlaceholderScreen from "./screens/placeholder.js";
import RunsScreen from "./screens/runs.js";
import RulesScreen from "./screens/rules.js";
import SettingsScreen from "./screens/settings.js";
import SitesScreen from "./screens/sites.js";

const { createApp, ref, computed, onMounted, onBeforeUnmount } = Vue;

// `step` marks screens that arrive in a later Phase 0 build step.
const ROUTES = [
  { id: "overview", label: "Overview", component: OverviewScreen },
  { id: "compliance", label: "Compliance", component: ComplianceScreen },
  { id: "findings", label: "Findings", component: FindingsScreen },
  { id: "runs", label: "Runs", component: RunsScreen },
  { id: "sites", label: "Sites", component: SitesScreen },
  { id: "rules", label: "Rules", component: RulesScreen },
  { id: "settings", label: "Settings", component: SettingsScreen },
];

const SYSTEM_POLL_MS = 5000;

const App = {
  setup() {
    const currentId = ref("overview");
    const param = ref(null); // e.g. "1" in #/sites/1
    const system = ref(null);
    const systemError = ref(null);
    let timer = null;

    const syncRoute = () => {
      const [id, ...rest] = location.hash.replace(/^#\/?/, "").split("/");
      currentId.value = ROUTES.some((r) => r.id === id) ? id : "overview";
      param.value = rest.join("/") || null;
    };

    const loadSystem = async () => {
      try {
        system.value = await api.get("/system");
        systemError.value = null;
      } catch (error) {
        systemError.value = error.message;
      }
    };

    onMounted(() => {
      syncRoute();
      window.addEventListener("hashchange", syncRoute);
      loadSystem();
      timer = setInterval(loadSystem, SYSTEM_POLL_MS);
    });
    onBeforeUnmount(() => {
      window.removeEventListener("hashchange", syncRoute);
      clearInterval(timer);
    });

    const route = computed(() => ROUTES.find((r) => r.id === currentId.value));
    const workerPill = computed(() => {
      if (systemError.value) return { cls: "bad", text: "Server unreachable" };
      if (!system.value) return { cls: "", text: "Connecting…" };
      return system.value.worker.online
        ? { cls: "ok", text: "Worker online" }
        : { cls: "warn", text: "Worker offline" };
    });

    return { routes: ROUTES, route, param, system, workerPill, PlaceholderScreen };
  },
  template: `
    <div class="layout">
      <nav class="sidebar" aria-label="Main">
        <div class="logo">
          <svg viewBox="0 0 32 32" aria-hidden="true"><path d="M16 2 4 7v8c0 7.5 5.1 13.3 12 15 6.9-1.7 12-7.5 12-15V7z"/></svg>
          BrandGuard
        </div>
        <a v-for="r in routes" :key="r.id" :href="'#/' + r.id"
           class="nav-link" :class="{ active: r.id === route.id }">
          <span>{{ r.label }}</span>
          <span v-if="r.step" class="soon">step {{ r.step }}</span>
        </a>
        <div class="sidebar-footer" v-if="system">v{{ system.version }}</div>
      </nav>
      <div class="main">
        <header class="topbar">
          <h1>{{ route.label }}</h1>
          <span class="pill" :class="workerPill.cls">{{ workerPill.text }}</span>
        </header>
        <main class="content">
          <component v-if="route.component" :is="route.component" :system="system" :param="param" />
          <component v-else :is="PlaceholderScreen" :route="route" />
        </main>
      </div>
    </div>
  `,
};

createApp(App).mount("#app");
