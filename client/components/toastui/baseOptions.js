import codeSyntaxHighlight from "@toast-ui/editor-plugin-code-syntax-highlight/dist/toastui-editor-plugin-code-syntax-highlight-all.js";
import router from "../../router.js";
import { attachmentUrlPrefix } from "../../constants.js";

const customHTMLRenderer = {
  // Render ```mermaid fenced code blocks as diagrams instead of plain code.
  // The container is left for mermaid.js (see mermaid.js) to fill in with an
  // SVG after the surrounding HTML has been mounted into the DOM.
  codeBlock(node, { origin }) {
    const language = node.info?.trim().split(/\s+/)[0]?.toLowerCase();
    if (language !== "mermaid") {
      return origin();
    }
    return [
      { type: "openTag", tagName: "div", classNames: ["mermaid"] },
      { type: "text", content: node.literal },
      { type: "closeTag", tagName: "div" },
    ];
  },
  // Add id attribute to headings
  heading(node, { entering, getChildrenText, origin }) {
    const original = origin();
    if (entering) {
      original.attributes = {
        id: getChildrenText(node)
          .toLowerCase()
          .replace(/[^a-z0-9-\s]*/g, "")
          .trim()
          .replace(/\s/g, "-"),
      };
    }
    return original;
  },
  // Convert relative hash links to absolute links
  link(_, { entering, origin }) {
    const original = origin();
    if (entering) {
      const href = original.attributes.href;
      if (href.startsWith("#")) {
        const targetRoute = {
          ...router.currentRoute.value,
          hash: href,
        };
        original.attributes.href = router.resolve(targetRoute).href;
      } else if (href.startsWith(attachmentUrlPrefix)) {
        // Open attachment links (e.g. uploaded PDFs) in a new tab so a
        // single click doesn't navigate away from the note.
        original.attributes.target = "_blank";
        original.attributes.rel = "noopener noreferrer";
      }
    }
    return original;
  },
};

const baseOptions = {
  height: "100%",
  plugins: [codeSyntaxHighlight],
  customHTMLRenderer: customHTMLRenderer,
  usageStatistics: false,
};

export default baseOptions;
