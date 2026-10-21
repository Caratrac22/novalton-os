/** A fixed HTTPS origin is required for cookie-backed operator mutations. */
export function verifiedMutationOrigin(request: Request): boolean {
  const configured = process.env.NOVALTON_WEB_ORIGIN;
  if (!configured) return false;
  try {
    const expected = new URL(configured);
    return expected.protocol === "https:" && expected.origin === configured &&
      request.headers.get("origin") === expected.origin;
  } catch { return false; }
}
