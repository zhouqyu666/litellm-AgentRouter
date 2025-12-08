import assert from "node:assert";
import { test } from "node:test";
import {
  DEFAULT_PORT,
  DEFAULT_HOST,
  DEFAULT_TIMEOUT_SECONDS,
  DEFAULT_UPSTREAM_BASE,
} from "../../lib/config/constants.mjs";
import { DEFAULT_USER_AGENT } from "../../lib/fetch/fetchVersion.mjs";

test("DEFAULT_PORT is 4000", () => {
  assert.strictEqual(DEFAULT_PORT, 4000);
});

test("DEFAULT_HOST is 0.0.0.0", () => {
  assert.strictEqual(DEFAULT_HOST, "0.0.0.0");
});

test("DEFAULT_TIMEOUT_SECONDS is 300", () => {
  assert.strictEqual(DEFAULT_TIMEOUT_SECONDS, 300);
});

test("DEFAULT_UPSTREAM_BASE is agentrouter.org", () => {
  assert.strictEqual(DEFAULT_UPSTREAM_BASE, "https://agentrouter.org/v1");
});

test("DEFAULT_USER_AGENT includes QwenCode", () => {
  assert.ok(DEFAULT_USER_AGENT.includes("QwenCode"));
});
