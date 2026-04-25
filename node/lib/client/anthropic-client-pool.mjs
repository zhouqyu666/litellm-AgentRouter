import Anthropic from "@anthropic-ai/sdk";

/**
 * Pool of Anthropic clients keyed by API key.
 * Reuses existing client instances to avoid repeated SDK initialisation.
 */
export class AnthropicClientPool {
  constructor({ baseURL, timeoutMs, logger }) {
    this.baseURL = baseURL;
    this.timeoutMs = timeoutMs;
    this.logger = logger || console;
    this._clients = new Map();
  }

  /**
   * Return an Anthropic client for the given API key.
   * Creates a new instance on first call for each unique key, then caches it.
   */
  get(apiKey) {
    if (!apiKey) {
      throw new Error("API key is required to obtain an Anthropic client");
    }

    let client = this._clients.get(apiKey);
    if (!client) {
      this.logger.log(JSON.stringify({
        anthropic_client: {
          event: "creating_client",
          base_url: this.baseURL,
          api_key_preview: apiKey.slice(0, 10) + "...",
          timeout_ms: this.timeoutMs,
        }
      }));

      client = new Anthropic({
        apiKey: null,
        authToken: apiKey,
        baseURL: this.baseURL,
        timeout: this.timeoutMs,
      });
      this._clients.set(apiKey, client);
    }
    return client;
  }

  get size() {
    return this._clients.size;
  }
}
