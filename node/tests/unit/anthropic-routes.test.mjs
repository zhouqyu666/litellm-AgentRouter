import assert from "node:assert";
import { test } from "node:test";
import { createAnthropicRouteHandlers } from "../../lib/router/anthropic-routes.mjs";

function makeMockClient({ createResult, withResponseResult } = {}) {
  const calls = [];
  const defaultData = {
    id: "msg-456",
    type: "message",
    role: "assistant",
    content: [{ type: "text", text: "Hello" }],
    model: "claude-sonnet-4-20250514",
    usage: { input_tokens: 10, output_tokens: 5 },
  };

  const promise = Promise.resolve(createResult ?? defaultData);
  if (withResponseResult !== undefined) {
    promise.withResponse = () => Promise.resolve(withResponseResult);
  } else {
    promise.withResponse = () =>
      Promise.resolve({
        data: createResult ?? defaultData,
        response: { status: 200, headers: new Headers({ "x-request-id": "resp-123" }) },
      });
  }

  return {
    messages: {
      create(body, options) {
        calls.push({ body, options });
        return promise;
      },
    },
    _calls: calls,
  };
}

test("createAnthropicRouteHandlers creates /v1/messages handler", () => {
  const handlers = createAnthropicRouteHandlers(() => makeMockClient());
  assert.ok(handlers["/v1/messages"]);
});

test("/v1/messages handler calls SDK client with body and forwards X-Request-ID", async () => {
  const client = makeMockClient();
  const handlers = createAnthropicRouteHandlers(() => client);
  const handler = handlers["/v1/messages"];

  const body = { model: "claude-sonnet-4-20250514", messages: [{ role: "user", content: "Hi" }] };
  const forwardedHeaders = { "X-Request-ID": "test-123" };

  const result = await handler(body, forwardedHeaders, "sk-ant-key");

  assert.strictEqual(client._calls.length, 1);
  assert.deepStrictEqual(client._calls[0].body, body);
  assert.deepStrictEqual(client._calls[0].options, { headers: { "X-Request-ID": "test-123" } });
  assert.ok(result.data);
  assert.strictEqual(result.data.id, "msg-456");
  assert.strictEqual(result.response.status, 200);
});

test("/v1/messages handler resolves client per apiKey", async () => {
  const resolvedKeys = [];
  const clientResolver = (apiKey) => {
    resolvedKeys.push(apiKey);
    return makeMockClient();
  };

  const handlers = createAnthropicRouteHandlers(clientResolver);
  const handler = handlers["/v1/messages"];

  await handler({ model: "test" }, {}, "sk-ant-key-1");
  await handler({ model: "test" }, {}, "sk-ant-key-2");

  assert.deepStrictEqual(resolvedKeys, ["sk-ant-key-1", "sk-ant-key-2"]);
});

test("/v1/messages handler returns stream with anthropic format for streaming", async () => {
  const mockStream = (async function* () {
    yield { type: "message_start", message: {} };
    yield { type: "content_block_delta", delta: { text: "Hi" } };
    yield { type: "message_stop" };
  })();

  const client = makeMockClient({ createResult: mockStream });
  // Override withResponse since streaming doesn't use it
  const handlers = createAnthropicRouteHandlers(() => {
    const calls = [];
    return {
      messages: {
        create(body, options) {
          calls.push({ body, options });
          return Promise.resolve(mockStream);
        },
      },
      _calls: calls,
    };
  });
  const handler = handlers["/v1/messages"];

  const result = await handler({ model: "test", stream: true }, {}, "sk-ant-key");

  assert.ok(result.stream);
  assert.strictEqual(result.streamFormat, "anthropic");
});

test("/v1/messages handler omits headers option when no X-Request-ID", async () => {
  const client = makeMockClient();
  const handlers = createAnthropicRouteHandlers(() => client);
  const handler = handlers["/v1/messages"];

  await handler({ model: "test" }, {}, "sk-ant-key");

  assert.deepStrictEqual(client._calls[0].options, {});
});

test("/v1/messages handler propagates SDK errors with status", async () => {
  const clientResolver = () => ({
    messages: {
      create() {
        const err = new Error("rate limited");
        err.status = 429;
        return Promise.reject(err);
      },
    },
  });

  const handlers = createAnthropicRouteHandlers(clientResolver);
  const handler = handlers["/v1/messages"];

  try {
    await handler({ model: "test" }, {}, "sk-ant-key");
    assert.fail("Should have thrown");
  } catch (err) {
    assert.strictEqual(err.status, 429);
    assert.ok(err.message.includes("rate limited"));
  }
});
