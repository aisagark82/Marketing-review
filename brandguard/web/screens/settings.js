import { api } from "../api.js";

const { ref, onMounted } = Vue;

export default {
  props: { system: Object, param: String },
  setup() {
    const form = ref(null);
    const profiles = ref({});
    const saving = ref(false);
    const message = ref(null);
    const error = ref(null);

    onMounted(async () => {
      try {
        [form.value, profiles.value] = await Promise.all([
          api.get("/settings"),
          api.get("/settings/profiles"),
        ]);
      } catch (e) {
        error.value = e.message;
      }
    });

    const save = async () => {
      saving.value = true;
      message.value = error.value = null;
      try {
        form.value = await api.put("/settings", form.value);
        message.value = "Saved. A new performance profile applies the next time you run brandguard start.";
      } catch (e) {
        error.value = e.message;
      } finally {
        saving.value = false;
      }
    };

    return { form, profiles, saving, message, error, save };
  },
  template: `
    <div v-if="!form && !error" class="muted">Loading…</div>
    <p v-if="error" class="error-text">{{ error }}</p>
    <form v-if="form" class="form" @submit.prevent="save">
      <div class="field">
        <label>Performance profile</label>
        <div class="radio-cards">
          <label v-for="(p, id) in profiles" :key="id" class="radio-card"
                 :class="{ selected: form.performance_profile === id }">
            <input type="radio" name="profile" :value="id" v-model="form.performance_profile" />
            <div class="title">{{ p.label }}</div>
            <div class="desc">{{ p.description }}</div>
            <div class="desc">{{ p.processing_workers }} processing worker(s)</div>
          </label>
        </div>
      </div>

      <div class="field">
        <label for="contact">Crawler contact email (optional)</label>
        <input id="contact" type="email" v-model.trim="form.crawler_contact_email" placeholder="you@example.com" />
        <div class="hint">Included in the crawler's User-Agent so site operators can reach you.</div>
      </div>

      <div class="card">
        <h2>Gemini</h2>
        <p class="muted">API key, model (gemini-2.5-flash) and connection test arrive in build step 6.</p>
      </div>

      <div class="toolbar">
        <button class="primary" type="submit" :disabled="saving">Save settings</button>
        <span v-if="message" class="muted">{{ message }}</span>
      </div>
    </form>
  `,
};
