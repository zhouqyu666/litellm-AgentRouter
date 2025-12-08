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
  }

  writeHead(status, headers) {
    this.statusCode = status;
    this.headers = { ...headers };
  }

  end(payload) {
    this.body = payload?.toString("utf-8") ?? "";
  }
}

test("NodeRequestRouter rejects non-POST methods", async () => {
  const mockClient = {
    chat: { completions: { create: () => {} } },
    completions: { create: () => {} },
  };

  const router = new NodeRequestRouter({
    client: mockClient,
    logger: SILENT_LOGGER,
  });

  const req = createMockRequest({ method: "GET" });
  const res = new MockResponse();

  await router.handle(req, res);

  assert.strictEqual(res.statusCode, 405);
  assert.strictEqual(JSON.parse(res.body).error, "Method not allowed");
});

test("NodeRequestRouter returns 404 for unknown routes", async () => {
  const mockClient = {
    chat: { completions: { create: () => {} } },
    completions: { create: () => {} },
  };

  const router = new NodeRequestRouter({
    client: mockClient,
    logger: SILENT_LOGGER,
  });

  const req = createMockRequest({ path: "/v1/unknown" });
  const res = new MockResponse();

  await router.handle(req, res);

  assert.strictEqual(res.statusCode, 404);
  assert.strictEqual(JSON.parse(res.body).error, "Not found");
});

test("NodeRequestRouter handles invalid JSON", async () => {
  const mockClient = {
    chat: { completions: { create: () => {} } },
    completions: { create: () => {} },
  };

  const router = new NodeRequestRouter({
    client: mockClient,
    logger: SILENT_LOGGER,
  });

  const req = {
    method: "POST",
    url: "/v1/chat/completions",
    headers: { host: "127.0.0.1" },
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
    client: mockClient,
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
    client: mockClient,
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
    client: mockClient,
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
              // Simulate upstream sending both headers (incorrect but happens)
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
    client: mockClient,
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

  // Verify Transfer-Encoding is removed to comply with HTTP spec
  // (Content-Length and Transfer-Encoding are mutually exclusive)
  assert.ok(!res.headers["transfer-encoding"], "Transfer-Encoding header should be removed");
  assert.ok(!res.headers["Transfer-Encoding"], "Transfer-Encoding header (caps) should be removed");

  // Verify Content-Length is set (proves response was processed)
  assert.ok(res.headers["content-length"], "Content-Length header should be present");

  // Verify custom headers are preserved
  assert.strictEqual(res.headers["x-custom-header"], "preserved", "Custom headers should be preserved");

  // Verify response body is valid
  const parsed = JSON.parse(res.body);
  assert.deepStrictEqual(parsed, { id: "chat-789" });
});
