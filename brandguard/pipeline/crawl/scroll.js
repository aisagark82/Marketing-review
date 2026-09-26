// Scroll down in screen-sized steps to trigger lazy-loaded sections, then return to the top.
async () => {
  const MAX_STEPS = 15;
  const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  for (let i = 0; i < MAX_STEPS; i++) {
    if (scrollY + innerHeight >= document.documentElement.scrollHeight) break;
    scrollBy(0, innerHeight);
    await pause(150);
  }
  scrollTo(0, 0);
  await pause(200);
};
