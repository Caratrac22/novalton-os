import assert from "node:assert/strict";
import test from "node:test";
import { buildPublicationRequest, PUBLICATION_AUTHORITY_FIELDS, publicationVisibleForCommit } from "./github-publication.ts";

test("publication prepare request contains only title and body", () => {
  const request = buildPublicationRequest("Title", "Body");
  assert.deepEqual(Object.keys(request), ["title", "body"]);
  assert.equal(PUBLICATION_AUTHORITY_FIELDS.some((field) => field in request), false);
});
test("publication bounds reject without truncation", () => {
  assert.throws(() => buildPublicationRequest("", ""), /title_out_of_bounds/);
  assert.throws(() => buildPublicationRequest("x".repeat(161), ""), /title_out_of_bounds/);
  const body = "x".repeat(16_384); assert.equal(buildPublicationRequest("x", body).body, body);
  assert.throws(() => buildPublicationRequest("x", "x".repeat(16_385)), /body_out_of_bounds/);
});
test("publication is visible only for a successful local commit", () => {
  assert.equal(publicationVisibleForCommit("APPLIED"), true);
  assert.equal(publicationVisibleForCommit("PENDING_APPROVAL"), false);
  assert.equal(publicationVisibleForCommit("REJECTED"), false);
  assert.equal(publicationVisibleForCommit("FAILED"), false);
  assert.equal(publicationVisibleForCommit(undefined), false);
});
