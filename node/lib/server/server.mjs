import http from "node:http";
import { logEvent } from "../utils/logger.mjs";
import { createRequestHandler } from "../router/router.mjs";
import { ClientPool } from "../client/client-pool.mjs";
import { AnthropicClientPool } from "../client/anthropic-client-pool.mjs";

export class NodeProxyServer {
  constructor({ config, logger }) {
    this.config = config;
    this.logger = logger;
    this.clientPool = new ClientPool({
      baseURL: config.upstreamBase,
      timeoutMs: config.timeoutMs,
      userAgent: config.userAgent,
    });
    this.anthropicClientPool = new AnthropicClientPool({
      baseURL: config.anthropicUpstreamBase,
      timeoutMs: config.timeoutMs,
    });
    this.server = http.createServer(
      createRequestHandler({
        clientResolver: (apiKey) => this.clientPool.get(apiKey),
        fallbackApiKey: config.fallbackApiKey,
        anthropicClientResolver: (apiKey) => this.anthropicClientPool.get(apiKey),
        anthropicFallbackApiKey: config.anthropicFallbackApiKey,
        logger,
      })
    );
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
