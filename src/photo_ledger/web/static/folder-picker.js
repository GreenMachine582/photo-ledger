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
})();
