import { OpenAI } from "openai";
import { createProxyFetch, maskProxyUrl } from "../utils/proxy-fetch.mjs";

/**
 * Pool of OpenAI clients keyed by API key.
 * Reuses existing client instances to avoid repeated SDK initialisation.
 */
export class ClientPool {
  constructor({ baseURL, timeoutMs, userAgent, upstreamProxyUrl, logger }) {
    this.baseURL = baseURL;
    this.timeoutMs = timeoutMs;
    this.userAgent = userAgent;
    this.upstreamProxyUrl = upstreamProxyUrl;
    this.logger = logger || console;
    this.fetch = createProxyFetch(upstreamProxyUrl);
    this._clients = new Map();
  }

  /**
   * Return an OpenAI client for the given API key.
   * Creates a new instance on first call for each unique key, then caches it.
   */
  get(apiKey) {
    if (!apiKey) {
      throw new Error("API key is required to obtain an OpenAI client");
    }

    let client = this._clients.get(apiKey);
    if (!client) {
      client = new OpenAI({
        apiKey,
        baseURL: this.baseURL,
        timeout: this.timeoutMs,
        ...(this.fetch ? { fetch: this.fetch } : {}),
        defaultHeaders: {
          "User-Agent": this.userAgent,
        },
      });
      if (this.fetch) {
        this.logger.log(JSON.stringify({
          openai_client: {
            event: "using_upstream_proxy",
            proxy_url: maskProxyUrl(this.upstreamProxyUrl),
          },
        }));
      }
      this._clients.set(apiKey, client);
    }
    return client;
  }

  get size() {
    return this._clients.size;
  }

  setUpstreamProxyUrl(upstreamProxyUrl) {
    this.upstreamProxyUrl = upstreamProxyUrl;
    this.fetch = createProxyFetch(upstreamProxyUrl);
    this._clients.clear();
  }
}
