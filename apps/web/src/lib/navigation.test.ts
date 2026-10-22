import assert from "node:assert/strict";
import test from "node:test";
import { primaryNavigation, sectionForPath } from "./navigation.ts";

test("the product has exactly five distinct primary sections", () => {
  assert.deepEqual(primaryNavigation.map((item) => item.href), [
    "/", "/projects", "/control", "/environments", "/settings",
  ]);
  assert.equal(new Set(primaryNavigation.map((item) => item.label)).size, 5);
});

test("task and operator subroutes keep the right section active", () => {
  const routes = {
    "/": "/", "/projects": "/projects", "/projects/": "/projects",
    "/tasks": "/projects", "/tasks?invalid": null,
    "/operator": "/control", "/operator/dispatch-id": "/control",
    "/activity": "/control", "/control": "/control",
    "/environments": "/environments", "/settings": "/settings",
  } as const;
  for (const [pathname, expected] of Object.entries(routes)) {
    assert.equal(sectionForPath(pathname), expected, pathname);
  }
});

test("unrelated prefix matches do not mark a section as active", () => {
  for (const path of ["/projectile", "/operators", "/settings-private", "/unknown"]) {
    assert.equal(sectionForPath(path), null);
  }
});
