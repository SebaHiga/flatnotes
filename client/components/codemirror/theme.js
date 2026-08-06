import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { EditorView } from "@codemirror/view";
import { tags } from "@lezer/highlight";

// Colours are read from the app's existing --theme-* CSS custom properties
// (see client/style.css), so this automatically follows the light/dark
// toggle without any JS-side dark-mode logic of its own.
export const editorTheme = EditorView.theme({
  "&": {
    height: "100%",
    color: "rgb(var(--theme-text))",
    backgroundColor: "rgb(var(--theme-background))",
  },
  "&.cm-focused": {
    outline: "none",
  },
  ".cm-content": {
    fontFamily: "Poppins, sans-serif",
    fontSize: "1rem",
    padding: "1rem 0 0 0",
    caretColor: "rgb(var(--theme-text))",
  },
  ".cm-line": {
    padding: "0 1rem",
  },
  ".cm-scroller": {
    lineHeight: "1.6rem",
  },
  "&.cm-focused .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection":
    {
      backgroundColor: "rgb(var(--theme-brand) / 0.3)",
    },
  ".cm-cursor, .cm-dropCursor": {
    borderLeftColor: "rgb(var(--theme-text))",
  },
  ".cm-activeLine": {
    backgroundColor: "rgb(var(--theme-background-elevated))",
  },
  ".cm-panels": {
    backgroundColor: "rgb(var(--theme-background-elevated))",
    color: "rgb(var(--theme-text))",
  },
  ".cm-panels.cm-panels-bottom": {
    borderTop: "1px solid rgb(var(--theme-border))",
  },
  ".cm-vim-panel": {
    padding: "2px 1rem",
  },
  ".cm-vim-panel input": {
    color: "rgb(var(--theme-text))",
    backgroundColor: "transparent",
    fontFamily: "Consolas, 'Lucida Console', Monaco, 'Andale Mono', monospace",
  },
  ".cm-searchMatch": {
    backgroundColor: "rgb(var(--theme-brand) / 0.25)",
  },
  ".cm-searchMatch-selected": {
    backgroundColor: "rgb(var(--theme-brand) / 0.5)",
  },
});

const monospaceFont =
  "Consolas, 'Lucida Console', Monaco, 'Andale Mono', monospace";

export const markdownHighlightStyle = HighlightStyle.define([
  { tag: tags.heading1, fontWeight: "bold", fontSize: "1.75rem" },
  { tag: tags.heading2, fontWeight: "bold", fontSize: "1.6rem" },
  { tag: tags.heading3, fontWeight: "bold", fontSize: "1.45rem" },
  { tag: tags.heading4, fontWeight: "bold", fontSize: "1.3rem" },
  { tag: tags.heading5, fontWeight: "bold", fontSize: "1.15rem" },
  { tag: tags.heading6, fontWeight: "bold", fontSize: "1rem" },
  { tag: tags.strong, fontWeight: "bold" },
  { tag: tags.emphasis, fontStyle: "italic" },
  { tag: tags.strikethrough, textDecoration: "line-through" },
  {
    tag: tags.link,
    color: "rgb(var(--theme-brand))",
    textDecoration: "underline",
  },
  { tag: tags.url, color: "rgb(var(--theme-brand))" },
  {
    tag: [tags.monospace, tags.processingInstruction],
    fontFamily: monospaceFont,
    backgroundColor: "rgb(var(--theme-background-elevated))",
  },
  { tag: tags.quote, color: "rgb(var(--theme-text-muted))" },
  { tag: tags.meta, color: "rgb(var(--theme-text-very-muted))" },
]);

export const editorExtensions = [editorTheme, syntaxHighlighting(markdownHighlightStyle)];
