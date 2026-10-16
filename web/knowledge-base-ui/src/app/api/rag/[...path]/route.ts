/**
 * Server-side proxy from the browser to rag-api (BFF). Only `/v1/agents/{uuid}/...` paths are
 * forwarded. Auth: a user token forwarded by the platform (Authorization header) wins; in local
 * development (DEV_AUTH=true) the proxy signs a short-lived gateway-style JWT for DEV_TENANT_ID.
 * Secrets stay on the server. Streaming bodies (uploads, SSE answers) pass through unbuffered.
 */
import { SignJWT } from "jose";
import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

const UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
const ALLOWED = new RegExp(`^v1/agents/${UUID}/(knowledge-base(/status)?|sources(/.*)?|test|answer)$`, "i");

async function devToken(): Promise<string | null> {
  if (process.env.DEV_AUTH !== "true") return null;
  const secret = process.env.DEV_JWT_SECRET;
  const tenant = process.env.DEV_TENANT_ID;
  if (!secret || !tenant) return null;
  return new SignJWT({ tenant_id: tenant })
    .setProtectedHeader({ alg: "HS256" })
    .setSubject("knowledge-base-ui-dev")
    .setIssuedAt()
    .setExpirationTime("5m")
    .sign(new TextEncoder().encode(secret));
}

async function proxy(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }): Promise<Response> {
  const { path } = await ctx.params;
  const joined = path.join("/");
  if (!ALLOWED.test(joined)) {
    return Response.json({ error: { code: "not_found", message: "Not found", details: {} } }, { status: 404 });
  }
  const base = process.env.RAG_API_URL ?? "http://localhost:8000";
  const target = `${base.replace(/\/$/, "")}/${joined}${req.nextUrl.search}`;

  const headers = new Headers();
  for (const name of ["content-type", "accept", "accept-language"]) {
    const value = req.headers.get(name);
    if (value) headers.set(name, value);
  }
  const forwarded = req.headers.get("authorization");
  const token = forwarded ? null : await devToken();
  if (forwarded) headers.set("authorization", forwarded);
  else if (token) headers.set("authorization", `Bearer ${token}`);

  const hasBody = !["GET", "HEAD", "DELETE"].includes(req.method);
  const upstream = await fetch(target, {
    method: req.method,
    headers,
    body: hasBody ? req.body : undefined,
    // Required by Node fetch to stream a request body (multipart uploads).
    ...(hasBody ? { duplex: "half" } : {}),
    cache: "no-store",
  } as RequestInit);

  const out = new Headers();
  for (const name of ["content-type", "cache-control"]) {
    const value = upstream.headers.get(name);
    if (value) out.set(name, value);
  }
  if (out.get("content-type")?.startsWith("text/event-stream")) out.set("x-accel-buffering", "no");
  return new Response(upstream.body, { status: upstream.status, headers: out });
}

export { proxy as GET, proxy as POST, proxy as PUT, proxy as DELETE };
