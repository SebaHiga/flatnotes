import { Vim } from "@replit/codemirror-vim";

// Vim.defineEx registers ex-commands on the shared, module-global vim
// singleton (there is only ever one, regardless of how many EditorViews use
// it), so we register flatnotes' :w / :wq / :x / :q handlers exactly once
// and dispatch to whichever editor instance is actually live via a WeakMap
// keyed by EditorView.
let commandsRegistered = false;
const instanceHandlers = new WeakMap();

function dispatch(cm, handlerName) {
  const handlers = instanceHandlers.get(cm.cm6);
  handlers?.[handlerName]?.();
}

function registerCommandsOnce() {
  if (commandsRegistered) return;
  commandsRegistered = true;

  Vim.defineEx("write", "w", (cm) => dispatch(cm, "save"));
  Vim.defineEx("wq", "wq", (cm) => dispatch(cm, "saveAndClose"));
  Vim.defineEx("xit", "x", (cm) => dispatch(cm, "saveAndClose"));
  Vim.defineEx("quit", "q", (cm) => dispatch(cm, "quit"));
}

// handlers: { save, saveAndClose, quit }
export function registerVimInstance(view, handlers) {
  registerCommandsOnce();
  instanceHandlers.set(view, handlers);
}

export function unregisterVimInstance(view) {
  instanceHandlers.delete(view);
}
