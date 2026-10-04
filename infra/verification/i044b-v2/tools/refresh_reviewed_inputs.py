"""Unprivileged deterministic closure generator; never used by root installers.

Review source first, run this tool, review the complete resulting diff. Pins are
computed in dependency order; no installed/compiler-dependent digest is pinned.
"""

import ast
import hashlib
import io
import json
import re
import tarfile
from pathlib import Path

B = Path(__file__).resolve().parents[1]
A = B.parent / "i044a-v2"
REPO = B.parents[2]
WORKFLOW = REPO / ".github/workflows/i044a-validation.yml"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def values(path: Path, names: set[str]) -> dict:
    result = {}
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            name = getattr(node.targets[0], "id", None)
            if name in names:
                result[name] = ast.literal_eval(node.value)
    assert set(result) == names
    return result


def json_bytes(value: dict) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def constant(path: Path, name: str, value: str) -> None:
    text, count = re.subn(
        rf'(?m)^({name} = ")[0-9a-f]{{64}}("$)',
        rf'\g<1>{value}\g<2>', path.read_text(),
    )
    assert count == 1
    path.write_text(text)


def main() -> None:
    pins = {
        B / "foundation-input.json": digest((B / "foundation-input.json").read_bytes()),
        A / "bundle-manifest.json": digest((A / "bundle-manifest.json").read_bytes()),
        A / "bundle.tar": digest((A / "bundle.tar").read_bytes()),
        A / "install.py": digest((A / "install.py").read_bytes()),
        A / "root-handoff.sh": digest((A / "root-handoff.sh").read_bytes()),
        B / "root-handoff.sh": digest((B / "root-handoff.sh").read_bytes()),
    }
    copies = values(B / "provision.py", {"COPY_FILES"})["COPY_FILES"]
    lock = json.loads((B / "runtime.lock.json").read_bytes())
    identity = {
        "schema": "novalton.i044b.foundation-input.v1",
        "runtime_version": lock["cpython"]["version"],
        "cpython_source_sha256": lock["cpython"]["sha256"],
        "bubblewrap_sha256": lock["bubblewrap"]["binary_sha256"],
        "source": {name: digest((B / name).read_bytes()) for name in copies if name != "foundation-input.json"},
    }
    (B / "foundation-input.json").write_bytes(json_bytes(identity))
    foundation = digest((B / "foundation-input.json").read_bytes())
    for path in (A / "install.py", A / "client/i044a_client.py"):
        constant(path, "FOUNDATION_INPUT_SHA256", foundation)
    script = (B / "root-handoff.sh").read_text()
    begin = script.index("/usr/bin/sha256sum -c <<'EOF'\n") + len("/usr/bin/sha256sum -c <<'EOF'\n")
    end = script.index("\nEOF", begin)
    closure = "\n".join(f"{digest((B / name).read_bytes())}  {name}" for name in copies)
    (B / "root-handoff.sh").write_text(script[:begin] + closure + script[end:])
    files = values(A / "install.py", {"FILES", "AUXILIARY"})
    members = files["FILES"] | files["AUXILIARY"]
    (A / "bundle-manifest.json").write_bytes(json_bytes({destination: digest((A / source).read_bytes()) for destination, source in members.items()}))
    # Preserve the reviewed archive's order; sorted additions are deterministic.
    with tarfile.open(A / "bundle.tar") as previous:
        order = [entry.name for entry in previous.getmembers()]
    expected = {"bundle-manifest.json", *members.values()}
    order = [name for name in order if name in expected] + sorted(expected - set(order))
    with tarfile.open(A / "bundle.tar", "w", format=tarfile.USTAR_FORMAT) as bundle:
        for name in order:
            data = (A / name).read_bytes()
            entry = tarfile.TarInfo(name)
            entry.size, entry.mode, entry.mtime = len(data), 0o644, 1789282800
            bundle.addfile(entry, io.BytesIO(data))
    constant(A / "install.py", "EXPECTED_BUNDLE_DIGEST", digest((A / "bundle.tar").read_bytes()))
    constant(A / "install.py", "EXPECTED_BUNDLE_MANIFEST_DIGEST", digest((A / "bundle-manifest.json").read_bytes()))
    for name, target in (("installer_sha256", A / "install.py"), ("bundle_sha256", A / "bundle.tar")):
        handoff, count = re.subn(rf"(?m)^{name}=[0-9a-f]{{64}}$", f"{name}={digest(target.read_bytes())}", (A / "root-handoff.sh").read_text())
        assert count == 1
        (A / "root-handoff.sh").write_text(handoff)
    # Only documentation and CI consume the externally reviewed handoff pins.
    for path in (B / "README.md", A / "README.md", WORKFLOW):
        text = path.read_text()
        for target, old in pins.items():
            text = text.replace(old, digest(target.read_bytes()))
        for relative in ("infra/verification/i044a-v2/install.py", "infra/verification/i044a-v2/bundle.tar", "infra/verification/i044a-v2/root-handoff.sh"):
            text = re.sub(rf"(?m)^[0-9a-f]{{64}}  {re.escape(relative)}$", f"{digest((REPO / relative).read_bytes())}  {relative}", text)
        text = re.sub(r"(?m)^(immutable installer SHA-256: )[0-9a-f]{64}$", rf"\g<1>{digest((A / 'install.py').read_bytes())}", text)
        for generation in ("i044a", "i044b"):
            text = re.sub(rf"(?m)^(\s*)[0-9a-f]{{64}}  /run/novalton-{generation}-v2-reviewed/root-handoff.sh$", rf"\g<1>{digest((B.parent / (generation + '-v2') / 'root-handoff.sh').read_bytes())}  /run/novalton-{generation}-v2-reviewed/root-handoff.sh", text)
        path.write_text(text)
    adapter = REPO / "apps/api/src/novalton_api/infrastructure/verification_sandbox.py"
    text = adapter.read_text()
    for name, identity in (("_FOUNDATION_INPUT_SHA256", foundation), ("_I044A_INPUT_SHA256", digest((A / "bundle-manifest.json").read_bytes()))):
        text, count = re.subn(rf'(?m)^({name}: Final = ")[0-9a-f]{{64}}("$)', rf'\g<1>{identity}\g<2>', text)
        assert count == 1
    adapter.write_text(text)
    print(json.dumps({"foundation_input_sha256": foundation, "i044a_input_sha256": digest((A / "bundle-manifest.json").read_bytes())}, sort_keys=True))


if __name__ == "__main__":
    main()
