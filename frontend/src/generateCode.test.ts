import { generateCode } from "./generateCode";
import { APP_ERROR_WEB_SOCKET_CODE } from "./constants";
import type { FullGenerationSettings } from "./types";

const toastError = jest.fn();
const toastSuccess = jest.fn();

jest.mock("./config", () => ({
  WS_BACKEND_URL: "ws://test-backend",
}));

jest.mock("react-hot-toast", () => ({
  __esModule: true,
  default: {
    error: (...args: unknown[]) => toastError(...args),
    success: (...args: unknown[]) => toastSuccess(...args),
  },
}));

type Listener = (event: unknown) => void;

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  listeners: Record<string, Listener[]> = {};
  sent: string[] = [];
  url: string;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  addEventListener(type: string, cb: Listener) {
    (this.listeners[type] ||= []).push(cb);
  }

  send(data: string) {
    this.sent.push(data);
  }

  close() {}

  emit(type: string, event: unknown) {
    (this.listeners[type] || []).forEach((cb) => cb(event));
  }

  open() {
    this.emit("open", {});
  }

  message(payload: unknown) {
    this.emit("message", { data: JSON.stringify(payload) });
  }

  serverClose(code: number, reason = "") {
    this.emit("close", { code, reason });
  }
}

function noopCallbacks() {
  return {
    onChange: jest.fn(),
    onSetCode: jest.fn(),
    onStatusUpdate: jest.fn(),
    onVariantComplete: jest.fn(),
    onVariantError: jest.fn(),
    onVariantCount: jest.fn(),
    onVariantModels: jest.fn(),
    onThinking: jest.fn(),
    onAssistant: jest.fn(),
    onToolStart: jest.fn(),
    onToolResult: jest.fn(),
    onCancel: jest.fn(),
    onComplete: jest.fn(),
    onJobCreated: jest.fn(),
    onJobStatus: jest.fn(),
  };
}

describe("generateCode queued-job terminal error handling", () => {
  const realWebSocket = global.WebSocket;

  beforeEach(() => {
    toastError.mockClear();
    toastSuccess.mockClear();
    FakeWebSocket.instances = [];
    // @ts-expect-error test double
    global.WebSocket = FakeWebSocket;
  });

  afterEach(() => {
    global.WebSocket = realWebSocket;
  });

  it("shows exactly one error toast for a failed queued job that already sent an error event", () => {
    const wsRef = { current: null as WebSocket | null };
    const callbacks = noopCallbacks();

    generateCode(wsRef, {} as FullGenerationSettings, callbacks);
    const ws = FakeWebSocket.instances[0];
    ws.open();
    ws.message({ type: "jobCreated", value: "job-123", variantIndex: 0 });
    ws.message({ type: "status", value: "Queued...", variantIndex: 0 });
    // backend forwards one descriptive error, then closes with the app-error code
    ws.message({
      type: "error",
      value: "No Anthropic API key configured.",
      variantIndex: 0,
    });
    ws.serverClose(APP_ERROR_WEB_SOCKET_CODE, "No Anthropic API key configured.");

    expect(toastError).toHaveBeenCalledTimes(1);
    expect(toastError).toHaveBeenCalledWith("No Anthropic API key configured.");
    expect(callbacks.onCancel).toHaveBeenCalledWith(
      "request_failed",
      "No Anthropic API key configured."
    );
  });

  it("does not reconnect after an app-error close and raises no extra toast", () => {
    jest.useFakeTimers();
    const wsRef = { current: null as WebSocket | null };
    const callbacks = noopCallbacks();

    generateCode(wsRef, {} as FullGenerationSettings, callbacks);
    const ws = FakeWebSocket.instances[0];
    ws.open();
    ws.message({ type: "jobCreated", value: "job-123", variantIndex: 0 });
    ws.message({ type: "error", value: "Generation failed. Please retry.", variantIndex: 0 });
    ws.serverClose(APP_ERROR_WEB_SOCKET_CODE, "Generation failed. Please retry.");

    jest.runAllTimers();

    expect(FakeWebSocket.instances).toHaveLength(1); // no reconnect
    expect(toastError).toHaveBeenCalledTimes(1);
    jest.useRealTimers();
  });
});
