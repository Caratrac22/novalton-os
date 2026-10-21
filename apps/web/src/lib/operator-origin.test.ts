import assert from "node:assert/strict";
import { test } from "node:test";
import { verifiedMutationOrigin } from "./operator-origin.ts";

test("cookie-backed decisions require an explicitly configured same HTTPS origin", () => {
  const before = process.env.NOVALTON_WEB_ORIGIN;
  try {
    delete process.env.NOVALTON_WEB_ORIGIN;
    assert.equal(verifiedMutationOrigin(new Request("https://example.test/", { headers: { Origin: "https://example.test" } })), false);
    process.env.NOVALTON_WEB_ORIGIN = "https://example.test";
    assert.equal(verifiedMutationOrigin(new Request("https://example.test/", { headers: { Origin: "https://example.test" } })), true);
    assert.equal(verifiedMutationOrigin(new Request("https://example.test/")), false);
    assert.equal(verifiedMutationOrigin(new Request("https://example.test/", { headers: { Origin: "https://other.test" } })), false);
    process.env.NOVALTON_WEB_ORIGIN = "http://example.test";
    assert.equal(verifiedMutationOrigin(new Request("http://example.test/", { headers: { Origin: "http://example.test" } })), false);
  } finally {
    if (before === undefined) delete process.env.NOVALTON_WEB_ORIGIN;
    else process.env.NOVALTON_WEB_ORIGIN = before;
  }
});
