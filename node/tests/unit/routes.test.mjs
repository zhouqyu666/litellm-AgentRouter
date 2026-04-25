import assert from "node:assert";
import { test } from "node:test";
import { createRouteHandlers } from "../../lib/router/routes.mjs";

test("createRouteHandlers creates chat completions handler", async () => {
  const mockClient = {
    chat: {
      completions: {
        create: async (body, options) => {
          return { result: "chat", body, options };
        },
      },
    },
    completions: {
      create: async () => ({ result: "completions" }),
    },
  };

  const handlers = createRouteHandlers(() => mockClient);

  assert.ok(handlers["/v1/chat/completions"]);
  assert.ok(handlers["/v1/completions"]);
});

test("chat handler calls client with body and headers", async () => {
  const calls = [];
  const mockClient = {
    chat: {
      completions: {
        create: (body, options) => {
          calls.push({ body, options });
          return Promise.resolve({ id: "chat-response" });
        },
      },
    },
  };

  const handlers = createRouteHandlers(() => mockClient);
  const handler = handlers["/v1/chat/completions"];

  const body = { model: "gpt-4" };
  const headers = { "X-Request-ID": "test-123" };

  const result = await handler(body, headers, "sk-test");

  assert.strictEqual(calls.length, 1);
  assert.deepStrictEqual(calls[0].body, body);
  assert.deepStrictEqual(calls[0].options.headers, headers);
  assert.deepStrictEqual(result.data, { id: "chat-response" });
  assert.strictEqual(result.response.status, 200);
});

test("handler supports withResponse pattern", async () => {
  const mockClient = {
    chat: {
      completions: {
        create: () => ({
          withResponse: async () => ({
            data: { id: "chat-123" },
            response: {
              status: 200,
              headers: new Headers({ "x-custom": "value" }),
            },
          }),
        }),
      },
    },
  };

  const handlers = createRouteHandlers(() => mockClient);
  const handler = handlers["/v1/chat/completions"];

  const result = await handler({}, {}, "sk-test");

  assert.deepStrictEqual(result.data, { id: "chat-123" });
  assert.strictEqual(result.response.status, 200);
});

test("handler wraps non-withResponse responses", async () => {
  const mockClient = {
    completions: {
      create: async () => ({ id: "comp-456" }),
    },
  };

  const handlers = createRouteHandlers(() => mockClient);
  const handler = handlers["/v1/completions"];

  const result = await handler({}, {}, "sk-test");

  assert.deepStrictEqual(result.data, { id: "comp-456" });
  assert.strictEqual(result.response.status, 200);
  assert.ok(result.response.headers instanceof Headers);
});

test("handler throws when client method unavailable", async () => {
  const mockClient = {
    chat: {},
    completions: {},
  };

  const handlers = createRouteHandlers(() => mockClient);
  const handler = handlers["/v1/chat/completions"];

  await assert.rejects(
    () => handler({}, {}, "sk-test"),
    /Handler not available/
  );
});
