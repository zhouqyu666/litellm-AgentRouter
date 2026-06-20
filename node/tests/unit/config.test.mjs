import assert from "node:assert";
import { test } from "node:test";
import { NodeProxyConfig } from "../../lib/config/config.mjs";

test("NodeProxyConfig.fromEnv uses defaults when no overrides", () => {
  const originalApiKey = process.env.OPENAI_API_KEY;
  const originalAnthropicKey = process.env.ANTHROPIC_API_KEY;
  const originalAnthropicBase = process.env.ANTHROPIC_BASE_URL;
  process.env.OPENAI_API_KEY = "sk-test-key";
  delete process.env.ANTHROPIC_API_KEY;
  delete process.env.ANTHROPIC_BASE_URL;

  try {
    const config = NodeProxyConfig.fromEnv();

    assert.strictEqual(config.port, 4000);
    assert.strictEqual(config.host, "0.0.0.0");
    assert.strictEqual(config.timeoutMs, 300_000);
    assert.strictEqual(config.upstreamBase, "https://agentrouter.org/v1");
    assert.strictEqual(config.fallbackApiKey, "sk-test-key");
    assert.ok(config.userAgent.includes("QwenCode"));
    assert.strictEqual(config.anthropicUpstreamBase, "https://agentrouter.org");
    // Anthropic fallback inherits from OpenAI key when ANTHROPIC_API_KEY is unset
    assert.strictEqual(config.anthropicFallbackApiKey, "sk-test-key");
  } finally {
    if (originalApiKey) {
      process.env.OPENAI_API_KEY = originalApiKey;
    } else {
      delete process.env.OPENAI_API_KEY;
    }
    if (originalAnthropicKey) {
      process.env.ANTHROPIC_API_KEY = originalAnthropicKey;
    } else {
      delete process.env.ANTHROPIC_API_KEY;
    }
    if (originalAnthropicBase) {
      process.env.ANTHROPIC_BASE_URL = originalAnthropicBase;
    } else {
      delete process.env.ANTHROPIC_BASE_URL;
    }
  }
});

test("NodeProxyConfig.fromEnv applies overrides", () => {
  const originalApiKey = process.env.OPENAI_API_KEY;
  process.env.OPENAI_API_KEY = "sk-env-key";

  try {
    const config = NodeProxyConfig.fromEnv({
      port: 8080,
      host: "127.0.0.1",
      timeoutMs: 30_000,
      upstreamBase: "https://custom.api/v1",
      apiKey: "sk-override-key",
      userAgent: "CustomAgent/1.0",
      anthropicUpstreamBase: "https://custom-anthropic.api",
      anthropicApiKey: "sk-ant-override",
    });

    assert.strictEqual(config.port, 8080);
    assert.strictEqual(config.host, "127.0.0.1");
    assert.strictEqual(config.timeoutMs, 30_000);
    assert.strictEqual(config.upstreamBase, "https://custom.api/v1");
    assert.strictEqual(config.fallbackApiKey, "sk-override-key");
    assert.strictEqual(config.userAgent, "CustomAgent/1.0");
    assert.strictEqual(config.anthropicUpstreamBase, "https://custom-anthropic.api");
    assert.strictEqual(config.anthropicFallbackApiKey, "sk-ant-override");
  } finally {
    if (originalApiKey) {
      process.env.OPENAI_API_KEY = originalApiKey;
    } else {
      delete process.env.OPENAI_API_KEY;
    }
  }
});

test("NodeProxyConfig.fromEnv reads from environment variables", () => {
  const originalApiKey = process.env.OPENAI_API_KEY;
  const originalBaseUrl = process.env.OPENAI_BASE_URL;
  const originalUserAgent = process.env.NODE_USER_AGENT;
  const originalAnthropicKey = process.env.ANTHROPIC_API_KEY;
  const originalAnthropicBase = process.env.ANTHROPIC_BASE_URL;
  const originalProxyUrl = process.env.UPSTREAM_PROXY_URL;

  process.env.OPENAI_API_KEY = "sk-from-env";
  process.env.OPENAI_BASE_URL = "https://env.api/v1";
  process.env.NODE_USER_AGENT = "EnvAgent/2.0";
  process.env.ANTHROPIC_API_KEY = "sk-ant-from-env";
  process.env.ANTHROPIC_BASE_URL = "https://ant-env.api";
  process.env.UPSTREAM_PROXY_URL = "socks5://user:pass@127.0.0.1:1080";

  try {
    const config = NodeProxyConfig.fromEnv();

    assert.strictEqual(config.fallbackApiKey, "sk-from-env");
    assert.strictEqual(config.upstreamBase, "https://env.api/v1");
    assert.strictEqual(config.userAgent, "EnvAgent/2.0");
    assert.strictEqual(config.anthropicFallbackApiKey, "sk-ant-from-env");
    assert.strictEqual(config.anthropicUpstreamBase, "https://ant-env.api");
    assert.strictEqual(config.upstreamProxyUrl, "socks5://user:pass@127.0.0.1:1080");
  } finally {
    if (originalApiKey) {
      process.env.OPENAI_API_KEY = originalApiKey;
    } else {
      delete process.env.OPENAI_API_KEY;
    }
    if (originalBaseUrl) {
      process.env.OPENAI_BASE_URL = originalBaseUrl;
    } else {
      delete process.env.OPENAI_BASE_URL;
    }
    if (originalUserAgent) {
      process.env.NODE_USER_AGENT = originalUserAgent;
    } else {
      delete process.env.NODE_USER_AGENT;
    }
    if (originalAnthropicKey) {
      process.env.ANTHROPIC_API_KEY = originalAnthropicKey;
    } else {
      delete process.env.ANTHROPIC_API_KEY;
    }
    if (originalAnthropicBase) {
      process.env.ANTHROPIC_BASE_URL = originalAnthropicBase;
    } else {
      delete process.env.ANTHROPIC_BASE_URL;
    }
    if (originalProxyUrl) {
      process.env.UPSTREAM_PROXY_URL = originalProxyUrl;
    } else {
      delete process.env.UPSTREAM_PROXY_URL;
    }
  }
});

test("NodeProxyConfig.fromEnv allows missing API key", () => {
  const originalApiKey = process.env.OPENAI_API_KEY;
  const originalAnthropicKey = process.env.ANTHROPIC_API_KEY;
  delete process.env.OPENAI_API_KEY;
  delete process.env.ANTHROPIC_API_KEY;

  try {
    const config = NodeProxyConfig.fromEnv();
    assert.strictEqual(config.fallbackApiKey, null);
    assert.strictEqual(config.anthropicFallbackApiKey, null);
  } finally {
    if (originalApiKey) {
      process.env.OPENAI_API_KEY = originalApiKey;
    }
    if (originalAnthropicKey) {
      process.env.ANTHROPIC_API_KEY = originalAnthropicKey;
    }
  }
});
