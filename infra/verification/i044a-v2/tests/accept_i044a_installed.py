"""Privileged installed acceptance for the final reviewed I-044A release."""

import hashlib
import json
import os
import pwd
import select
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Self

RELEASE = Path("/opt/novalton-verification/i044a-v2")
INSTALLED_MANIFEST_SHA256 = ""
PYTHON = str(RELEASE / "rootfs/runtime/bin/python3.13")
UNIT = "novalton-verification.service"
CLIENT = str(RELEASE / "client/i044a_client.py")
SECURITY_KEYS = frozenset(
    {
        "accepted",
        "arbitrary_fd",
        "extra_fd",
        "other_pid",
        "replay",
        "wrong_capability",
        "wrong_digest",
    }
)


def ctl(*arguments: str) -> str:
    return subprocess.check_output(["/usr/bin/systemctl", *arguments], text=True).strip()


EXCLUDED = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".next",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "coverage",
        "dist",
        "node_modules",
    }
)
MAX_FILES = 4096
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_SOURCE_BYTES = 32 * 1024 * 1024
FIXTURE_RELATIVE_PATH = PurePosixPath("workspace/untrusted_probe.py")
FIXTURE_BYTES = b'raise SystemExit("source must remain data")\n'


class TrustedFixtureWorkspace:
    """Private, root-owned test source for snapshot-mismatch regressions."""

    def __init__(self) -> None:
        parent = Path("/tmp")
        parent_info = parent.lstat()
        if (
            stat.S_ISLNK(parent_info.st_mode)
            or not stat.S_ISDIR(parent_info.st_mode)
            or parent_info.st_uid != 0
            or parent_info.st_gid != 0
            or not parent_info.st_mode & stat.S_ISVTX
            or not parent_info.st_mode & stat.S_IWOTH
        ):
            raise RuntimeError("fixture_parent_untrusted")
        self._temporary = tempfile.TemporaryDirectory(
            prefix="novalton-i044a-acceptance-", dir=str(parent)
        )
        self.path = Path(self._temporary.name)
        self.fixture_path = self.path.joinpath(*FIXTURE_RELATIVE_PATH.parts)
        try:
            self._populate()
        except BaseException:
            self.cleanup()
            raise

    def _populate(self) -> None:
        owner_uid = os.geteuid()
        owner_gid = os.getegid()
        root_info = self.path.lstat()
        if (
            stat.S_ISLNK(root_info.st_mode)
            or not stat.S_ISDIR(root_info.st_mode)
            or root_info.st_uid != owner_uid
            or root_info.st_gid != owner_gid
            or stat.S_IMODE(root_info.st_mode) != 0o700
        ):
            raise RuntimeError("fixture_root_untrusted")
        workspace = self.path / "workspace"
        workspace.mkdir(mode=0o700)
        workspace_info = workspace.lstat()
        if (
            stat.S_ISLNK(workspace_info.st_mode)
            or not stat.S_ISDIR(workspace_info.st_mode)
            or workspace_info.st_uid != owner_uid
            or workspace_info.st_gid != owner_gid
            or stat.S_IMODE(workspace_info.st_mode) != 0o700
        ):
            raise RuntimeError("fixture_directory_untrusted")
        descriptor = os.open(
            self.fixture_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
        )
        with os.fdopen(descriptor, "wb", closefd=True) as writer:
            writer.write(FIXTURE_BYTES)
        fixture_info = self.fixture_path.lstat()
        if (
            stat.S_ISLNK(fixture_info.st_mode)
            or not stat.S_ISREG(fixture_info.st_mode)
            or fixture_info.st_uid != owner_uid
            or fixture_info.st_gid != owner_gid
            or stat.S_IMODE(fixture_info.st_mode) != 0o600
        ):
            raise RuntimeError("fixture_file_untrusted")

    def replace_fixture(self, data: bytes) -> None:
        descriptor = os.open(
            self.fixture_path,
            os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        with os.fdopen(descriptor, "wb", closefd=True) as writer:
            os.ftruncate(writer.fileno(), 0)
            writer.write(data)

    def cleanup(self) -> None:
        self._temporary.cleanup()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.cleanup()


def create_host_marker() -> tuple[Path, tuple[int, int]]:
    """Create the probe marker without following or replacing any /tmp entry."""
    path = Path("/tmp/novalton-host-secret")
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
    )
    info = os.fstat(descriptor)
    identity = (info.st_dev, info.st_ino)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as writer:
            writer.write(b"I044A_FAKE_ONLY")
            os.fchmod(writer.fileno(), 0o400)
    except BaseException:
        info = path.lstat()
        if stat.S_ISREG(info.st_mode) and (info.st_dev, info.st_ino) == identity:
            path.unlink()
        raise
    return path, identity


def remove_host_marker(marker: tuple[Path, tuple[int, int]]) -> None:
    path, identity = marker
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISREG(info.st_mode) and (info.st_dev, info.st_ino) == identity:
        path.unlink()


def client(action: str, run_id: str | None = None, timeout: float = 20) -> dict:
    account = pwd.getpwnam("novalton-verify-client")
    output = subprocess.check_output(
        [
            PYTHON,
            "-I",
            "-S",
            "-B",
            CLIENT,
            INSTALLED_MANIFEST_SHA256,
            action,
            *([] if run_id is None else [run_id]),
        ],
        text=True,
        user=account.pw_uid,
        group=account.pw_gid,
        extra_groups=os.getgrouplist(account.pw_name, account.pw_gid),
        env={"GITHUB_TOKEN": "I044A_FAKE_ONLY", "OPENAI_API_KEY": "I044A_FAKE_ONLY"},
        stdin=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        timeout=timeout,
    )
    return json.loads(output)


def security_response() -> dict:
    response = client("security")
    if not isinstance(response, dict):
        raise TypeError("security_client_response_not_object")
    if "error" in response:
        error = response["error"]
        if not isinstance(error, str):
            raise TypeError("security_client_error_not_string")
        raise AssertionError("security_client_error: " + json.dumps(error, ensure_ascii=True))
    if set(response) != SECURITY_KEYS:
        raise AssertionError("security_client_response_shape")
    return response


def source_digest(root: Path) -> str:
    files = []
    entries = 0
    total = 0
    for directory, names, filenames in os.walk(root, topdown=True, followlinks=False):
        base = Path(directory)
        kept = []
        for name in sorted(names):
            relative = PurePosixPath((base / name).relative_to(root).as_posix())
            path = base / name
            if any(part in EXCLUDED or part.startswith(".env") for part in relative.parts):
                continue
            if path.is_symlink():
                raise AssertionError("source_symlink_denied")
            kept.append(name)
            entries += 1
            if entries > MAX_FILES:
                raise AssertionError("source_bound_exceeded")
        names.clear()
        names.extend(kept)
        for name in sorted(filenames):
            path = base / name
            relative = PurePosixPath(path.relative_to(root).as_posix())
            if any(part in EXCLUDED or part.startswith(".env") for part in relative.parts):
                continue
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                raise AssertionError("source_type_denied")
            entries += 1
            total += info.st_size
            if info.st_size > MAX_FILE_BYTES or entries > MAX_FILES or total > MAX_SOURCE_BYTES:
                raise AssertionError("source_bound_exceeded")
            files.append((relative, path))
    digest = hashlib.sha256()
    for relative, path in sorted(files, key=lambda item: item[0].as_posix().encode()):
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(descriptor, "rb", closefd=True) as reader:
            data = reader.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise AssertionError("source_file_too_large")
        digest.update(relative.as_posix().encode())
        digest.update(b"\0")
        digest.update(str(len(data)).encode())
        digest.update(b"\0")
        digest.update(data)
    return digest.hexdigest()


def wait_result(identity: str) -> dict:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = client("result", identity)
        if result.get("state") != "running":
            return result
        time.sleep(0.05)
    raise AssertionError("result_timeout")


def wait_ready() -> dict:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            result = client("health")
            if result.get("state") == "ready" and result.get("active") is False:
                return result
        except subprocess.SubprocessError:
            pass
        time.sleep(0.05)
    raise AssertionError("worker_not_ready")


def wait_population(service_group: Path, identity: str, minimum: int = 6) -> tuple[Path, list[str]]:
    run_group = service_group / ("run-" + identity)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            values = (run_group / "cgroup.procs").read_text().split()
            if len(values) >= minimum:
                return run_group, values
        except OSError:
            pass
        time.sleep(0.02)
    raise AssertionError("sandbox_population_not_ready")


def track_processes(values: list[str]) -> list[int]:
    tracked = []
    for value in values:
        try:
            tracked.append(os.pidfd_open(int(value)))
        except ProcessLookupError:
            pass
    return tracked


def assert_exited(tracked: list[int]) -> None:
    pending = set(tracked)
    poller = select.poll()
    for descriptor in tracked:
        poller.register(descriptor, select.POLLIN | select.POLLHUP | select.POLLERR)
    deadline = time.monotonic() + 3
    try:
        while pending and time.monotonic() < deadline:
            for descriptor, _ in poller.poll(100):
                pending.discard(descriptor)
        assert not pending, "sandbox descendant survived cleanup"
    finally:
        for descriptor in tracked:
            os.close(descriptor)


def main() -> None:
    global INSTALLED_MANIFEST_SHA256
    if os.geteuid() != 0 or len(sys.argv) != 1:
        raise SystemExit("usage: accept_i044a_installed.py (as root)")
    manifest_data = (RELEASE / "manifest.json").read_bytes()
    metadata = json.loads((RELEASE / "release-metadata.json").read_bytes())
    assert isinstance(metadata, dict) and set(metadata) == {
        "schema", "i044a_input_sha256", "foundation_input_sha256",
        "foundation_installed_manifest_sha256", "installed_manifest_sha256",
    }
    assert metadata["schema"] == "novalton.i044a.release-metadata.v1"
    INSTALLED_MANIFEST_SHA256 = hashlib.sha256(manifest_data).hexdigest()
    assert metadata["installed_manifest_sha256"] == INSTALLED_MANIFEST_SHA256
    assert ctl("is-active", UNIT) == "active"
    main_pid = ctl("show", UNIT, "-p", "MainPID", "--value")
    assert Path("/proc", main_pid, "environ").read_bytes() == b""
    status = dict(line.split(":", 1) for line in Path("/proc", main_pid, "status").read_text().splitlines())
    assert status["NoNewPrivs"].strip() == "1" and int(status["CapEff"].strip(), 16) == 0
    service_group = Path("/sys/fs/cgroup") / ctl("show", UNIT, "-p", "ControlGroup", "--value").lstrip("/")
    host_marker = create_host_marker()
    try:
        health = wait_ready()
        assert health["definition"] == "repository-probe-v1"
        assert health["installed_manifest_sha256"] == INSTALLED_MANIFEST_SHA256
        assert health["i044a_input_sha256"] == metadata["i044a_input_sha256"]
        assert health["foundation_input_sha256"] == metadata["foundation_input_sha256"]
        assert health["foundation_installed_manifest_sha256"] == metadata["foundation_installed_manifest_sha256"]
        assert health["db_mode"] is False

        security = security_response()
        assert security["arbitrary_fd"] == {"error": "invalid_request"}
        assert security["extra_fd"] == {"error": "invalid_request"}
        assert security["wrong_digest"] == {"error": "invalid_request"}
        assert security["wrong_capability"] == {"error": "invalid_capability"}
        assert security["other_pid"] == {"error": "invalid_capability"}
        assert security["accepted"]["state"] == "accepted"
        assert security["replay"] == {"error": "invalid_capability"}
        assert wait_result(security["accepted"]["run_id"])["population_empty"]

        clean = client("verify")
        assert clean["state"] == "passed"
        assert clean["population_empty"] and clean["scratch_destroyed"]
        assert clean["snapshot_destroyed"] and all(clean["checks"].values())

        first = client("start")
        identity = first["run_id"]
        second = client("start")
        assert second == {"error": "busy"}
        client("cancel", identity)
        cancelled = wait_result(identity)
        assert cancelled["state"] == "cancelled" and cancelled["population_empty"]
        assert cancelled["snapshot_destroyed"]

        start = client("start")
        identity = start["run_id"]
        run_group, values = wait_population(service_group, identity)
        assert (run_group / "cpu.max").read_text().strip() == "200000 100000"
        assert (run_group / "memory.max").read_text().strip() == "1073741824"
        assert (run_group / "memory.swap.max").read_text().strip() == "0"
        assert (run_group / "pids.max").read_text().strip() == "32"
        tracked = track_processes(values)
        ctl("kill", "--kill-whom=main", "--signal=KILL", UNIT)
        wait_ready()
        reconciled = wait_result(identity)
        assert reconciled["state"] == "reconciled" and reconciled["population_empty"]
        assert reconciled["snapshot_destroyed"]
        assert_exited(tracked)
        assert not list(service_group.glob("run-*"))
        assert not list(Path("/var/lib/novalton-verification").glob("snapshot-*"))
    finally:
        remove_host_marker(host_marker)
    logs = subprocess.check_output(["/usr/bin/journalctl", "-u", UNIT, "--since", "-3min", "--no-pager", "-o", "cat"], text=True)
    assert all(marker not in logs for marker in ("I044A_FAKE_ONLY", "GITHUB_TOKEN", "OPENAI_API_KEY"))
    print(json.dumps({"installed_acceptance": "PASS", "installed_manifest_sha256": INSTALLED_MANIFEST_SHA256, "db_mode": False}, sort_keys=True))


if __name__ == "__main__":
    main()
