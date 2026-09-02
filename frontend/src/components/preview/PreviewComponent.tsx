import { useEffect, useRef } from "react";
import classNames from "classnames";
import useThrottle from "../../hooks/useThrottle";
import { useAppStore } from "../../store/app-store";
import { normalizeBabelCdn } from "../../lib/babelCdn";
import {
  injectPreviewBridge,
  isPreviewMessage,
  postToPreview,
  PREVIEW_SANDBOX,
} from "./previewMessaging";

interface Props {
  code: string;
  device: "mobile" | "desktop";
  onScaleChange?: (scale: number) => void;
  viewMode?: "fit" | "actual";
}

const MOBILE_VIEWPORT_WIDTH = 375;
export const DESKTOP_VIEWPORT_WIDTH = 1366;

function PreviewComponent({
  code,
  device,
  onScaleChange,
  viewMode,
}: Props) {
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const wrapperRef = useRef<HTMLDivElement | null>(null);

  // Don't update code more often than every 200ms.
  const throttledCode = useThrottle(code, 200);
  const activeMode = viewMode ?? "fit";

  const { inSelectAndEditMode, selectedElement, setSelectedElement } =
    useAppStore();

  // The preview iframe is sandboxed without "allow-same-origin", so the host
  // cannot read its DOM. Element selection happens entirely inside the injected
  // bridge (preview-bridge.js); here we only listen for its validated messages.
  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (!isPreviewMessage(event, iframeRef.current?.contentWindow)) return;
      const data = event.data;
      if (data.type === "ready") {
        // Re-sync mode after a (re)load of the previewed document.
        postToPreview(iframeRef.current, {
          type: "setSelectMode",
          enabled: useAppStore.getState().inSelectAndEditMode,
        });
      } else if (data.type === "selected") {
        useAppStore.getState().setSelectedElement(data.element);
      } else if (data.type === "exitSelectMode") {
        useAppStore.getState().disableInSelectAndEditMode();
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  // Tell the bridge when select-and-edit mode toggles.
  useEffect(() => {
    postToPreview(iframeRef.current, {
      type: "setSelectMode",
      enabled: inSelectAndEditMode,
    });
  }, [inSelectAndEditMode]);

  // Clearing the selection from elsewhere (sidebar X, after submitting an edit).
  useEffect(() => {
    if (!selectedElement) {
      postToPreview(iframeRef.current, { type: "clearSelection" });
    }
  }, [selectedElement]);

  // Exiting select mode also releases any locked target. (Escape / app-wide
  // exit is handled by useEscapeToExitSelectMode in App.)
  useEffect(() => {
    if (!inSelectAndEditMode && selectedElement) {
      setSelectedElement(null);
    }
  }, [inSelectAndEditMode, selectedElement, setSelectedElement]);

  // Apply a fixed viewport per device and scale to fit the available pane.
  useEffect(() => {
    const updateScale = () => {
      const wrapper = wrapperRef.current;
      const iframe = iframeRef.current;
      if (!wrapper || !iframe) return;

      const viewportWidth = wrapper.clientWidth;
      const viewportHeight = wrapper.clientHeight;

      if (device === "desktop") {
        const scaleValue =
          activeMode === "fit"
            ? Math.min(1, viewportWidth / DESKTOP_VIEWPORT_WIDTH)
            : 1;
        const iframeHeight = scaleValue > 0 ? viewportHeight / scaleValue : viewportHeight;

        onScaleChange?.(scaleValue);
        iframe.style.width = `${DESKTOP_VIEWPORT_WIDTH}px`;
        iframe.style.height = `${iframeHeight}px`;
        iframe.style.transform = `scale(${scaleValue})`;
        iframe.style.transformOrigin = "top left";
        return;
      }

      onScaleChange?.(1);
      iframe.style.width = `${MOBILE_VIEWPORT_WIDTH}px`;
      iframe.style.height = `${viewportHeight}px`;
      iframe.style.transform = "scale(1)";
      iframe.style.transformOrigin = "top left";
    };

    updateScale();

    window.addEventListener("resize", updateScale);
    const resizeObserver = new ResizeObserver(updateScale);
    if (wrapperRef.current) {
      resizeObserver.observe(wrapperRef.current);
    }
    return () => {
      window.removeEventListener("resize", updateScale);
      resizeObserver.disconnect();
    };
  }, [activeMode, device, onScaleChange]);

  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe) return;
    // Normalize the Babel CDN so generated React pages (old and new) mount, then
    // inject the host<->preview bridge before the page's own scripts.
    const html = injectPreviewBridge(normalizeBabelCdn(throttledCode));
    if (iframe.srcdoc !== html) {
      iframe.srcdoc = html;
    }
  }, [throttledCode]);

  return (
    <div
      className={`flex-1 min-h-0 relative ${
        device === "mobile"
          ? "flex justify-center overflow-hidden bg-gray-100 dark:bg-zinc-900"
          : activeMode === "fit"
            ? "flex justify-center overflow-hidden"
            : "overflow-auto"
      }`}
    >
      <div
        ref={wrapperRef}
        className={`w-full h-full ${device === "mobile" ? "flex justify-center" : ""}`}
      >
        <iframe
          id={`preview-${device}`}
          ref={iframeRef}
          title="Preview"
          sandbox={PREVIEW_SANDBOX}
          className={classNames(
            {
              "border-0": true,
            }
          )}
        ></iframe>
      </div>
    </div>
  );
}

export default PreviewComponent;
