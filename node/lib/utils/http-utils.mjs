export function buildForwardHeaders(originalHeaders) {
  const forwarded = {};

  if (originalHeaders["x-request-id"]) {
    forwarded["X-Request-ID"] = originalHeaders["x-request-id"];
  }

  // Do NOT forward User-Agent from the incoming request.
  // The Node proxy must use the OpenAI SDK's own User-Agent when calling
  // upstream (agentrouter.org rejects non-SDK User-Agent strings).

  return forwarded;
}

export function headersToPlainObject(headers) {
  const result = {};
  
  if (headers && typeof headers.forEach === "function") {
    headers.forEach((value, key) => {
      result[key.toLowerCase()] = value;
    });
  } else if (headers && typeof headers === "object") {
    Object.entries(headers).forEach(([key, value]) => {
      result[key.toLowerCase()] = value;
    });
  }
  
  return result;
}

export async function readJsonBody(req) {
  const chunks = [];
  for await (const chunk of req) {
    chunks.push(chunk);
  }

  if (chunks.length === 0) {
    return {};
  }

  const payload = Buffer.concat(chunks).toString("utf-8");
  return JSON.parse(payload);
}
