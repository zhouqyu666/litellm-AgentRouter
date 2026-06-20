import nodeFetch from "node-fetch";
import { ProxyAgent } from "proxy-agent";

export function normalizeProxyUrl(proxyUrl) {
  const value = (proxyUrl ?? "").trim();
  if (!value) {
    return null;
  }

  const parsed = new URL(value);
  const protocol = parsed.protocol.toLowerCase();
  if (!["http:", "https:", "socks:", "socks4:", "socks4a:", "socks5:", "socks5h:"].includes(protocol)) {
    throw new Error(`Unsupported upstream proxy protocol: ${protocol}`);
  }
  return value;
}

export function maskProxyUrl(proxyUrl) {
  const value = normalizeProxyUrl(proxyUrl);
  if (!value) {
    return null;
  }

  const parsed = new URL(value);
  if (parsed.username || parsed.password) {
    parsed.username = "***";
    parsed.password = "***";
  }
  return parsed.toString();
}

export function createProxyFetch(proxyUrl) {
  const value = normalizeProxyUrl(proxyUrl);
  if (!value) {
    return null;
  }

  const proxyAgent = new ProxyAgent({
    getProxyForUrl: () => value,
  });

  return async function fetchViaProxy(url, init = {}) {
    return nodeFetch(url, {
      ...init,
      agent: proxyAgent,
    });
  };
}
