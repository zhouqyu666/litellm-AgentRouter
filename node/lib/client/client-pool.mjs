import { OpenAI } from "openai";

/**
 * Pool of OpenAI clients keyed by API key.
 * Reuses existing client instances to avoid repeated SDK initialisation.
 */
export class ClientPool {
  constructor({ baseURL, timeoutMs, userAgent }) {
    this.baseURL = baseURL;
    this.timeoutMs = timeoutMs;
    this.userAgent = userAgent;
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
        defaultHeaders: {
          "User-Agent": this.userAgent,
        },
      });
      this._clients.set(apiKey, client);
    }
    return client;
  }

  get size() {
    return this._clients.size;
  }
}
