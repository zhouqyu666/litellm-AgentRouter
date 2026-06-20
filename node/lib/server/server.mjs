import http from "node:http";
import { logEvent } from "../utils/logger.mjs";
import { createRequestHandler } from "../router/router.mjs";
import { ClientPool } from "../client/client-pool.mjs";
import { AnthropicClientPool } from "../client/anthropic-client-pool.mjs";
import { readJsonBody } from "../utils/http-utils.mjs";
import { maskProxyUrl, normalizeProxyUrl } from "../utils/proxy-fetch.mjs";

export class NodeProxyServer {
  constructor({ config, logger }) {
    this.config = config;
    this.logger = logger;
    this.clientPool = new ClientPool({
      baseURL: config.upstreamBase,
      timeoutMs: config.timeoutMs,
      userAgent: config.userAgent,
      upstreamProxyUrl: config.upstreamProxyUrl,
      logger,
    });
    this.anthropicClientPool = new AnthropicClientPool({
      baseURL: config.anthropicUpstreamBase,
      timeoutMs: config.timeoutMs,
      upstreamProxyUrl: config.upstreamProxyUrl,
      logger,
    });
    const publicHandler = createRequestHandler({
        clientResolver: (apiKey) => this.clientPool.get(apiKey),
        fallbackApiKey: config.fallbackApiKey,
        anthropicClientResolver: (apiKey) => this.anthropicClientPool.get(apiKey),
        anthropicFallbackApiKey: config.anthropicFallbackApiKey,
        logger,
      });
    this.server = http.createServer((req, res) => this._handle(req, res, publicHandler));
  }

  async _handle(req, res, publicHandler) {
    const url = req.url ? new URL(req.url, "http://localhost") : new URL("/", "http://localhost");
    if (url.pathname === "/__admin/upstream-proxy") {
      return this._handleUpstreamProxyAdmin(req, res);
    }
    return publicHandler(req, res);
  }

  async _handleUpstreamProxyAdmin(req, res) {
    if ((req.method ?? "GET").toUpperCase() !== "PUT") {
      return this._sendJson(res, 405, { error: "Method not allowed" });
    }

    let payload;
    try {
      payload = await readJsonBody(req);
    } catch (error) {
      return this._sendJson(res, 400, { error: "Invalid JSON payload", detail: error.message });
    }

    const proxyUrl = normalizeProxyUrl(payload.proxy_url ?? "");
    this.config.upstreamProxyUrl = proxyUrl;
    this.clientPool.setUpstreamProxyUrl(proxyUrl);
    this.anthropicClientPool.setUpstreamProxyUrl(proxyUrl);

    logEvent(this.logger, {
      event: "upstream_proxy_updated",
      upstream_proxy_enabled: Boolean(proxyUrl),
      proxy_url: maskProxyUrl(proxyUrl),
    });

    return this._sendJson(res, 200, {
      message: "Upstream proxy updated",
      upstream_proxy_enabled: Boolean(proxyUrl),
      proxy_url: maskProxyUrl(proxyUrl),
    });
  }

  _sendJson(res, status, payload) {
    const body = JSON.stringify(payload);
    res.writeHead(status, {
      "content-type": "application/json",
      "content-length": Buffer.byteLength(body),
    });
    res.end(body);
  }

  start() {
    return new Promise((resolve, reject) => {
      const onError = (error) => {
        this.server.off("listening", onListen);
        reject(error);
      };

      const onListen = () => {
        this.server.off("error", onError);
        const address = this.server.address();
        logEvent(this.logger, {
          event: "ready",
          port: address?.port ?? this.config.port,
          upstream_base: this.config.upstreamBase,
          anthropic_upstream_base: this.config.anthropicUpstreamBase,
          upstream_proxy_enabled: Boolean(this.config.upstreamProxyUrl),
        });
        resolve(address);
      };

      this.server.once("error", onError);
      this.server.once("listening", onListen);
      this.server.listen(this.config.port, this.config.host);
    });
  }

  stop() {
    return new Promise((resolve, reject) => {
      if (!this.server.listening) {
        resolve();
        return;
      }

      this.server.close((error) => {
        if (error) {
          reject(error);
          return;
        }
        logEvent(this.logger, { event: "shutdown" });
        resolve();
      });
    });
  }

  address() {
    return this.server.address();
  }
}
