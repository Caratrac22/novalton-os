"use strict";

const assert = require("node:assert/strict");
const { createHash } = require("node:crypto");
const {
  mkdtempSync,
  mkdirSync,
  writeFileSync,
  readFileSync,
  rmSync,
  symlinkSync,
} = require("node:fs");
const { createRequire } = require("node:module");
const { tmpdir } = require("node:os");
const { join, resolve } = require("node:path");
const { test } = require("node:test");
const { ESLint } = require("eslint");

const project = resolve(__dirname, "../..");
const pluginRequire = createRequire(
  require.resolve("@next/eslint-plugin-next"),
);
const glob = pluginRequire("fast-glob");
const globRequire = createRequire(pluginRequire.resolve("fast-glob"));
const matcher = globRequire("micromatch");
const { getRootDirs } = pluginRequire("./utils/get-root-dirs.js");

function fixture(run) {
  const root = mkdtempSync(join(tmpdir(), "novalton-next-root-glob-"));
  try {
    for (const dir of [
      "apps/one/pages",
      "apps/two/src/app/account",
      "apps/.hidden",
      "other",
    ]) {
      mkdirSync(join(root, dir), { recursive: true });
    }
    writeFileSync(
      join(root, "apps/one/pages/fixture-one.tsx"),
      "export default function Page() { return null; }",
    );
    writeFileSync(
      join(root, "apps/two/src/app/account/page.tsx"),
      "export default function Page() { return null; }",
    );
    writeFileSync(join(root, "apps/file.txt"), "not a directory");
    return run(root);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

test("the Next plugin resolves the real replacement and the vulnerable chain is absent", () => {
  assert.equal(
    globRequire("micromatch/package.json").name,
    "@novalton/fast-glob-matcher",
  );
  assert.equal(pluginRequire("../package.json").version, "16.3.8");
  assert.equal(
    createHash("sha256")
      .update(readFileSync(pluginRequire.resolve("./utils/get-root-dirs.js")))
      .digest("hex"),
    "886677432990a735e5ebdfb345ff1cbd40e264f9947a8432eeeb254b3a926bde",
  );
  assert.equal(pluginRequire("fast-glob/package.json").version, "3.3.1");
  assert.equal(
    createHash("sha256")
      .update(readFileSync(globRequire.resolve("./utils/pattern.js")))
      .digest("hex"),
    "7f5e77e8b047207114780d33bb3eadbbc921294033eeae15c0fa82eb137bbad3",
  );
  assert.deepEqual(Object.keys(matcher), ["makeRe", "scan", "braces"]);
  const lock = JSON.parse(
    readFileSync(join(project, "package-lock.json"), "utf8"),
  );
  for (const [path, member] of Object.entries(lock.packages)) {
    assert.ok(!/(^|\/)node_modules\/braces$/.test(path), path);
    if (/(^|\/)node_modules\/micromatch$/.test(path))
      assert.equal(member.link, true);
  }
});

test("literal, wildcard, brace, extglob and missing roots retain exact directory discovery", () =>
  fixture((root) => {
    const discover = (suffix) =>
      glob.globSync(`${root}/${suffix}`, { onlyDirectories: true }).sort();
    const one = join(root, "apps/one");
    const two = join(root, "apps/two");
    assert.deepEqual(discover("apps/one"), [one]);
    assert.deepEqual(discover("apps/one/"), [`${one}/`]);
    assert.deepEqual(discover("apps/*"), [one, two]);
    assert.deepEqual(discover("apps/{one,two}"), [one, two]);
    assert.deepEqual(discover("apps/@(one|two)"), [one, two]);
    assert.deepEqual(discover("apps/no-match*"), []);
    assert.deepEqual(discover("apps/file.txt"), []);
  }));

test("actual Next root discovery preserves string, array, backslash and default settings", () =>
  fixture((root) => {
    const context = (rootDir) => ({
      cwd: root,
      settings: { next: { rootDir } },
    });
    assert.deepEqual(getRootDirs({ cwd: root, settings: {} }), [root]);
    assert.deepEqual(getRootDirs(context(`${root}/apps/one`)), [
      join(root, "apps/one"),
    ]);
    assert.deepEqual(
      getRootDirs(context([`${root}/apps/one`, `${root}/apps/two`, 17])).sort(),
      [join(root, "apps/one"), join(root, "apps/two")],
    );
    assert.deepEqual(
      getRootDirs(context(`${root}/apps/one`.replaceAll("/", "\\"))),
      [join(root, "apps/one")],
    );
  }));

test("unsupported matcher calls fail explicitly", () => {
  assert.throws(() => matcher.makeRe(null), TypeError);
  assert.throws(() => matcher.scan([]), TypeError);
  for (const options of [
    undefined,
    {},
    { expand: false, nodupes: true },
    { expand: true, nodupes: true, ignore: "*" },
  ]) {
    assert.throws(() => matcher.braces("{a,b}", options), TypeError);
  }
});

test("relative roots retain their leading dot and do not expand into descendants", () => {
  const relative = require("node:path").relative(
    process.cwd(),
    join(project, "apps/web"),
  );
  assert.deepEqual(glob.globSync(relative, { onlyDirectories: true }), [
    relative,
  ]);
  assert.deepEqual(glob.globSync(`./${relative}`, { onlyDirectories: true }), [
    `./${relative}`,
  ]);
});

test("symlink, recursive and negated roots retain the original directory discovery", () =>
  fixture((root) => {
    const one = join(root, "apps/one");
    const two = join(root, "apps/two");
    const link = join(root, "apps/link");
    symlinkSync(one, link);
    const discover = (suffix) =>
      glob.globSync(`${root}/${suffix}`, { onlyDirectories: true }).sort();
    assert.deepEqual(discover("apps/link"), [link]);
    assert.deepEqual(discover("apps/*"), [link, one, two]);
    assert.deepEqual(discover("apps/!(two)"), [
      join(root, "apps/.hidden"),
      link,
      one,
    ]);
    const descendants = [
      link,
      join(link, "pages"),
      one,
      join(one, "pages"),
      two,
      join(two, "src"),
      join(two, "src/app"),
      join(two, "src/app/account"),
    ].sort();
    assert.deepEqual(discover("apps/**"), descendants);
    assert.deepEqual(discover("apps/**/*"), descendants);
  }));

test("expansion limits fail explicitly and never return a truncated root set", () => {
  assert.throws(
    () => matcher.braces("{1..1001}", { expand: true, nodupes: true }),
    /result limit/,
  );
  assert.throws(
    () => matcher.braces("{a,b}".repeat(11), { expand: true, nodupes: true }),
    /result limit/,
  );
  assert.equal(
    matcher.braces("{1..1000}", { expand: true, nodupes: true }).length,
    1000,
  );
  const escaped = matcher.braces(`${"\\,".repeat(1024)}{1..1000}`, {
    expand: true,
    nodupes: true,
  });
  assert.equal(escaped.length, 1000);
  assert.equal(escaped[999], `${",".repeat(1024)}1000`);
  assert.throws(() => matcher.makeRe("a".repeat(4097)), /length limit/);
  assert.throws(
    () =>
      matcher.braces(`{a}${"}".repeat(1000)},z}`, {
        expand: true,
        nodupes: true,
      }),
    /rewrite budget/,
  );
});

test("deeply nested brace patterns do not cause the original stack-exhaustion failure", () =>
  fixture((root) => {
    const pattern = `${root}/apps/${"{".repeat(1000)}missing${"}".repeat(1000)}`;
    assert.throws(
      () => glob.globSync(pattern, { onlyDirectories: true }),
      /brace nesting exceeds the reviewed limit/,
    );
  }));

test("the complete effective ESLint rule configuration stays unchanged", async () => {
  const eslint = new ESLint({ cwd: join(project, "apps/web") });
  const config = await eslint.calculateConfigForFile(
    join(project, "apps/web/src/app/page.tsx"),
  );
  const rules = Object.fromEntries(
    Object.entries(config.rules).sort(([a], [b]) => a.localeCompare(b)),
  );
  assert.equal(Object.keys(rules).length, 113);
  assert.equal(
    createHash("sha256").update(JSON.stringify(rules)).digest("hex"),
    "e809ea1c5cccec205e74738d64d3f93ea3e7577838c1f5664d6a4305cf1500b5",
  );
});

test("real Next lint still rejects internal anchors for roots discovered through globs", async () => {
  // ESLint runs while the temporary pages/app trees still exist.
  const root = mkdtempSync(join(tmpdir(), "novalton-next-lint-"));
  try {
    mkdirSync(join(root, "apps/one/pages"), { recursive: true });
    mkdirSync(join(root, "apps/two/src/app/account"), { recursive: true });
    mkdirSync(join(root, "apps/two/src/pages"), { recursive: true });
    writeFileSync(
      join(root, "apps/one/pages/fixture-one.tsx"),
      "export default function Page() { return null; }",
    );
    writeFileSync(
      join(root, "apps/two/src/app/account/page.tsx"),
      "export default function Page() { return null; }",
    );
    writeFileSync(
      join(root, "apps/two/src/pages/fixture-two.tsx"),
      "export default function Page() { return null; }",
    );
    const eslint = new ESLint({
      cwd: join(project, "apps/web"),
      overrideConfig: {
        settings: { next: { rootDir: `${root}/apps/{one,two}` } },
      },
    });
    const [result] = await eslint.lintText(
      'export default function Probe() { return <><a href="/fixture-one">One</a><a href="/fixture-two">Two</a><img src="/image.png" alt="Image" /></>; }',
      { filePath: "src/app/lint-probe.tsx" },
    );
    const messages = result.messages.filter(
      (item) => item.ruleId === "@next/next/no-html-link-for-pages",
    );
    assert.equal(messages.length, 2);
    assert.ok(messages.every((item) => item.severity === 2));
    assert.ok(
      result.messages.some(
        (item) => item.ruleId === "@next/next/no-img-element",
      ),
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
