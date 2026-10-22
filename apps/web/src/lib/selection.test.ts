import assert from "node:assert/strict";
import { test } from "node:test";
import { selectVisibleRecord } from "./selection.ts";

const records = [{ id: "a" }, { id: "b" }];

test("a selected project or task cannot silently fall through to another visible record", () => {
  assert.equal(selectVisibleRecord(records, "b")?.id, "b");
  assert.equal(selectVisibleRecord(records, "outside"), null);
  assert.equal(selectVisibleRecord(records)?.id, "a");
  assert.equal(selectVisibleRecord([], "outside"), null);
});
