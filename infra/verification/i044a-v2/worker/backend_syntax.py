"""Fixed DB-free Python syntax verification; never import or execute source code."""

import json
import os
import re
import stat
import warnings
from pathlib import Path

SOURCE = Path("/source")
ROOTS = (SOURCE / "apps/api/src", SOURCE / "apps/api/tests")
MAX_FILES = 4096
MAX_BYTES = 2 * 1024 * 1024
MAX_DIAGNOSTICS = 4
SAFE_PATH = re.compile(r"[A-Za-z0-9_./-]{1,200}\Z")


def verify() -> dict[str, object]:
    """Return bounded metadata, never source lines or interpreter exception text."""
    checked = 0
    failed = 0
    diagnostics = []
    for root in ROOTS:
        if root.is_symlink() or not root.is_dir():
            return {"state": "failed", "failure_code": "verification_source_missing"}
        for directory, names, files in os.walk(root, followlinks=False):
            names.sort()
            for name in names:
                if (Path(directory) / name).is_symlink():
                    return {
                        "state": "failed",
                        "failure_code": "verification_source_type",
                    }
            for name in sorted(files):
                if not name.endswith(".py"):
                    continue
                path = Path(directory) / name
                info = path.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
                    return {
                        "state": "failed",
                        "failure_code": "verification_source_type",
                    }
                checked += 1
                if checked > MAX_FILES:
                    return {
                        "state": "failed",
                        "failure_code": "verification_source_bound",
                    }
                descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
                with os.fdopen(descriptor, "rb") as reader:
                    source = reader.read(MAX_BYTES + 1)
                if len(source) > MAX_BYTES:
                    return {
                        "state": "failed",
                        "failure_code": "verification_source_bound",
                    }
                try:
                    # compile creates a code object but never evaluates it. The
                    # filename is constant so exception internals cannot leak paths.
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        compile(
                            source, "verification-source", "exec", dont_inherit=True
                        )
                except (SyntaxError, ValueError):
                    failed += 1
                    if len(diagnostics) < MAX_DIAGNOSTICS:
                        relative = path.relative_to(SOURCE).as_posix()
                        diagnostics.append(
                            {
                                "path": relative
                                if SAFE_PATH.fullmatch(relative)
                                else "redacted-path",
                                "code": "python_syntax_invalid",
                            }
                        )
    if checked == 0:
        return {"state": "failed", "failure_code": "verification_source_empty"}
    return {
        "state": "passed" if failed == 0 else "failed",
        "checked_files": checked,
        "failed_files": failed,
        "diagnostics": diagnostics,
        "truncated": failed > len(diagnostics),
    }


if __name__ == "__main__":
    try:
        result = verify()
    except (OSError, MemoryError, RecursionError):
        result = {"state": "failed", "failure_code": "verification_unavailable"}
    print(json.dumps(result, sort_keys=True, separators=(",", ":")), flush=True)
    raise SystemExit(0 if result["state"] == "passed" else 1)
