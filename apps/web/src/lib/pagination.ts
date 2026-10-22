export const PAGE_SIZE = 20;
export function pageOffset(value: string | string[] | undefined): number | null {
  if (value === undefined) return 0;
  if (typeof value !== "string" || !/^(0|[1-9]\d{0,5})$/.test(value)) return null;
  const page = Number(value);
  return Number.isSafeInteger(page * PAGE_SIZE) ? page * PAGE_SIZE : null;
}

export function pageHref(path: string, params: Record<string, string | undefined>, offset: number): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value) query.set(key, value);
  if (offset > 0) query.set("page", String(offset / PAGE_SIZE));
  const suffix = query.toString();
  return suffix ? `${path}?${suffix}` : path;
}
