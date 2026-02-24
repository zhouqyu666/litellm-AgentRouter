import assert from "node:assert";
import { test } from "node:test";
import { createNodeUpstreamProxy } from "../../main.mjs";

const SILENT_LOGGER = { log: () => {}, error: () => {} };

test("reads OPENAI_BASE_URL from environment", () => {
  const originalEnv = process.env.OPENAI_BASE_URL;
  process.env.OPENAI_BASE_URL = "https://custom.api.com/v1";
  process.env.OPENAI_API_KEY = "sk-test-key";

  try {
    const proxy = createNodeUpstreamProxy({
      logger: SILENT_LOGGER,
    });

    assert.strictEqual(proxy.config.upstreamBase, "https://custom.api.com/v1");
    assert.strictEqual(proxy.config.fallbackApiKey, "sk-test-key");
  } finally {
    if (originalEnv !== undefined) {
      process.env.OPENAI_BASE_URL = originalEnv;
    } else {
      delete process.env.OPENAI_BASE_URL;
    }
    delete process.env.OPENAI_API_KEY;
  }
});

test("reads NODE_USER_AGENT from environment", () => {
  const originalUserAgent = process.env.NODE_USER_AGENT;
  process.env.NODE_USER_AGENT = "CustomAgent/1.0.0";
  process.env.OPENAI_API_KEY = "sk-test-key";

  try {
    const proxy = createNodeUpstreamProxy({
      logger: SILENT_LOGGER,
    });

    assert.strictEqual(proxy.config.userAgent, "CustomAgent/1.0.0");
  } finally {
    if (originalUserAgent !== undefined) {
      process.env.NODE_USER_AGENT = originalUserAgent;
    } else {
      delete process.env.NODE_USER_AGENT;
    }
    delete process.env.OPENAI_API_KEY;
  }
});

test("uses default values when environment variables are not set", () => {
  const originalBase = process.env.OPENAI_BASE_URL;
  const originalAgent = process.env.NODE_USER_AGENT;
  delete process.env.OPENAI_BASE_URL;
  delete process.env.NODE_USER_AGENT;
  process.env.OPENAI_API_KEY = "sk-test-key";

  try {
    const proxy = createNodeUpstreamProxy({
      logger: SILENT_LOGGER,
    });

    assert.ok(proxy.config.upstreamBase.includes("agentrouter.org"));
    assert.ok(proxy.config.userAgent.includes("QwenCode"));
  } finally {
    if (originalBase !== undefined) {
      process.env.OPENAI_BASE_URL = originalBase;
    }
    if (originalAgent !== undefined) {
      process.env.NODE_USER_AGENT = originalAgent;
    }
    delete process.env.OPENAI_API_KEY;
  }
});

test("always uses port 4000 regardless of environment", () => {
  process.env.OPENAI_API_KEY = "sk-test-key";
  process.env.PORT = "8080"; // This should be ignored

  try {
    const proxy = createNodeUpstreamProxy({
      logger: SILENT_LOGGER,
    });

    // Port should always be 4000, not affected by PORT env var
    assert.strictEqual(proxy.config.port, 4000);
  } finally {
    delete process.env.OPENAI_API_KEY;
    delete process.env.PORT;
  }
});

test("allows missing OPENAI_API_KEY (key comes from request)", () => {
  const originalKey = process.env.OPENAI_API_KEY;
  delete process.env.OPENAI_API_KEY;

  try {
    const proxy = createNodeUpstreamProxy({
      logger: SILENT_LOGGER,
    });

    assert.strictEqual(proxy.config.fallbackApiKey, null);
  } finally {
    if (originalKey !== undefined) {
      process.env.OPENAI_API_KEY = originalKey;
    }
  }
});

test("overrides take precedence over environment variables", () => {
  process.env.OPENAI_BASE_URL = "https://env.api.com/v1";
  process.env.OPENAI_API_KEY = "sk-env-key";
  process.env.NODE_USER_AGENT = "EnvAgent/1.0";

  try {
    const proxy = createNodeUpstreamProxy({
      logger: SILENT_LOGGER,
      upstreamBase: "https://override.api.com/v1",
      apiKey: "sk-override-key",
      userAgent: "OverrideAgent/2.0",
    });

    assert.strictEqual(proxy.config.upstreamBase, "https://override.api.com/v1");
    assert.strictEqual(proxy.config.fallbackApiKey, "sk-override-key");
    assert.strictEqual(proxy.config.userAgent, "OverrideAgent/2.0");
  } finally {
    delete process.env.OPENAI_BASE_URL;
    delete process.env.OPENAI_API_KEY;
    delete process.env.NODE_USER_AGENT;
  }
});
