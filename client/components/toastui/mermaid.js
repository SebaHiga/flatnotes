// Dynamically imported so notes without any mermaid diagrams don't pay for
// mermaid's (fairly large) runtime on every note view.
let mermaidPromise;
function loadMermaid() {
  if (!mermaidPromise) {
    mermaidPromise = import("mermaid").then((module) => module.default);
  }
  return mermaidPromise;
}

function isDarkThemeOn() {
  return document.body.classList.contains("dark");
}

// mermaid.initialize() is cheap and only affects diagrams rendered after
// it's called, so it's safe (and necessary) to call before every render to
// pick up the current theme.
function configureTheme(mermaid) {
  mermaid.initialize({
    startOnLoad: false,
    securityLevel: "strict",
    theme: isDarkThemeOn() ? "dark" : "default",
  });
}

// Renders any not-yet-rendered `.mermaid` blocks inside the given container.
// Safe to call repeatedly (e.g. on every editor change) since already
// rendered diagrams are skipped.
export function renderMermaidDiagrams(container) {
  if (!container) {
    return;
  }
  // Nodes hidden by a hidden ancestor (e.g. TOAST UI's Write/Preview tabs
  // keep the inactive pane in the DOM with display:none) are skipped rather
  // than rendered: mermaid can't measure text layout in a hidden container,
  // so it fails, swaps in its own "Syntax error" placeholder SVG, and still
  // marks the node processed — permanently hiding the real diagram once the
  // container becomes visible again. Left unprocessed, a later render call
  // (e.g. when the tab becomes active) will pick them up correctly.
  const nodes = Array.from(
    container.querySelectorAll("div.mermaid:not([data-processed])"),
  ).filter((node) => node.offsetParent !== null);
  if (nodes.length === 0) {
    return;
  }
  // mermaid.run() replaces each node's contents with the rendered SVG, so
  // the original diagram source has to be saved separately if it's ever
  // going to be re-rendered (e.g. after a theme change).
  nodes.forEach((node) => {
    node.dataset.mermaidSource = node.textContent;
  });
  loadMermaid().then((mermaid) => {
    configureTheme(mermaid);
    // Nodes still attached and unprocessed? A fast edit/navigation could
    // have already removed or re-rendered them while mermaid was loading.
    const pendingNodes = nodes.filter(
      (node) => node.isConnected && !node.dataset.processed,
    );
    if (pendingNodes.length === 0) {
      return;
    }
    mermaid.run({ nodes: pendingNodes }).catch((error) => {
      console.error("Failed to render mermaid diagram(s):", error);
    });
  });
}

// Forces every diagram inside the container to be redrawn, e.g. after a
// theme change. mermaid.run() skips nodes it already processed, so the
// marker attribute it uses to track that has to be cleared first.
export function rerenderMermaidDiagrams(container) {
  if (!container) {
    return;
  }
  container.querySelectorAll("div.mermaid[data-processed]").forEach((node) => {
    node.removeAttribute("data-processed");
    node.textContent = node.dataset.mermaidSource;
  });
  renderMermaidDiagrams(container);
}
