// Open collapsed content (accordions, disclosure widgets) without leaving the page.
// <details> are opened directly; aria-expanded toggles are clicked while link clicks are
// cancelled, and buttons that would submit a form are never clicked. Returns how many opened.
async () => {
  const MAX_TOGGLES = 50;
  const cancelLinks = (event) => {
    if (event.target.closest && event.target.closest("a[href]")) event.preventDefault();
  };
  document.addEventListener("click", cancelLinks, true);
  let opened = 0;
  for (const details of document.querySelectorAll("details:not([open])")) {
    details.open = true;
    opened++;
  }
  const toggles = [...document.querySelectorAll('[aria-expanded="false"]')]
    .filter((el) => {
      const submitsForm = el.tagName === "BUTTON" && el.type === "submit" && el.form;
      const isButton =
        (el.tagName === "BUTTON" && !submitsForm) || el.getAttribute("role") === "button";
      return isButton && (!el.checkVisibility || el.checkVisibility());
    })
    .slice(0, MAX_TOGGLES);
  for (const el of toggles) {
    try {
      el.click();
      opened++;
    } catch {
      /* a broken widget shouldn't stop the capture */
    }
  }
  await new Promise((resolve) => setTimeout(resolve, 400));
  document.removeEventListener("click", cancelLinks, true);
  return opened;
};
