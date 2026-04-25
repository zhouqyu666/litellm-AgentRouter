import { Readable } from "node:stream";
import { logEvent } from "../utils/logger.mjs";
import { buildForwardHeaders, headersToPlainObject, readJsonBody } from "../utils/http-utils.mjs";
import { createRouteHandlers } from "./routes.mjs";
import { createAnthropicRouteHandlers } from "./anthropic-routes.mjs";

/**
 * Extract an API key from request headers.
 * Checks x-api-key header first (Anthropic convention), then
 * falls back to Authorization: Bearer (OpenAI convention).
 * Returns null when neither is present.
 */
function extractApiKey(headers) {
  // Anthropic sends via x-api-key header
  const xApiKey = headers["x-api-key"];
  if (xApiKey) return xApiKey;

  // OpenAI sends via Authorization: Bearer
  const auth = headers["authorization"];
  if (!auth) return null;
  const parts = auth.split(/\s+/);
  if (parts.length === 2 && parts[0].toLowerCase() === "bearer") {
    return parts[1];
  }
  return null;
}

// Keep old name as alias for backward compatibility in tests
export const extractBearerToken = extractApiKey;

export class NodeRequestRouter {
  /**
   * @param {object}   opts
   * @param {function} opts.clientResolver  (apiKey) => OpenAI client
   * @param {string|null} opts.fallbackApiKey  key used when request has no Authorization header (OpenAI)
   * @param {function} [opts.anthropicClientResolver]  (apiKey) => Anthropic client
   * @param {string|null} [opts.anthropicFallbackApiKey]  key for Anthropic when no x-api-key header
   * @param {object}   opts.logger
   */
  constructor({ clientResolver, fallbackApiKey, anthropicClientResolver, anthropicFallbackApiKey, logger }) {
    this.logger = logger;
    this.fallbackApiKey = fallbackApiKey;
    this.anthropicFallbackApiKey = anthropicFallbackApiKey ?? null;

    // Debug: log fallback keys on startup
    logEvent(this.logger, {
      event: "router_initialized",
      has_fallback_key: !!fallbackApiKey,
      has_anthropic_fallback: !!this.anthropicFallbackApiKey,
      anthropic_fallback_preview: this.anthropicFallbackApiKey ? this.anthropicFallbackApiKey.slice(0, 10) + "..." : null,
    });

    // Merge OpenAI and Anthropic route handler maps
    this.handlers = {};
    if (clientResolver) {
      Object.assign(this.handlers, createRouteHandlers(clientResolver));
    }
    if (anthropicClientResolver) {
      Object.assign(this.handlers, createAnthropicRouteHandlers(anthropicClientResolver));
    }
  }

  async handle(req, res) {
    const method = (req.method ?? "GET").toUpperCase();
    const url = this._parseUrl(req);
    const requestId = req.headers["x-request-id"] ?? null;
    const startTime = Date.now();

    // Debug: log all incoming headers
    logEvent(this.logger, {
      event: "request_received",
      method,
      path: url.pathname,
      request_id: requestId,
      headers: {
        "x-api-key": req.headers["x-api-key"] ? "present" : "absent",
        "authorization": req.headers["authorization"] ? "present" : "absent",
      },
    });

    if (method !== "POST") {
      return this._sendError(res, 405, "Method not allowed", requestId);
    }

    const handler = this.handlers[url.pathname];
    if (!handler) {
      return this._sendError(res, 404, "Not found", requestId);
    }

    let payload;
    try {
      payload = await readJsonBody(req);
    } catch (error) {
      return this._sendError(res, 400, "Invalid JSON payload", requestId, error.message);
    }

    // Resolve the API key: prefer the key from the incoming request, fall back to config
    const requestApiKey = extractApiKey(req.headers);
    const apiKey = requestApiKey ?? this._getFallbackKey(url.pathname);

    // Debug: log key resolution
    logEvent(this.logger, {
      event: "api_key_resolved",
      path: url.pathname,
      has_request_key: !!requestApiKey,
      request_key_preview: requestApiKey ? requestApiKey.slice(0, 10) + "..." : null,
      has_resolved_key: !!apiKey,
      resolved_key_preview: apiKey ? apiKey.slice(0, 10) + "..." : null,
    });

    if (!apiKey) {
      return this._sendError(res, 401, "No API key provided (Authorization header, x-api-key, or fallback env)", requestId);
    }

    const forwardedHeaders = buildForwardHeaders(req.headers);

    try {
      const result = await handler(payload, forwardedHeaders, apiKey);

      // Raw passthrough responses (e.g. Anthropic transparent proxy)
      if (result.rawBody !== undefined || result.rawStream) {
        return this._sendRawResponse(res, result, startTime, requestId);
      }

      // Check if this is a streaming response
      if (result.stream) {
        if (result.streamFormat === "anthropic") {
          return this._sendAnthropicStreamingResponse(res, result.stream, forwardedHeaders, startTime, requestId);
        }
        return this._sendStreamingResponse(res, result.stream, forwardedHeaders, startTime, requestId);
      }

      // Non-streaming response
      const { data, response } = result;
      this._sendSuccess(res, data, response, forwardedHeaders, startTime);
    } catch (error) {
      const status = error?.status ?? 502;
      const message = error?.message ?? "upstream_error";
      this._sendError(res, status, message, requestId);
    }
  }

  /**
   * Return the appropriate fallback API key based on request path.
   */
  _getFallbackKey(pathname) {
    if (pathname === "/v1/messages") {
      return this.anthropicFallbackApiKey;
    }
    return this.fallbackApiKey;
  }

  _parseUrl(req) {
    const host = req.headers.host ?? "localhost";
    return req.url ? new URL(req.url, `http://${host}`) : new URL("/", "http://localhost");
  }

  _logRequest(method, path, requestId) {
    logEvent(this.logger, {
      event: "request_received",
      method,
      path,
      request_id: requestId,
    });
  }

  _sendError(res, status, error, requestId, detail = null) {
    const payload = { error };
    if (detail) {
      payload.detail = detail;
    }

    res.writeHead(status, { "Content-Type": "application/json" });
    res.end(JSON.stringify(payload));

    logEvent(this.logger, {
      event: "request_failed",
      status,
      error,
      request_id: requestId,
    });
  }

  _sendSuccess(res, data, response, forwardedHeaders, startTime) {
    const normalizedHeaders = headersToPlainObject(response.headers);
    const status = response.status ?? 200;

    // Serialize the response body
    const body = JSON.stringify(data);
    const bodyBuffer = Buffer.from(body, 'utf-8');

    // Remove transfer-encoding header if present - it's incompatible with content-length
    // HTTP spec: Transfer-Encoding and Content-Length are mutually exclusive
    delete normalizedHeaders["transfer-encoding"];
    delete normalizedHeaders["Transfer-Encoding"];

    const responseHeaders = {
      ...normalizedHeaders,
      "content-type": normalizedHeaders["content-type"] ?? "application/json",
      "content-length": bodyBuffer.length.toString(),
    };

    const requestId = normalizedHeaders["x-request-id"] ?? forwardedHeaders["X-Request-ID"];
    if (requestId) {
      responseHeaders["x-request-id"] = requestId;
    }

    res.writeHead(status, responseHeaders);
    res.end(bodyBuffer);

    logEvent(this.logger, {
      event: "request_completed",
      status,
      duration_s: ((Date.now() - startTime) / 1000).toFixed(2),
      request_id: requestId,
    });
  }

  async _sendStreamingResponse(res, stream, forwardedHeaders, startTime, requestId) {
    const responseHeaders = {
      "content-type": "text/event-stream",
      "cache-control": "no-cache",
      "connection": "keep-alive",
    };

    if (requestId) {
      responseHeaders["x-request-id"] = requestId;
    }

    res.writeHead(200, responseHeaders);

    try {
      for await (const chunk of stream) {
        const line = `data: ${JSON.stringify(chunk)}\n\n`;
        res.write(line);
      }

      res.write("data: [DONE]\n\n");
      res.end();

      logEvent(this.logger, {
        event: "request_completed",
        status: 200,
        duration_s: ((Date.now() - startTime) / 1000).toFixed(2),
        request_id: requestId,
        streaming: true,
      });
    } catch (error) {
      logEvent(this.logger, {
        event: "streaming_error",
        error: error.message,
        request_id: requestId,
      });
      res.end();
    }
  }

  /**
   * Send a raw passthrough response (no JSON serialization).
   * Used for transparent Anthropic proxying — upstream bytes pass through untouched.
   */
  _sendRawResponse(res, result, startTime, requestId) {
    const { rawBody, rawStream, rawStatus, rawHeaders } = result;
    const status = rawStatus || 200;
    const headers = { ...rawHeaders };

    if (requestId) {
      headers["x-request-id"] = requestId;
    }

    if (rawStream) {
      // Streaming: pipe raw bytes through
      res.writeHead(status, headers);

      const nodeStream = (typeof rawStream.getReader === "function")
        ? Readable.fromWeb(rawStream)
        : rawStream;

      nodeStream.pipe(res);
      nodeStream.on("error", (err) => {
        logEvent(this.logger, {
          event: "streaming_error",
          error: err.message,
          request_id: requestId,
          raw_passthrough: true,
        });
        res.end();
      });
      return;
    }

    // Non-streaming: write raw body directly (no JSON.stringify)
    const bodyBuffer = Buffer.from(rawBody, "utf-8");
    delete headers["transfer-encoding"];
    headers["content-length"] = bodyBuffer.length.toString();
    if (!headers["content-type"]) {
      headers["content-type"] = "application/json";
    }

    res.writeHead(status, headers);
    res.end(bodyBuffer);

    logEvent(this.logger, {
      event: "request_completed",
      status,
      duration_s: ((Date.now() - startTime) / 1000).toFixed(2),
      request_id: requestId,
      raw_passthrough: true,
    });
  }

  /**
   * Send an Anthropic-format SSE streaming response.
   * Anthropic SSE uses `event: {type}\ndata: {json}\n\n` format (no [DONE] sentinel).
   */
  async _sendAnthropicStreamingResponse(res, stream, forwardedHeaders, startTime, requestId) {
    const responseHeaders = {
      "content-type": "text/event-stream",
      "cache-control": "no-cache",
      "connection": "keep-alive",
    };

    if (requestId) {
      responseHeaders["x-request-id"] = requestId;
    }

    res.writeHead(200, responseHeaders);

    try {
      for await (const event of stream) {
        const eventType = event.type ?? "unknown";
        const line = `event: ${eventType}\ndata: ${JSON.stringify(event)}\n\n`;
        res.write(line);
      }

      res.end();

      logEvent(this.logger, {
        event: "request_completed",
        status: 200,
        duration_s: ((Date.now() - startTime) / 1000).toFixed(2),
        request_id: requestId,
        streaming: true,
        stream_format: "anthropic",
      });
    } catch (error) {
      logEvent(this.logger, {
        event: "streaming_error",
        error: error.message,
        request_id: requestId,
        stream_format: "anthropic",
      });
      res.end();
    }
  }
}

export function createRequestHandler({ clientResolver, fallbackApiKey, anthropicClientResolver, anthropicFallbackApiKey, logger }) {
  const router = new NodeRequestRouter({ clientResolver, fallbackApiKey, anthropicClientResolver, anthropicFallbackApiKey, logger });
  return router.handle.bind(router);
}
