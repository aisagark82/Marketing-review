// Small chart pieces (design guidance: one hue for magnitude, thin bars with a rounded
// data end, the value at the tip, a hover tooltip, text in text colours).

const { ref, computed } = Vue;

export const BarList = {
  props: {
    items: { type: Array, required: true }, // [[label, value], ...]
    unit: { type: String, default: "" },
    empty: { type: String, default: "None" },
  },
  setup(props) {
    const hover = ref(null);
    const max = computed(() => Math.max(1, ...props.items.map(([, v]) => v)));
    const total = computed(() => props.items.reduce((sum, [, v]) => sum + v, 0));
    const tip = (item) => {
      const share = total.value ? Math.round((100 * item[1]) / total.value) : 0;
      return `${item[0]}: ${item[1].toLocaleString()}${props.unit} (${share}% of ${total.value.toLocaleString()})`;
    };
    return { hover, max, tip };
  },
  template: `
    <p v-if="!items.length" class="muted">{{ empty }}</p>
    <ul v-else class="bars" role="list">
      <li v-for="item in items" :key="item[0]" @mouseenter="hover = item[0]" @mouseleave="hover = null"
          @focus="hover = item[0]" @blur="hover = null" tabindex="0" :aria-label="tip(item)">
        <span class="bar-label">{{ item[0] }}</span>
        <span class="bar-track">
          <span class="bar-fill" :style="{ width: (100 * item[1] / max) + '%' }"></span>
          <span class="bar-value">{{ item[1].toLocaleString() }}{{ unit }}</span>
        </span>
        <span v-if="hover === item[0]" class="bar-tip" role="tooltip">{{ tip(item) }}</span>
      </li>
    </ul>
  `,
};

export const StatTile = {
  props: { label: String, value: [String, Number], detail: String, hero: Boolean },
  template: `
    <div class="card stat" :class="{ hero }">
      <div class="label">{{ label }}</div>
      <div class="value">{{ value ?? '—' }}</div>
      <div v-if="detail" class="muted small">{{ detail }}</div>
    </div>
  `,
};
