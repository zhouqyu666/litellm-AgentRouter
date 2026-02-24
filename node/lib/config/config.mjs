import {
  DEFAULT_PORT,
  DEFAULT_HOST,
  DEFAULT_TIMEOUT_SECONDS,
  DEFAULT_UPSTREAM_BASE,
} from "./constants.mjs";
import { DEFAULT_USER_AGENT } from "../fetch/fetchVersion.mjs";

export class NodeProxyConfig {
  constructor({ port, host, timeoutMs, upstreamBase, fallbackApiKey, userAgent }) {
    this.port = port;
    this.host = host;
    this.timeoutMs = timeoutMs;
    this.upstreamBase = upstreamBase;
    this.fallbackApiKey = fallbackApiKey;
    this.userAgent = userAgent;
  }

  static fromEnv(overrides = {}) {
    const port = overrides.port ?? DEFAULT_PORT;
    const host = overrides.host ?? DEFAULT_HOST;
    const timeoutMs = overrides.timeoutMs ?? DEFAULT_TIMEOUT_SECONDS * 1000;
    const upstreamBase = overrides.upstreamBase ?? process.env.OPENAI_BASE_URL ?? DEFAULT_UPSTREAM_BASE;
    const userAgent = overrides.userAgent ?? process.env.NODE_USER_AGENT ?? DEFAULT_USER_AGENT;

    // API key is optional at config level; it can come from each request's
    // Authorization header (forwarded by LiteLLM with per-key entries).
    const fallbackApiKey = overrides.apiKey
      ?? process.env.OPENAI_API_KEY
      ?? null;

    return new NodeProxyConfig({
      port,
      host,
      timeoutMs,
      upstreamBase,
      fallbackApiKey,
      userAgent,
    });
  }
}
