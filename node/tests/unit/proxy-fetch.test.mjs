import assert from "node:assert";
import { test } from "node:test";
import { createProxyFetch, maskProxyUrl, normalizeProxyUrl } from "../../lib/utils/proxy-fetch.mjs";

test("normalizeProxyUrl accepts http and socks5 proxies", () => {
  assert.strictEqual(normalizeProxyUrl("http://127.0.0.1:8080"), "http://127.0.0.1:8080");
  assert.strictEqual(
    normalizeProxyUrl("socks5://user:pass@64.188.8.141:1186"),
    "socks5://user:pass@64.188.8.141:1186",
  );
});

test("normalizeProxyUrl returns null for empty proxy", () => {
  assert.strictEqual(normalizeProxyUrl(""), null);
  assert.strictEqual(normalizeProxyUrl(null), null);
});

test("normalizeProxyUrl rejects unsupported protocols", () => {
  assert.throws(() => normalizeProxyUrl("ftp://proxy.example.com"), /Unsupported upstream proxy protocol/);
});

test("maskProxyUrl hides credentials", () => {
  assert.strictEqual(
    maskProxyUrl("socks5://user:pass@64.188.8.141:1186"),
    "socks5://***:***@64.188.8.141:1186",
  );
});

test("createProxyFetch returns null when no proxy is configured", () => {
  assert.strictEqual(createProxyFetch(""), null);
});

test("createProxyFetch returns a fetch function for proxy URL", () => {
  assert.strictEqual(typeof createProxyFetch("socks5://user:pass@64.188.8.141:1186"), "function");
});
