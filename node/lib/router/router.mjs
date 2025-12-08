import { logEvent } from "../utils/logger.mjs";
import { buildForwardHeaders, headersToPlainObject, readJsonBody } from "../utils/http-utils.mjs";
import { createRouteHandlers } from "./routes.mjs";

export class NodeRequestRouter {
  constructor({ client, logger }) {
    this.logger = logger;
    this.handlers = createRouteHandlers(client);
  }

  async handle(req, res) {
    const method = (req.method ?? "GET").toUpperCase();
    const url = this._parseUrl(req);
    const requestId = req.headers["x-request-id"] ?? null;
    const startTime = Date.now();

    this._logRequest(method, url.pathname, requestId);

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

    const forwardedHeaders = buildForwardHeaders(req.headers);

    try {
      const result = await handler(payload, forwardedHeaders);
      
      // Check if this is a streaming response
      if (result.stream) {
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
}

export function createRequestHandler({ client, logger }) {
  const router = new NodeRequestRouter({ client, logger });
  return router.handle.bind(router);
}
