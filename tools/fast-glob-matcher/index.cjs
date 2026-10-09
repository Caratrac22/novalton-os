"use strict";

const picomatch = require("picomatch");
const { expand } = require("brace-expansion");

// The three matcher calls used by fast-glob 3.3.1, not a full micromatch API.
function checkedPattern(pattern) {
  if (typeof pattern !== "string")
    throw new TypeError("Expected a glob string");
  if (pattern.length > 4096)
    throw new TypeError("Glob pattern exceeds the reviewed length limit");
  // Bound recursive expansion before calling the maintained expansion library.
  let depth = 0;
  let closingBraces = 0;
  for (let i = 0; i < pattern.length; i++) {
    if (pattern[i] === "\\") {
      i++;
      continue;
    }
    if (pattern[i] === "{" && ++depth > 64) {
      throw new TypeError("Glob brace nesting exceeds the reviewed limit");
    }
    if (pattern[i] === "}") {
      if (++closingBraces >= 1000) {
        throw new TypeError("Glob pattern exceeds the reviewed rewrite budget");
      }
      depth = Math.max(0, depth - 1);
    }
  }
  return pattern;
}

exports.makeRe = (pattern, options) =>
  picomatch.makeRe(checkedPattern(pattern), options);
exports.scan = (pattern, options) =>
  picomatch.scan(checkedPattern(pattern), options);
exports.braces = (pattern, options) => {
  if (
    !options ||
    typeof options !== "object" ||
    !Object.hasOwn(options, "expand") ||
    !Object.hasOwn(options, "nodupes") ||
    options.expand !== true ||
    options.nodupes !== true ||
    Object.keys(options).length !== 2
  ) {
    throw new TypeError("Unsupported fast-glob brace expansion contract");
  }
  // Ask for one more than the accepted bound, then reject overflow. Returning
  // a library-truncated expansion would silently omit roots from linting.
  const expanded = expand(checkedPattern(pattern), {
    max: 1001,
    // The pinned library temporarily encodes escaped characters in tokens
    // shorter than 64 bytes. Budget those too, so its cap cannot truncate a
    // valid <=4096-character expansion before the result-count sentinel.
    maxLength: 4096 * 1001 * 64,
  });
  if (expanded.length > 1000)
    throw new TypeError("Glob expansion exceeds the reviewed result limit");
  return [...new Set(expanded)];
};
