import { NodeProxyConfig } from "../config/config.mjs";
import { NodeProxyServer } from "./server.mjs";
import { logEvent } from "../utils/logger.mjs";

export function createNodeUpstreamProxy({
  logger = console,
  ...overrides
} = {}) {
  const config = NodeProxyConfig.fromEnv(overrides);
  const proxy = new NodeProxyServer({ config, logger });

  return {
    start: async () => {
      const address = await proxy.start();
      logEvent(logger, {
        event: "startup",
        port: config.port,
        upstream_base: config.upstreamBase,
        anthropic_upstream_base: config.anthropicUpstreamBase,
        timeout_ms: config.timeoutMs,
      });
      return address;
    },
    stop: () => proxy.stop(),
    address: () => proxy.address(),
    config,
    logger,
  };
}
