export default {
  props: { route: { type: Object, required: true } },
  template: `
    <div class="card placeholder">
      <h2>{{ route.label }} arrives in build step {{ route.step }}</h2>
      <p>{{ route.about }}</p>
    </div>
  `,
};
