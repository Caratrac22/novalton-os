# Matcher adapter for Next's fast-glob dependency

This private development package replaces only `micromatch` beneath
`fast-glob@3.3.1`, used by `@next/eslint-plugin-next@16.3.8`. It is not part of
the application runtime or the I-044A/I-044B foundation.

Micromatch reaches `braces@3.0.3`, affected by
[GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm), with no
published patched release. This replacement removes that implementation. The
original fast-glob filesystem walker remains unchanged, including directory
symlinks, recursive roots and relative-path semantics. A tinyglobby replacement
was rejected because it could omit symlink roots.

The reviewed fast-glob helper calls only `makeRe`, `scan` and
`braces(pattern, { expand: true, nodupes: true })`. The first two delegate to
the maintained, pinned `picomatch@4.0.7` primitive. Expansion uses
`brace-expansion@5.0.12`, deduplicates results, and rejects unsupported options.
Inputs are bounded to 4096 characters, 64 nested braces and 1000 expansions.
At least 1000 unescaped closing braces are rejected before the library's rewrite
limit can cause a partial expansion. Its default recursion and rewrite caps
remain enabled.
Overflow raises an explicit error. Expansion asks for 1001 results so reaching
the bound cannot silently truncate the roots linted; its aggregate character
budget accommodates all 1001 results at the maximum input length, including
the pinned library's temporary escape tokens (less than 64 bytes per character).

The root package declares the local dependency under the import name
`micromatch`, with a version-scoped npm override for fast-glob. The installed
package identifies itself as `@novalton/fast-glob-matcher`. It is a narrow
adapter, not a full micromatch replacement or a renamed copy of vulnerable code.
No integrity hashes are substituted and no advisory is suppressed. Npm records
the local package and the registry integrities of its external dependencies.

Run `npm ci`, then `npm run test:lint`. Generic CI runs this guard before lint.
Tests pin the actual caller versions and source hashes, reject vulnerable
dependency reintroduction, check literal/glob/symlink/recursive root discovery,
exercise nesting and expansion bounds, preserve the complete effective ESLint
rule configuration, and prove real lint failures across multiple roots.
Disposable fixtures are removed in `finally` blocks. During implementation,
18 root-pattern cases were compared against the original fast-glob/micromatch
dependency graph and matched exactly.

No Next, React, accessibility or TypeScript rule is disabled. Upgrading the
caller requires reviewing its matcher API again before updating the scoped
override or pinned test evidence. Remove this adapter when a maintained upstream
dependency graph passes the audit and the same regressions.
