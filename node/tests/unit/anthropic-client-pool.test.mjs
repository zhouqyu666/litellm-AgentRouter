import assert from "node:assert";
import { test } from "node:test";
import { AnthropicClientPool } from "../../lib/client/anthropic-client-pool.mjs";

test("AnthropicClientPool.get creates a client for a given key", () => {
  const pool = new AnthropicClientPool({
    baseURL: "https://agentrouter.org",
    timeoutMs: 60_000,
    userAgent: "TestAgent/1.0",
  });

  const client = pool.get("sk-ant-test-key");
  assert.ok(client);
  assert.ok(client.messages);
  assert.strictEqual(pool.size, 1);
});

test("AnthropicClientPool.get reuses cached clients", () => {
  const pool = new AnthropicClientPool({
    baseURL: "https://agentrouter.org",
    timeoutMs: 60_000,
    userAgent: "TestAgent/1.0",
  });

  const client1 = pool.get("sk-ant-key1");
  const client2 = pool.get("sk-ant-key1");
  assert.strictEqual(client1, client2, "Same key should return same client");
  assert.strictEqual(pool.size, 1);
});

test("AnthropicClientPool.get creates separate clients per key", () => {
  const pool = new AnthropicClientPool({
    baseURL: "https://agentrouter.org",
    timeoutMs: 60_000,
    userAgent: "TestAgent/1.0",
  });

  const client1 = pool.get("sk-ant-key1");
  const client2 = pool.get("sk-ant-key2");
  assert.notStrictEqual(client1, client2, "Different keys should return different clients");
  assert.strictEqual(pool.size, 2);
});

test("AnthropicClientPool.get throws on missing key", () => {
  const pool = new AnthropicClientPool({
    baseURL: "https://agentrouter.org",
    timeoutMs: 60_000,
    userAgent: "TestAgent/1.0",
  });

  assert.throws(
    () => pool.get(null),
    /API key is required to obtain an Anthropic client/
  );
  assert.throws(
    () => pool.get(""),
    /API key is required to obtain an Anthropic client/
  );
  assert.throws(
    () => pool.get(undefined),
    /API key is required to obtain an Anthropic client/
  );
});

test("AnthropicClientPool.size starts at zero", () => {
  const pool = new AnthropicClientPool({
    baseURL: "https://agentrouter.org",
    timeoutMs: 60_000,
    userAgent: "TestAgent/1.0",
  });

  assert.strictEqual(pool.size, 0);
});
