/**
 * Build route handlers for the Anthropic Messages API using the Anthropic SDK.
 *
 * Uses the real Anthropic SDK client (via clientResolver) so that all
 * authentication headers, TLS behaviour, and client fingerprinting match
 * what agentrouter.org expects from a genuine SDK client.
 *
 * @param {function} clientResolver  (apiKey) => Anthropic client instance
 */
export function createAnthropicRouteHandlers(clientResolver) {
  return {
    "/v1/messages": async (body, forwardedHeaders, apiKey) => {
      console.log(JSON.stringify({
        anthropic_route: {
          event: "handling_request",
          api_key_preview: apiKey ? apiKey.slice(0, 10) + "..." : null,
          model: body.model,
          stream: body.stream,
        }
      }));

      const client = clientResolver(apiKey);
      const isStreaming = body.stream === true;

      const options = {};
      if (forwardedHeaders["X-Request-ID"]) {
        options.headers = { "X-Request-ID": forwardedHeaders["X-Request-ID"] };
      }

      try {
        const upstreamPromise = client.messages.create(body, options);

        if (isStreaming) {
          const stream = await upstreamPromise;
          return { stream, streamFormat: "anthropic" };
        }

        if (typeof upstreamPromise?.withResponse === "function") {
          return upstreamPromise.withResponse();
        }

        const data = await upstreamPromise;
        return {
          data,
          response: { status: 200, headers: new Headers() },
        };
      } catch (error) {
        console.log(JSON.stringify({
          anthropic_route: {
            event: "sdk_error",
            error: error.message,
            status: error.status,
          }
        }));
        throw error;
      }
    },
  };
}
