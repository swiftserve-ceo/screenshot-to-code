// Host side of the preview <-> host channel. The preview iframe is sandboxed
// without "allow-same-origin", so this postMessage channel (with strict
// source/shape validation) is the only link between them. See preview-bridge.js.
import bridgeSource from "./preview-bridge.js?raw";

export const PREVIEW_HOST_SOURCE = "s2c-host";
export const PREVIEW_SOURCE = "s2c-preview";

// Sandbox tokens: everything the previewed page needs to render and be
// interactive, but NOT "allow-same-origin" (which would let it reach the host
// origin / storage) and NOT "allow-top-navigation" (which would let it navigate
// the whole tab).
export const PREVIEW_SANDBOX =
  "allow-scripts allow-forms allow-modals allow-popups allow-popups-to-escape-sandbox";

export interface SelectedElement {
  tagName: string;
  outerHTML: string;
  context: string;
}

export type PreviewInboundMessage =
  | { source: typeof PREVIEW_SOURCE; type: "ready" }
  | { source: typeof PREVIEW_SOURCE; type: "selected"; element: SelectedElement }
  | { source: typeof PREVIEW_SOURCE; type: "exitSelectMode" };

const BRIDGE_TAG = `<script data-s2c-bridge>${bridgeSource}</script>`;

// Insert the bridge as the first thing in <head> (or before the first script, or
// at the top of the document) so it installs its capture-phase listeners before
// the generated page's own scripts run.
export function injectPreviewBridge(html: string): string {
  if (!html) return html;
  if (html.includes("data-s2c-bridge")) return html;
  if (/<head[^>]*>/i.test(html)) {
    return html.replace(/<head[^>]*>/i, (m) => `${m}${BRIDGE_TAG}`);
  }
  if (/<html[^>]*>/i.test(html)) {
    return html.replace(/<html[^>]*>/i, (m) => `${m}${BRIDGE_TAG}`);
  }
  return BRIDGE_TAG + html;
}

export function isPreviewMessage(
  event: MessageEvent,
  expectedSource: Window | null | undefined
): event is MessageEvent<PreviewInboundMessage> {
  return (
    !!expectedSource &&
    event.source === expectedSource &&
    typeof event.data === "object" &&
    event.data !== null &&
    (event.data as { source?: unknown }).source === PREVIEW_SOURCE
  );
}

export function postToPreview(
  iframe: HTMLIFrameElement | null,
  message: { type: "setSelectMode"; enabled: boolean } | { type: "clearSelection" }
): void {
  iframe?.contentWindow?.postMessage({ source: PREVIEW_HOST_SOURCE, ...message }, "*");
}
