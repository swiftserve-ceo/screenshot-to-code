import toast from "react-hot-toast";
import { WS_BACKEND_URL } from "./config";
import {
  APP_ERROR_WEB_SOCKET_CODE,
  USER_CLOSE_WEB_SOCKET_CODE,
} from "./constants";
import { FullGenerationSettings } from "./types";

const ERROR_MESSAGE =
  "Error generating code. Check the Developer Console AND the backend logs for details. Feel free to open a Github issue.";

const CANCEL_MESSAGE = "Code generation cancelled";

// Batch 3: how many times we transparently re-attach to a queued job after an
// unexpected WebSocket drop. The worker keeps running regardless.
const MAX_RECONNECT_ATTEMPTS = 5;
const RECONNECT_BASE_DELAY_MS = 800;

type WebSocketResponse = {
  type:
    | "chunk"
    | "status"
    | "setCode"
    | "error"
    | "variantComplete"
    | "variantError"
    | "variantCount"
    | "variantModels"
    | "thinking"
    | "assistant"
    | "toolStart"
    | "toolResult"
    // Batch 3 (additive): queued-generation correlation + lifecycle
    | "jobCreated"
    | "jobStatus";
  value?: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data?: any;
  eventId?: string;
  variantIndex: number;
};

interface CodeGenerationCallbacks {
  onChange: (chunk: string, variantIndex: number) => void;
  onSetCode: (code: string, variantIndex: number) => void;
  onStatusUpdate: (status: string, variantIndex: number) => void;
  onVariantComplete: (variantIndex: number) => void;
  onVariantError: (variantIndex: number, error: string) => void;
  onVariantCount: (count: number) => void;
  onVariantModels: (models: string[]) => void;
  onThinking: (content: string, variantIndex: number, eventId?: string) => void;
  onAssistant: (content: string, variantIndex: number, eventId?: string) => void;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  onToolStart: (data: any, variantIndex: number, eventId?: string) => void;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  onToolResult: (data: any, variantIndex: number, eventId?: string) => void;
  onCancel: (
    reason: "user_cancelled" | "request_failed" | "connection_error",
    errorMessage?: string
  ) => void;
  onComplete: () => void;
  // Batch 3 (optional): the queued job's id + lifecycle status.
  onJobCreated?: (jobId: string) => void;
  onJobStatus?: (status: string) => void;
}

export function generateCode(
  wsRef: React.MutableRefObject<WebSocket | null>,
  params: FullGenerationSettings,
  callbacks: CodeGenerationCallbacks
) {
  // Shared across (re)connections for one logical generation.
  const state = { jobId: null as string | null, reconnects: 0, done: false };

  const connect = (payload: Record<string, unknown>) => {
    const wsUrl = `${WS_BACKEND_URL}/generate-code`;
    console.log("Connecting to backend @ ", wsUrl);

    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.addEventListener("open", () => {
      ws.send(JSON.stringify(payload));
    });

    ws.addEventListener("message", async (event: MessageEvent) => {
      const response = JSON.parse(event.data) as WebSocketResponse;
      if (response.type === "chunk") {
        callbacks.onChange(response.value || "", response.variantIndex);
      } else if (response.type === "status") {
        callbacks.onStatusUpdate(response.value || "", response.variantIndex);
      } else if (response.type === "setCode") {
        callbacks.onSetCode(response.value || "", response.variantIndex);
      } else if (response.type === "variantComplete") {
        callbacks.onVariantComplete(response.variantIndex);
      } else if (response.type === "variantError") {
        callbacks.onVariantError(response.variantIndex, response.value || "");
      } else if (response.type === "variantCount") {
        callbacks.onVariantCount(parseInt(response.value || "1"));
      } else if (response.type === "variantModels") {
        callbacks.onVariantModels(response.data?.models || []);
      } else if (response.type === "thinking") {
        callbacks.onThinking(response.value || "", response.variantIndex, response.eventId);
      } else if (response.type === "assistant") {
        callbacks.onAssistant(response.value || "", response.variantIndex, response.eventId);
      } else if (response.type === "toolStart") {
        callbacks.onToolStart(response.data, response.variantIndex, response.eventId);
      } else if (response.type === "toolResult") {
        callbacks.onToolResult(response.data, response.variantIndex, response.eventId);
      } else if (response.type === "jobCreated") {
        state.jobId = response.value || null;
        if (state.jobId) callbacks.onJobCreated?.(state.jobId);
      } else if (response.type === "jobStatus") {
        callbacks.onJobStatus?.(response.value || "");
      } else if (response.type === "error") {
        console.error("Error generating code", response.value);
        toast.error(response.value || ERROR_MESSAGE);
      }
    });

    ws.addEventListener("close", (event) => {
      console.log("Connection closed", event.code, event.reason);
      if (event.code === USER_CLOSE_WEB_SOCKET_CODE) {
        state.done = true;
        toast.success(CANCEL_MESSAGE);
        callbacks.onCancel("user_cancelled");
      } else if (event.code === APP_ERROR_WEB_SOCKET_CODE) {
        state.done = true;
        console.error("Known server error", event);
        callbacks.onCancel("request_failed", event.reason || ERROR_MESSAGE);
      } else if (event.code !== 1000) {
        // Unexpected drop. If this is a queued job, the worker is still running
        // — transparently re-attach instead of failing the generation.
        if (state.jobId && state.reconnects < MAX_RECONNECT_ATTEMPTS && !state.done) {
          state.reconnects += 1;
          const delay = RECONNECT_BASE_DELAY_MS * state.reconnects;
          console.warn(
            `WebSocket dropped; re-attaching to job ${state.jobId} ` +
              `(attempt ${state.reconnects}/${MAX_RECONNECT_ATTEMPTS}) in ${delay}ms`
          );
          setTimeout(() => connect({ jobId: state.jobId }), delay);
          return;
        }
        console.error("Unknown server or connection error", event);
        toast.error(ERROR_MESSAGE);
        callbacks.onCancel("connection_error", event.reason || ERROR_MESSAGE);
      } else {
        state.done = true;
        callbacks.onComplete();
      }
    });

    ws.addEventListener("error", (error) => {
      console.error("WebSocket error", error);
    });
  };

  connect(params as unknown as Record<string, unknown>);
}
