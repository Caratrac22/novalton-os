import { scopedSessionFetch } from "@/lib/api/scoped";

export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  const headers = new Headers({ Accept: "text/event-stream" });
  const lastEventId = request.headers.get("last-event-id");
  if (lastEventId) headers.set("Last-Event-ID", lastEventId);
  try {
    const upstream = await scopedSessionFetch("events/stream", { cache: "no-store", headers, signal: request.signal });
    if (!upstream.ok || !upstream.body) return new Response("Activity stream unavailable", { status: [401, 403, 404].includes(upstream.status) ? upstream.status : 502 });
    return new Response(upstream.body, { headers: { "Cache-Control": "no-cache, no-store", "Content-Type": "text/event-stream", "X-Accel-Buffering": "no" } });
  } catch { return new Response("Activity stream unavailable", { status: 502 }); }
}
