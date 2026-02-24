import assert from "node:assert";
import { test } from "node:test";
import { buildForwardHeaders, headersToPlainObject, readJsonBody } from "../../lib/utils/http-utils.mjs";

test("buildForwardHeaders extracts x-request-id", () => {
  const headers = {
    "x-request-id": "req-123",
    "content-type": "application/json",
  };

  const forwarded = buildForwardHeaders(headers);
  
  assert.strictEqual(forwarded["X-Request-ID"], "req-123");
  assert.strictEqual(forwarded["content-type"], undefined);
});

test("buildForwardHeaders does NOT forward user-agent (Node proxy uses its own)", () => {
  const headers = {
    "user-agent": "TestAgent/1.0",
    "accept": "application/json",
  };

  const forwarded = buildForwardHeaders(headers);

  assert.strictEqual(forwarded["User-Agent"], undefined);
  assert.strictEqual(forwarded["accept"], undefined);
});

test("buildForwardHeaders handles missing headers", () => {
  const headers = {
    "content-type": "application/json",
  };

  const forwarded = buildForwardHeaders(headers);
  
  assert.strictEqual(Object.keys(forwarded).length, 0);
});

test("headersToPlainObject converts Headers object", () => {
  const headers = new Headers();
  headers.set("Content-Type", "application/json");
  headers.set("X-Request-ID", "req-456");

  const plain = headersToPlainObject(headers);
  
  assert.strictEqual(plain["content-type"], "application/json");
  assert.strictEqual(plain["x-request-id"], "req-456");
});

test("headersToPlainObject converts plain object", () => {
  const headers = {
    "Content-Type": "application/json",
    "X-Request-ID": "req-789",
  };

  const plain = headersToPlainObject(headers);
  
  assert.strictEqual(plain["content-type"], "application/json");
  assert.strictEqual(plain["x-request-id"], "req-789");
});

test("headersToPlainObject handles null/undefined", () => {
  assert.deepStrictEqual(headersToPlainObject(null), {});
  assert.deepStrictEqual(headersToPlainObject(undefined), {});
});

test("readJsonBody parses JSON from request stream", async () => {
  const payload = { model: "gpt-4", messages: [] };
  const buffer = Buffer.from(JSON.stringify(payload));

  const mockReq = {
    async *[Symbol.asyncIterator]() {
      yield buffer;
    },
  };

  const result = await readJsonBody(mockReq);
  assert.deepStrictEqual(result, payload);
});

test("readJsonBody handles empty request", async () => {
  const mockReq = {
    async *[Symbol.asyncIterator]() {
      // No chunks
    },
  };

  const result = await readJsonBody(mockReq);
  assert.deepStrictEqual(result, {});
});

test("readJsonBody handles chunked data", async () => {
  const payload = { large: "data" };
  const json = JSON.stringify(payload);
  const chunk1 = Buffer.from(json.slice(0, 5));
  const chunk2 = Buffer.from(json.slice(5));

  const mockReq = {
    async *[Symbol.asyncIterator]() {
      yield chunk1;
      yield chunk2;
    },
  };

  const result = await readJsonBody(mockReq);
  assert.deepStrictEqual(result, payload);
});
