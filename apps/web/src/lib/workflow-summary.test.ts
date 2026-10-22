import assert from "node:assert/strict";
import test from "node:test";
import { summarizeWorkflows } from "./workflow-summary.ts";

test("empty runs are actual zero counts", () => {
  assert.deepEqual(summarizeWorkflows([]), {
    CREATED: 0, RUNNING: 0, COMPLETED: 0, FAILED: 0, CANCELLED: 0,
  });
});

test("the snapshot counts every governed workflow state once", () => {
  assert.deepEqual(summarizeWorkflows([
    { status: "CREATED" }, { status: "RUNNING" }, { status: "RUNNING" },
    { status: "COMPLETED" }, { status: "FAILED" }, { status: "CANCELLED" },
  ]), { CREATED: 1, RUNNING: 2, COMPLETED: 1, FAILED: 1, CANCELLED: 1 });
});
