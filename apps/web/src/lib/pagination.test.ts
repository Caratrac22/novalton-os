import assert from "node:assert/strict";
import test from "node:test";
import { PAGE_SIZE, pageHref, pageOffset } from "./pagination.ts";

test("pagination reaches records beyond the first hundred without losing selection", () => {
  assert.equal(pageOffset("5"), 100);
  assert.equal(PAGE_SIZE, 20);
  assert.equal(pageHref("/tasks", { project: "project-id", task: "task-id" }, 100),
    "/tasks?project=project-id&task=task-id&page=5");
  assert.equal(pageHref("/tasks", { project: "project-id" }, 80),
    "/tasks?project=project-id&page=4");
});

test("invalid and unbounded page parameters are refused", () => {
  for (const value of ["-1", "01", "5.5", "1000000", "foo", ["1", "2"]])
    assert.equal(pageOffset(value), null);
});
