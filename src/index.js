import { Container } from "@cloudflare/containers";

const PUBLIC_PATHS = new Set([
  "/health",
  "/docs",
  "/openapi.json",
  "/redoc",
  "/v1/convert"
]);

export class DoclingContainer extends Container {
  defaultPort = 8000;
  sleepAfter = "10m";
}

function getAllowedOrigin(env, requestOrigin) {
  const configured = (env.CORS_ALLOW_ORIGIN || "*")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);

  if (!configured.length || configured.includes("*")) {
    return "*";
  }

  if (requestOrigin && configured.includes(requestOrigin)) {
    return requestOrigin;
  }

  return configured[0];
}

function buildCorsHeaders(env, request) {
  const requestOrigin = request.headers.get("origin");
  const allowedOrigin = getAllowedOrigin(env, requestOrigin);

  return {
    "Access-Control-Allow-Origin": allowedOrigin,
    "Access-Control-Allow-Headers": "Authorization, Content-Type, X-API-Key",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Max-Age": "86400",
    Vary: "Origin"
  };
}

function json(data, init = {}) {
  const headers = new Headers(init.headers || {});
  headers.set("Content-Type", "application/json; charset=utf-8");
  return new Response(JSON.stringify(data, null, 2), {
    ...init,
    headers
  });
}

function withCors(response, env, request) {
  const headers = new Headers(response.headers);
  const corsHeaders = buildCorsHeaders(env, request);

  for (const [key, value] of Object.entries(corsHeaders)) {
    headers.set(key, value);
  }

  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers
  });
}

function isAuthorized(request, env) {
  const configuredKeys = (env.API_KEYS || "")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);

  if (!configuredKeys.length) {
    return true;
  }

  const authHeader = request.headers.get("authorization");
  const bearerToken = authHeader?.startsWith("Bearer ")
    ? authHeader.slice("Bearer ".length).trim()
    : "";
  const apiKeyHeader = request.headers.get("x-api-key")?.trim() || "";
  const token = bearerToken || apiKeyHeader;

  return configuredKeys.includes(token);
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: buildCorsHeaders(env, request)
      });
    }

    const url = new URL(request.url);

    if (url.pathname === "/") {
      return withCors(
        json({
          service: "docling-cloudflare-api",
          endpoints: {
            health: "GET /health",
            docs: "GET /docs",
            convert: "POST /v1/convert"
          },
          auth: env.API_KEYS
            ? "Use Authorization: Bearer <token> or X-API-Key"
            : "Open access. Set API_KEYS secret to enable auth.",
          accepted_requests: [
            {
              content_type: "application/json",
              body: {
                source_url: "https://example.com/paper.pdf"
              }
            },
            {
              content_type: "multipart/form-data",
              body: {
                file: "<pdf file>"
              }
            }
          ]
        }),
        env,
        request
      );
    }

    if (!PUBLIC_PATHS.has(url.pathname)) {
      return withCors(
        json({ error: "Not found" }, { status: 404 }),
        env,
        request
      );
    }

    if (url.pathname === "/v1/convert" && !isAuthorized(request, env)) {
      return withCors(
        json({ error: "Unauthorized" }, { status: 401 }),
        env,
        request
      );
    }

    try {
      const container = env.DOCLING_CONTAINER.getByName("shared");
      const upstreamResponse = await container.fetch(request);
      return withCors(upstreamResponse, env, request);
    } catch (error) {
      return withCors(
        json(
          {
            error: "Docling container unavailable",
            detail: error instanceof Error ? error.message : String(error)
          },
          { status: 503 }
        ),
        env,
        request
      );
    }
  }
};