import { scopedSessionFetch } from "@/lib/api/scoped";
export async function GET() {
  try {
    const upstream = await scopedSessionFetch("provider-keys");
    return new Response(await upstream.text(), { status: upstream.status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
  } catch { return new Response("Service indisponible", { status: 503 }); }
}
