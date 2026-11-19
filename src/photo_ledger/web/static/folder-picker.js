// The folder fields' "Browse folders": picking a folder in the tree fills the field above it.
// gth-ui's tree.js fires "change" on the tree when its selection changes.
(() => {
  document.addEventListener("change", (event) => {
    const tree = event.target;
    if (!(tree instanceof Element) || !tree.matches("[data-gth-tree]")) return;
    const browse = tree.closest("[data-folder-for]");
    const field = browse && document.getElementById(browse.dataset.folderFor);
    const picked = tree.querySelector("[role=treeitem][aria-selected=true]");
    if (!field || !picked) return;
    field.value = picked.getAttribute("data-gth-node");
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });

  // Explorer's "Copy as path" wraps the path in quotes: drop them as it's pasted. The server
  // drops them too, so this only keeps the field showing the path that will be used.
  document.addEventListener("paste", (event) => {
    const field = event.target;
    if (!(field instanceof HTMLInputElement) || !field.id) return;
    if (!document.querySelector(`[data-folder-for="${CSS.escape(field.id)}"]`)) return;
    setTimeout(() => {
      const text = field.value.trim();
      const quoted = text.length >= 2 && text[0] === text.at(-1) && `"'`.includes(text[0]);
      if (quoted) field.value = text.slice(1, -1).trim();
    });
  });
})();
