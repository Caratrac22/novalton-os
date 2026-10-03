"""Root-only reproducible installer for the I-044B v2 foundation.

The installer has no caller-controlled input.  Its only download is pinned in
``runtime.lock.json`` and authenticated before extraction.  All mutable build
state lives below a private temporary directory; the final release is assembled
under a trusted root-owned parent and atomically promoted only after its complete
manifest has been checked.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

SOURCE = Path(__file__).resolve().parent
TARGET = Path("/opt/novalton-verification/i044b-v2")
PARENT = TARGET.parent
STORAGE = Path("/var/lib/novalton-verification")
UNIT = Path("/etc/systemd/system/novalton-verification.service")
MOUNT_UNIT = Path("/etc/systemd/system/var-lib-novalton\\x2dverification.mount")
LOCK = SOURCE / "runtime.lock.json"
FOUNDATION_INPUT = SOURCE / "foundation-input.json"
INSTALLED_MANIFEST = "installed-manifest.json"
FOUNDATION_METADATA = "foundation-metadata.json"
COPY_FILES = (
    "foundation-input.json",
    "provision.py",
    "worker/worker.py",
    "client/i044b_client.py",
    "novalton-verification.service",
    "var-lib-novalton\\x2dverification.mount",
    "runtime.lock.json",
    "tests/accept_i044b_installed.py",
)


def checked(command: list[str], *, cwd: Path | None = None) -> None:
    subprocess.run(command, check=True, env={"PATH": "/usr/bin:/bin"}, stdin=subprocess.DEVNULL, cwd=cwd)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def no_link(path: Path) -> os.stat_result:
    info = path.lstat()
    if path.is_symlink():
        raise RuntimeError("symlink_denied")
    return info


def install_control_file(source: Path, destination: Path) -> None:
    parent = no_link(destination.parent)
    if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != 0 or parent.st_gid != 0
            or parent.st_mode & 0o022):
        raise RuntimeError("control_parent_untrusted")
    expected = source.read_bytes()
    try:
        current = no_link(destination)
    except FileNotFoundError:
        descriptor = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o644,
        )
        with os.fdopen(descriptor, "wb", closefd=True) as writer:
            writer.write(expected)
            writer.flush()
            os.fsync(writer.fileno())
    else:
        if (not stat.S_ISREG(current.st_mode) or current.st_uid != 0 or current.st_gid != 0
                or stat.S_IMODE(current.st_mode) != 0o644
                or destination.read_bytes() != expected):
            raise RuntimeError("installed_control_drift")
    final = no_link(destination)
    if (not stat.S_ISREG(final.st_mode) or final.st_uid != 0 or final.st_gid != 0
            or stat.S_IMODE(final.st_mode) != 0o644 or destination.read_bytes() != expected):
        raise RuntimeError("installed_control_mismatch")


def trusted_source() -> None:
    root = no_link(SOURCE)
    if not stat.S_ISDIR(root.st_mode):
        raise RuntimeError("source_shape")
    for relative in COPY_FILES:
        info = no_link(SOURCE / relative)
        if not stat.S_ISREG(info.st_mode):
            raise RuntimeError("source_shape")
    lock_info = no_link(LOCK)
    if lock_info.st_mode & 0o022:
        raise RuntimeError("source_writable")


def load_lock() -> dict[str, object]:
    lock = json.loads(LOCK.read_bytes())
    if (
        not isinstance(lock, dict)
        or set(lock) != {"format", "bubblewrap", "cpython"}
        or lock.get("format") != 1
        or not isinstance(lock.get("bubblewrap"), dict)
        or not isinstance(lock.get("cpython"), dict)
    ):
        raise RuntimeError("runtime_lock_shape")
    cpython = lock["cpython"]
    if (
        set(cpython) != {"url", "sha256", "version"}
        or not isinstance(cpython["url"], str)
        or not cpython["url"].startswith("https://www.python.org/ftp/python/")
        or not isinstance(cpython["sha256"], str)
        or len(cpython["sha256"]) != 64
        or not isinstance(cpython["version"], str)
    ):
        raise RuntimeError("runtime_lock_shape")
    bubblewrap = lock["bubblewrap"]
    if (
        set(bubblewrap) != {"url", "sha256", "binary_sha256", "version"}
        or bubblewrap["url"]
        != "https://security.ubuntu.com/ubuntu/pool/main/b/bubblewrap/"
        "bubblewrap_0.9.0-1ubuntu0.3_amd64.deb"
        or bubblewrap["version"] != "0.9.0-1ubuntu0.3"
        or any(
            not isinstance(bubblewrap[field], str) or len(bubblewrap[field]) != 64
            for field in ("sha256", "binary_sha256")
        )
    ):
        raise RuntimeError("runtime_lock_shape")
    return lock


def verify_foundation_input(lock: dict[str, object]) -> str:
    input_data = FOUNDATION_INPUT.read_bytes()
    identity = json.loads(input_data)
    if (
        not isinstance(identity, dict)
        or set(identity) != {
            "schema", "runtime_version", "cpython_source_sha256",
            "bubblewrap_sha256", "source",
        }
        or identity.get("schema") != "novalton.i044b.foundation-input.v1"
        or identity.get("runtime_version") != lock["cpython"]["version"]  # type: ignore[index]
        or identity.get("cpython_source_sha256") != lock["cpython"]["sha256"]  # type: ignore[index]
        or identity.get("bubblewrap_sha256")
        != lock["bubblewrap"]["binary_sha256"]  # type: ignore[index]
        or not isinstance(identity.get("source"), dict)
    ):
        raise RuntimeError("foundation_identity_shape")
    if set(identity["source"]) != {path for path in COPY_FILES if path != "foundation-input.json"}:
        raise RuntimeError("foundation_identity_shape")
    for relative, expected in identity["source"].items():
        if not isinstance(relative, str) or not isinstance(expected, str) or digest((SOURCE / relative).read_bytes()) != expected:
            raise RuntimeError("foundation_identity_content")
    return digest(input_data)


def ensure_accounts() -> None:
    try:
        import grp
        import pwd

        group = grp.getgrnam("novalton-verify-ipc")
        service = pwd.getpwnam("novalton-verify")
        client = pwd.getpwnam("novalton-verify-client")
        if service.pw_uid == 0 or client.pw_uid == 0 or service.pw_gid == 0:
            raise RuntimeError("account_privilege")
        if group.gr_gid == 0:
            raise RuntimeError("account_privilege")
        return
    except KeyError:
        pass
    checked(["/usr/sbin/groupadd", "--system", "novalton-verify-ipc"])
    checked(["/usr/sbin/useradd", "--system", "--no-create-home", "--shell", "/usr/sbin/nologin", "--user-group", "novalton-verify"])
    checked(["/usr/sbin/useradd", "--system", "--no-create-home", "--shell", "/usr/sbin/nologin", "--user-group", "--groups", "novalton-verify-ipc", "novalton-verify-client"])
    checked(["/usr/sbin/usermod", "--append", "--groups", "novalton-verify-ipc", "novalton-verify"])


def download_pinned(source: object, destination: Path) -> Path:
    assert isinstance(source, dict)
    request = urllib.request.Request(str(source["url"]), headers={"User-Agent": "Novalton-I044B/2"})
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("xb") as output:
        shutil.copyfileobj(response, output, 64 * 1024)
    if digest(destination.read_bytes()) != source["sha256"]:
        raise RuntimeError("runtime_download_digest_mismatch")
    return destination


def extract_bubblewrap(archive: Path, work: Path, expected_sha256: str) -> Path:
    destination = work / "bubblewrap-package"
    destination.mkdir(mode=0o700)
    checked(["/usr/bin/dpkg-deb", "--extract", str(archive), str(destination)])
    binary = destination / "usr/bin/bwrap"
    info = no_link(binary)
    if not stat.S_ISREG(info.st_mode) or digest(binary.read_bytes()) != expected_sha256:
        raise RuntimeError("bubblewrap_digest_mismatch")
    return binary


def extract_runtime(archive: Path, work: Path, version: str) -> Path:
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        root_name = f"Python-{version}"
        prefix = root_name + "/"
        # The archive is authenticated before this point.  Symlinks may occur
        # in CPython's signed source tree, but device entries and any path that
        # can escape the versioned prefix are still rejected before extraction.
        if not members or any(
            member.isdev() or (member.name != root_name and not member.name.startswith(prefix))
            or ".." in Path(member.name).parts or member.name.startswith("/")
            for member in members
        ):
            raise RuntimeError("runtime_archive_shape")
        bundle.extractall(work, filter="data")
    source = work / f"Python-{version}"
    if not source.is_dir() or source.is_symlink():
        raise RuntimeError("runtime_extract_shape")
    return source


def copy_dependency(path: Path, rootfs: Path) -> None:
    destination = rootfs / path.relative_to("/")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, destination, follow_symlinks=True)


def runtime_rootfs(runtime: Path, rootfs: Path) -> None:
    shutil.copytree(runtime, rootfs / "runtime", symlinks=False)
    libraries: set[Path] = set()
    candidates = [rootfs / "runtime/bin/python3.13", *sorted((rootfs / "runtime/lib/python3.13/lib-dynload").glob("*.so"))]
    for candidate in candidates:
        output = subprocess.check_output(["/usr/bin/ldd", str(candidate)], text=True, env={"PATH": "/usr/bin:/bin"})
        for line in output.splitlines():
            for token in line.replace("=>", " ").split():
                value = Path(token)
                if value.is_absolute() and value.exists() and value.is_file():
                    libraries.add(value.resolve())
    loader = Path("/lib64/ld-linux-x86-64.so.2").resolve()
    libraries.add(loader)
    for library in sorted(libraries):
        copy_dependency(library, rootfs)
    link = rootfs / "lib64/ld-linux-x86-64.so.2"
    if not link.exists():
        link.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(loader, link)


def manifest(root: Path) -> bytes:
    members: list[dict[str, object]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().encode()):
        info = no_link(path)
        relative = path.relative_to(root).as_posix()
        if relative in {INSTALLED_MANIFEST, FOUNDATION_METADATA}:
            continue
        entry: dict[str, object] = {
            "path": relative,
            "uid": info.st_uid,
            "gid": info.st_gid,
            "mode": f"{stat.S_IMODE(info.st_mode):04o}",
        }
        if stat.S_ISDIR(info.st_mode):
            entry["type"] = "directory"
        elif stat.S_ISREG(info.st_mode):
            entry["type"] = "regular"
            entry["sha256"] = digest(path.read_bytes())
        else:
            raise RuntimeError("release_shape")
        members.append(entry)
    value = {"schema": "novalton.i044b.installed-manifest.v1", "members": members}
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def harden(root: Path) -> None:
    for path in [root, *root.rglob("*")]:
        os.chown(path, 0, 0, follow_symlinks=False)
        if path.is_dir():
            path.chmod(0o555)
        else:
            path.chmod(0o555 if path.stat().st_mode & 0o111 else 0o444)


def verify_release(root: Path, expected_foundation_input: str | None = None) -> dict[str, str]:
    info = no_link(root)
    if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o555 or info.st_uid != 0 or info.st_gid != 0:
        raise RuntimeError("release_metadata")
    manifest_path = root / INSTALLED_MANIFEST
    metadata_path = root / FOUNDATION_METADATA
    for control in (manifest_path, metadata_path):
        control_info = no_link(control)
        if (not stat.S_ISREG(control_info.st_mode) or control_info.st_uid != 0
                or control_info.st_gid != 0 or stat.S_IMODE(control_info.st_mode) != 0o444):
            raise RuntimeError("release_metadata")
    manifest_data = manifest_path.read_bytes()
    installed_manifest_sha256 = digest(manifest_data)
    expected = json.loads(manifest_data)
    if (not isinstance(expected, dict)
            or set(expected) != {"schema", "members"}
            or expected.get("schema") != "novalton.i044b.installed-manifest.v1"
            or not isinstance(expected.get("members"), list)):
        raise RuntimeError("release_manifest_shape")
    actual_paths = {
        path.relative_to(root).as_posix() for path in root.rglob("*")
        if path not in {manifest_path, metadata_path}
    }
    listed: set[str] = set()
    for entry in expected["members"]:
        if not isinstance(entry, dict) or set(entry) not in (
            {"path", "type", "uid", "gid", "mode"},
            {"path", "type", "uid", "gid", "mode", "sha256"},
        ):
            raise RuntimeError("release_manifest_shape")
        relative = entry["path"]
        if (not isinstance(relative, str) or not relative or relative.startswith("/")
                or ".." in Path(relative).parts or relative in listed):
            raise RuntimeError("release_manifest_shape")
        listed.add(relative)
        path = root / relative
        path_info = no_link(path)
        actual_type = "directory" if stat.S_ISDIR(path_info.st_mode) else "regular" if stat.S_ISREG(path_info.st_mode) else "other"
        if (entry["type"] != actual_type or entry["uid"] != path_info.st_uid
                or entry["gid"] != path_info.st_gid
                or entry["mode"] != f"{stat.S_IMODE(path_info.st_mode):04o}"):
            raise RuntimeError("release_metadata")
        if actual_type == "regular":
            if set(entry) != {"path", "type", "uid", "gid", "mode", "sha256"} or digest(path.read_bytes()) != entry["sha256"]:
                raise RuntimeError("release_content")
        elif set(entry) != {"path", "type", "uid", "gid", "mode"}:
            raise RuntimeError("release_manifest_shape")
    if listed != actual_paths:
        raise RuntimeError("release_manifest_shape")
    metadata = json.loads(metadata_path.read_bytes())
    if (not isinstance(metadata, dict) or set(metadata) != {
        "schema", "foundation_input_sha256", "installed_manifest_sha256", "runtime_version"
    } or metadata.get("schema") != "novalton.i044b.foundation-metadata.v1"
        or not isinstance(metadata.get("foundation_input_sha256"), str)
        or __import__("re").fullmatch(r"[0-9a-f]{64}", metadata["foundation_input_sha256"]) is None
        or metadata.get("installed_manifest_sha256") != installed_manifest_sha256
        or metadata.get("runtime_version") != "3.13.15"
        or (expected_foundation_input is not None
            and metadata["foundation_input_sha256"] != expected_foundation_input)):
        raise RuntimeError("foundation_metadata_shape")
    return metadata


def install() -> str:
    if os.geteuid() != 0 or len(sys.argv) != 1:
        raise SystemExit("I-044B v2 installer accepts no arguments and requires root")
    trusted_source()
    lock = load_lock()
    foundation_input_sha256 = verify_foundation_input(lock)
    ensure_accounts()
    PARENT.mkdir(mode=0o755, parents=True, exist_ok=True)
    parent = no_link(PARENT)
    if parent.st_uid != 0 or parent.st_gid != 0 or parent.st_mode & 0o022:
        raise RuntimeError("target_parent_untrusted")
    with tempfile.TemporaryDirectory(prefix="novalton-i044b-build-", dir="/var/tmp") as temporary:
        work = Path(temporary)
        archive = download_pinned(lock["cpython"], work / "Python.tgz")
        bubblewrap_archive = download_pinned(lock["bubblewrap"], work / "bubblewrap.deb")
        bubblewrap_lock = lock["bubblewrap"]
        assert isinstance(bubblewrap_lock, dict)
        bubblewrap = extract_bubblewrap(
            bubblewrap_archive, work, str(bubblewrap_lock["binary_sha256"])
        )
        source = extract_runtime(archive, work, str(lock["cpython"]["version"]))  # type: ignore[index]
        prefix = work / "runtime"
        checked([str(source / "configure"), f"--prefix={prefix}", "--without-ensurepip", "--disable-test-modules"], cwd=source)
        checked(["/usr/bin/make", "-C", str(source), "-j2"])
        checked(["/usr/bin/make", "-C", str(source), "install"])
        candidate = Path(tempfile.mkdtemp(prefix=".i044b-v2-candidate-", dir=PARENT))
        try:
            for relative in COPY_FILES:
                destination = candidate / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(SOURCE / relative, destination)
            shutil.copy2(bubblewrap, candidate / "bwrap")
            runtime_rootfs(prefix, candidate / "rootfs")
            shutil.copytree(prefix, candidate / "runtime", symlinks=False)
            (candidate / "policy.json").write_text(json.dumps({"client_gid": __import__("grp").getgrnam("novalton-verify-ipc").gr_gid, "client_uid": __import__("pwd").getpwnam("novalton-verify-client").pw_uid}, sort_keys=True) + "\n")
            harden(candidate)
            manifest_data = manifest(candidate)
            (candidate / INSTALLED_MANIFEST).write_bytes(manifest_data)
            metadata = {
                "schema": "novalton.i044b.foundation-metadata.v1",
                "foundation_input_sha256": foundation_input_sha256,
                "installed_manifest_sha256": digest(manifest_data),
                "runtime_version": str(lock["cpython"]["version"]),  # type: ignore[index]
            }
            (candidate / FOUNDATION_METADATA).write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
            harden(candidate)
            evidence = verify_release(candidate, foundation_input_sha256)
            if TARGET.exists():
                if verify_release(TARGET, foundation_input_sha256) != evidence:
                    raise RuntimeError("different_foundation_already_installed")
                shutil.rmtree(candidate)
            else:
                candidate.rename(TARGET)
            STORAGE.mkdir(mode=0o700, parents=True, exist_ok=True)
            storage_info = no_link(STORAGE)
            if not stat.S_ISDIR(storage_info.st_mode) or storage_info.st_mode & 0o022:
                raise RuntimeError("storage_mountpoint_untrusted")
            install_control_file(TARGET / "novalton-verification.service", UNIT)
            install_control_file(
                TARGET / "var-lib-novalton\\x2dverification.mount", MOUNT_UNIT
            )
            checked(["/usr/bin/systemctl", "daemon-reload"])
            checked(["/usr/bin/systemctl", "enable", "--now", "var-lib-novalton\\x2dverification.mount"])
            service = __import__("pwd").getpwnam("novalton-verify")
            os.chown(STORAGE, service.pw_uid, service.pw_gid)
            STORAGE.chmod(0o700)
            checked(["/usr/bin/systemctl", "enable", "--now", "novalton-verification.service"])
            checked(["/usr/bin/systemctl", "is-active", "novalton-verification.service"])
            return evidence["installed_manifest_sha256"]
        except BaseException:
            if candidate.exists():
                shutil.rmtree(candidate)
            raise


if __name__ == "__main__":
    print(install())
