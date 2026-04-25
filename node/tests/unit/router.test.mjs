import assert from "node:assert";
import { test } from "node:test";
import { NodeRequestRouter } from "../../lib/router/router.mjs";

const SILENT_LOGGER = { log: () => {}, error: () => {} };

function createMockRequest({
  path = "/v1/chat/completions",
  body = null,
  headers = {},
  method = "POST",
} = {}) {
  const payloadBuffer = body ? Buffer.from(JSON.stringify(body)) : null;
  let consumed = false;

  return {
    method,
    url: path,
    headers: {
      host: "127.0.0.1",
      ...headers,
    },
    async *[Symbol.asyncIterator]() {
      if (consumed) {
        return;
      }
      consumed = true;
      if (payloadBuffer) {
        yield payloadBuffer;
      }
    },
  };
}

class MockResponse {
  constructor() {
    this.statusCode = 200;
    this.headers = {};
    this.body = "";
    this._chunks = [];
  }

  writeHead(status, headers) {
    this.statusCode = status;
    this.headers = { ...headers };
  }

  write(chunk) {
    this._chunks.push(chunk);
  }

  end(payload) {
    if (payload) {
      this.body = payload?.toString("utf-8") ?? "";
    } else {
      this.body = this._chunks.join("");
    }
  }
}

function createOpenAIMockClient() {
  return {
    chat: {
      completions: {
        create: (body, options) => ({
          withResponse: async () => ({
            data: { id: "chat-123" },
            response: {
              status: 200,
              headers: new Headers({ "content-type": "application/json" }),
            },
          }),
        }),
      },
    },
    completions: { create: () => {} },
  };
}

test("NodeRequestRouter rejects non-POST methods", async () => {
  const router = new NodeRequestRouter({
    clientResolver: () => createOpenAIMockClient(),
    logger: SILENT_LOGGER,
  });

  const req = createMockRequest({ method: "GET" });
  const res = new MockResponse();

  await router.handle(req, res);

  assert.strictEqual(res.statusCode, 405);
  assert.strictEqual(JSON.parse(res.body).error, "Method not allowed");
});

test("NodeRequestRouter returns 404 for unknown routes", async () => {
  const router = new NodeRequestRouter({
    clientResolver: () => createOpenAIMockClient(),
    logger: SILENT_LOGGER,
  });

  const req = createMockRequest({ path: "/v1/unknown" });
  const res = new MockResponse();

  await router.handle(req, res);

  assert.strictEqual(res.statusCode, 404);
  assert.strictEqual(JSON.parse(res.body).error, "Not found");
});

test("NodeRequestRouter handles invalid JSON", async () => {
  const router = new NodeRequestRouter({
    clientResolver: () => createOpenAIMockClient(),
    logger: SILENT_LOGGER,
  });

  const req = {
    method: "POST",
    url: "/v1/chat/completions",
    headers: { host: "127.0.0.1", authorization: "Bearer sk-test" },
    async *[Symbol.asyncIterator]() {
      yield Buffer.from("{invalid");
    },
  };

  const res = new MockResponse();
  await router.handle(req, res);

  assert.strictEqual(res.statusCode, 400);
  const body = JSON.parse(res.body);
  assert.strictEqual(body.error, "Invalid JSON payload");
  assert.ok(body.detail);
});

test("NodeRequestRouter forwards successful responses", async () => {
  let handlerCalled = false;
  const mockClient = {
    chat: {
      completions: {
        create: (body, options) => {
          handlerCalled = true;
          return {
            withResponse: async () => ({
              data: { id: "chat-123" },
              response: {
                status: 200,
                headers: new Headers({ "content-type": "application/json" }),
              },
            }),
          };
        },
      },
    },
    completions: { create: () => {} },
  };

  const router = new NodeRequestRouter({
    clientResolver: () => mockClient,
    fallbackApiKey: "sk-test",
    logger: SILENT_LOGGER,
  });

  const req = createMockRequest({
    path: "/v1/chat/completions",
    body: { model: "gpt-4" },
  });
  const res = new MockResponse();

  await router.handle(req, res);

  assert.ok(handlerCalled, "Handler should be called");
  assert.strictEqual(res.statusCode, 200);
  assert.ok(res.body.length > 0, `Response body should not be empty, got: "${res.body}"`);
  const parsed = JSON.parse(res.body);
  assert.deepStrictEqual(parsed, { id: "chat-123" });
});

test("NodeRequestRouter propagates upstream errors", async () => {
  const error = new Error("Upstream failed");
  error.status = 503;

  const mockClient = {
    chat: {
      completions: {
        create: (body, options) => ({
          withResponse: async () => {
            throw error;
          },
        }),
      },
    },
    completions: { create: () => {} },
  };

  const router = new NodeRequestRouter({
    clientResolver: () => mockClient,
    fallbackApiKey: "sk-test",
    logger: SILENT_LOGGER,
  });

  const req = createMockRequest({ path: "/v1/chat/completions" });
  const res = new MockResponse();

  await router.handle(req, res);

  assert.strictEqual(res.statusCode, 503);
  assert.strictEqual(JSON.parse(res.body).error, "Upstream failed");
});

test("NodeRequestRouter preserves request ID", async () => {
  const mockClient = {
    chat: {
      completions: {
        create: async (body, options) => ({
          withResponse: async () => ({
            data: { ok: true },
            response: {
              status: 200,
              headers: new Headers({ "x-request-id": "req-456" }),
            },
          }),
        }),
      },
    },
    completions: { create: () => {} },
  };

  const router = new NodeRequestRouter({
    clientResolver: () => mockClient,
    fallbackApiKey: "sk-test",
    logger: SILENT_LOGGER,
  });

  const req = createMockRequest({
    path: "/v1/chat/completions",
    headers: { "x-request-id": "req-456" },
  });
  const res = new MockResponse();

  await router.handle(req, res);

  assert.strictEqual(res.headers["x-request-id"], "req-456");
});

test("NodeRequestRouter removes Transfer-Encoding before setting Content-Length", async () => {
  const mockClient = {
    chat: {
      completions: {
        create: (body, options) => ({
          withResponse: async () => ({
            data: { id: "chat-789" },
            response: {
              status: 200,
              headers: new Headers({
                "content-type": "application/json",
                "transfer-encoding": "chunked",
                "x-custom-header": "preserved",
              }),
            },
          }),
        }),
      },
    },
    completions: { create: () => {} },
  };

  const router = new NodeRequestRouter({
    clientResolver: () => mockClient,
    fallbackApiKey: "sk-test",
    logger: SILENT_LOGGER,
  });

  const req = createMockRequest({
    path: "/v1/chat/completions",
    body: { model: "gpt-4", messages: [] },
  });
  const res = new MockResponse();

  await router.handle(req, res);

  assert.strictEqual(res.statusCode, 200);
  assert.ok(res.body.length > 0, "Response body should not be empty");
  assert.ok(!res.headers["transfer-encoding"], "Transfer-Encoding header should be removed");
  assert.ok(!res.headers["Transfer-Encoding"], "Transfer-Encoding header (caps) should be removed");
  assert.ok(res.headers["content-length"], "Content-Length header should be present");
  assert.strictEqual(res.headers["x-custom-header"], "preserved", "Custom headers should be preserved");
  const parsed = JSON.parse(res.body);
  assert.deepStrictEqual(parsed, { id: "chat-789" });
});

// --- x-api-key extraction tests ---

function createAnthropicMockClient({ captureKey } = {}) {
  return (apiKey) => {
    if (captureKey) captureKey(apiKey);
    return {
      messages: {
        create(body, options) {
          const data = { id: "msg-123", type: "message", content: [{ type: "text", text: "Hi" }] };
          const p = Promise.resolve(data);
          p.withResponse = () => Promise.resolve({
            data,
            response: { status: 200, headers: new Headers({ "content-type": "application/json" }) },
          });
          return p;
        },
      },
    };
  };
}

test("NodeRequestRouter extracts API key from x-api-key header for Anthropic", async () => {
  let capturedApiKey = null;

  const router = new NodeRequestRouter({
    clientResolver: () => createOpenAIMockClient(),
    fallbackApiKey: "sk-openai-fallback",
    anthropicClientResolver: createAnthropicMockClient({ captureKey: (k) => { capturedApiKey = k; } }),
    anthropicFallbackApiKey: "sk-ant-fallback",
    logger: SILENT_LOGGER,
  });

  const req = createMockRequest({
    path: "/v1/messages",
    body: { model: "claude-sonnet-4-20250514", messages: [] },
    headers: { "x-api-key": "sk-ant-from-header" },
  });
  const res = new MockResponse();

  await router.handle(req, res);

  assert.strictEqual(res.statusCode, 200);
  assert.strictEqual(capturedApiKey, "sk-ant-from-header");
});

test("NodeRequestRouter falls back to anthropic key for /v1/messages", async () => {
  let capturedApiKey = null;

  const router = new NodeRequestRouter({
    clientResolver: () => createOpenAIMockClient(),
    fallbackApiKey: "sk-openai-fallback",
    anthropicClientResolver: createAnthropicMockClient({ captureKey: (k) => { capturedApiKey = k; } }),
    anthropicFallbackApiKey: "sk-ant-fallback",
    logger: SILENT_LOGGER,
  });

  // No Authorization or x-api-key headers
  const req = createMockRequest({
    path: "/v1/messages",
    body: { model: "claude-sonnet-4-20250514", messages: [] },
  });
  const res = new MockResponse();

  await router.handle(req, res);

  assert.strictEqual(res.statusCode, 200);
  assert.strictEqual(capturedApiKey, "sk-ant-fallback");
});

test("NodeRequestRouter falls back to openai key for /v1/chat/completions", async () => {
  const mockClient = createOpenAIMockClient();

  const router = new NodeRequestRouter({
    clientResolver: () => mockClient,
    fallbackApiKey: "sk-openai-fallback",
    anthropicFallbackApiKey: "sk-ant-fallback",
    logger: SILENT_LOGGER,
  });

  // No Authorization header
  const req = createMockRequest({
    path: "/v1/chat/completions",
    body: { model: "gpt-5" },
  });
  const res = new MockResponse();

  await router.handle(req, res);

  assert.strictEqual(res.statusCode, 200);
});

test("NodeRequestRouter returns 401 when no API key available", async () => {
  const router = new NodeRequestRouter({
    clientResolver: () => createOpenAIMockClient(),
    fallbackApiKey: null,
    anthropicFallbackApiKey: null,
    logger: SILENT_LOGGER,
  });

  const req = createMockRequest({
    path: "/v1/chat/completions",
    body: { model: "gpt-5" },
  });
  const res = new MockResponse();

  await router.handle(req, res);

  assert.strictEqual(res.statusCode, 401);
});

// --- Anthropic SDK-based response tests ---

test("NodeRequestRouter sends JSON body for Anthropic non-streaming via SDK", async () => {
  const router = new NodeRequestRouter({
    clientResolver: () => createOpenAIMockClient(),
    fallbackApiKey: "sk-openai",
    anthropicClientResolver: createAnthropicMockClient(),
    anthropicFallbackApiKey: "sk-ant-test",
    logger: SILENT_LOGGER,
  });

  const req = createMockRequest({
    path: "/v1/messages",
    body: { model: "claude-sonnet-4-20250514", messages: [] },
  });
  const res = new MockResponse();

  await router.handle(req, res);

  assert.strictEqual(res.statusCode, 200);
  assert.ok(res.headers["content-type"]?.includes("application/json"));
  const parsed = JSON.parse(res.body);
  assert.strictEqual(parsed.id, "msg-123");
  assert.strictEqual(parsed.type, "message");
});

test("NodeRequestRouter sends SSE for Anthropic streaming via SDK", async () => {
  const streamingClientResolver = () => ({
    messages: {
      create(body, options) {
        const stream = (async function* () {
          yield { type: "message_start", message: { id: "msg-stream" } };
          yield { type: "content_block_delta", delta: { type: "text_delta", text: "Hi" } };
          yield { type: "message_stop" };
        })();
        return Promise.resolve(stream);
      },
    },
  });

  const router = new NodeRequestRouter({
    clientResolver: () => createOpenAIMockClient(),
    fallbackApiKey: "sk-openai",
    anthropicClientResolver: streamingClientResolver,
    anthropicFallbackApiKey: "sk-ant-test",
    logger: SILENT_LOGGER,
  });

  const req = createMockRequest({
    path: "/v1/messages",
    body: { model: "claude-sonnet-4-20250514", messages: [], stream: true },
  });
  const res = new MockResponse();

  await router.handle(req, res);

  assert.strictEqual(res.statusCode, 200);
  assert.strictEqual(res.headers["content-type"], "text/event-stream");
  assert.ok(res.body.includes("event: message_start"), "Should contain message_start event");
  assert.ok(res.body.includes("event: content_block_delta"), "Should contain content_block_delta event");
  assert.ok(res.body.includes("event: message_stop"), "Should contain message_stop event");
});
