/**
 * Build route handlers that resolve the OpenAI client dynamically per-request.
 *
 * @param {function} clientResolver  (apiKey) => OpenAI client instance
 */
export function createRouteHandlers(clientResolver) {
  const wrapHandler = (handlerFn) => async (body, forwardedHeaders, apiKey) => {
    const client = clientResolver(apiKey);
    const handler = handlerFn(client);

    if (!handler) {
      throw new Error("Handler not available");
    }

    // Check if this is a streaming request
    const isStreaming = body.stream === true;

    const upstreamPromise = handler(body, { headers: forwardedHeaders });

    // For streaming requests, return the stream directly
    if (isStreaming) {
      const stream = await upstreamPromise;
      return {
        stream,
      };
    }

    // For non-streaming requests, use withResponse if available
    if (typeof upstreamPromise?.withResponse === "function") {
      return upstreamPromise.withResponse();
    }

    const data = await upstreamPromise;
    return {
      data,
      response: {
        status: 200,
        headers: new Headers(),
      },
    };
  };

  return {
    "/v1/chat/completions": wrapHandler(
      (client) => client.chat?.completions?.create?.bind(client.chat.completions)
    ),
    "/v1/completions": wrapHandler(
      (client) => client.completions?.create?.bind(client.completions)
    ),
  };
}
