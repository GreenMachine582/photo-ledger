// Keyboard actions for the comparison view: A keep left, D keep right, B keep both, S skip,
// Z undo. Each key submits the form of the button carrying its data-key.
(() => {
  document.addEventListener("keydown", (event) => {
    if (event.ctrlKey || event.metaKey || event.altKey || event.repeat) return;
    const target = event.target;
    if (target instanceof Element && target.closest("input, textarea, select, [contenteditable]")) {
      return;
    }
    const button = document.querySelector(`button[data-key="${event.key.toUpperCase()}"]`);
    if (!button || button.disabled) return;
    event.preventDefault();
    button.disabled = true; // one decision per key press
    if (button.form) {
      button.form.requestSubmit();
    } else {
      button.click();
    }
  });
})();
