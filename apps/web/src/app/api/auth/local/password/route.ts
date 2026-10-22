import { NextResponse } from "next/server";
import { scopedSessionFetch, isRecord } from "@/lib/api/scoped";
import { cookieOptions, sessionCookie } from "@/lib/operator-oidc";
import { verifiedMutationOrigin } from "@/lib/operator-origin";

export async function POST(request: Request) {
  if (!verifiedMutationOrigin(request)) return new Response("Accès refusé", { status: 403 });
  let body: unknown;
  try { body = await request.json(); } catch { return Response.json({ message: "Saisie invalide." }, { status: 400 }); }
  if (!isRecord(body) || typeof body.current !== "string" || typeof body.replacement !== "string" ||
      body.current.length > 128 || body.replacement.length < 12 || body.replacement.length > 128) return Response.json({ message: "Saisie invalide." }, { status: 400 });
  try {
    const upstream = await scopedSessionFetch("account/password", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body), signal: AbortSignal.timeout(7000) });
    if (!upstream.ok) return Response.json({ message: upstream.status === 401 ? "Mot de passe ou session invalide." : "Changement indisponible." }, { status: upstream.status });
    const response = NextResponse.json({ ok: true });
    response.cookies.set(sessionCookie, "", { ...cookieOptions, maxAge: 0 });
    response.cookies.set("__Host-novalton-operator-workspace", "", { ...cookieOptions, maxAge: 0 });
    return response;
  } catch { return Response.json({ message: "Service indisponible." }, { status: 503 }); }
}
