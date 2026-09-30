"""Root-only offline installer for one independently pinned I-044A bundle."""

import hashlib
import io
import json
import os
import re
import shutil
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

SOURCE = Path("/run/novalton-i044a-v2-reviewed")
BASE = Path("/opt/novalton-verification/i044b-v1")
TARGET = Path("/opt/novalton-verification/i044a-v2")
UNIT = Path("/etc/systemd/system/novalton-verification.service")
FOUNDATION_DIGEST = "6643fdf075190c785de92ee28e0776915297640208fd091b64045313fe16bd7c"
EXPECTED_BUNDLE_DIGEST = "f804c28ff27cbff40e6a9ae8448633262c61421e87c5e9dd1444aed1e30fd137"
EXPECTED_BUNDLE_MANIFEST_DIGEST = "2eeecda08e4d7b2ba34657112ff7825bbc02c9312660810f282d7af6dc536e31"
EXPECTED_RELEASE_DIGEST = "935319e8d43272f8e325832c3bc9e382499a6b0f40abb71eedb9410217f273a8"
ALLOWED_PREDECESSOR_RELEASE_DIGEST = "71fa6df9100246b5b37a541e808936f87b05b9084b2446200648b256f867fdd2"
FILES = {
    "client/i044a_client.py": "client/i044a_client.py",
    "novalton-verification.service": "novalton-verification.service",
    "rootfs/runtime/i044a_probe.py": "worker/adversarial_probe.py",
    "worker/i044a.py": "worker/i044a.py",
    "worker/i044a_launch.py": "worker/i044a_launch.py",
}
AUXILIARY = {
    "tests/accept_i044a_installed.py": "tests/accept_i044a_installed.py",
    "tests/test_i044a_contract.py": "tests/test_i044a_contract.py",
    "tests/fixtures/i044b_worker_contract_shim.py": "tests/fixtures/i044b_worker_contract_shim.py",
    "tests/test_i044a_seccomp_kernel.py": "tests/test_i044a_seccomp_kernel.py",
    "tests/test_i044a_seccomp_staging.py": "tests/test_i044a_seccomp_staging.py",
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def checked(command: list[str]) -> None:
    subprocess.run(command, check=True, env={}, stdin=subprocess.DEVNULL)


def seccomp_policy() -> bytes:
    """x86_64 cBPF: filter clone namespace flags and deny clone3 entirely."""
    denied = [
        41, 42, 43, 49, 50, 53, 101, 103, 155, 159, 163, 164, 165, 166,
        167, 168, 169, 170, 171, 172, 173, 174, 175, 176, 177, 178, 179,
        180, 212, 227, 246, 248, 249, 250, 272, 298, 300, 303, 304, 308,
        310, 311, 312, 313, 317, 321, 323, 425, 426, 427, 428, 429, 430,
        431, 432, 433, 435, 442,
    ]
    instructions = [
        (0x20, 0, 0, 4),
        (0x15, 1, 0, 0xC000003E),
        (0x06, 0, 0, 0x80000000),
        (0x20, 0, 0, 0),
        (0x15, 0, 3, 56),
        (0x20, 0, 0, 16),
        (0x45, 0, 1, 0x7E020080),
        (0x06, 0, 0, 0x00050001),
        (0x20, 0, 0, 0),
    ]
    for number in denied:
        instructions.extend(((0x15, 0, 1, number), (0x06, 0, 0, 0x00050001)))
    instructions.append((0x06, 0, 0, 0x7FFF0000))
    return b"".join(struct.pack("HBBI", *instruction) for instruction in instructions)


def verify_foundation(*, ownership: bool = True) -> dict[str, str]:
    manifest_data = (BASE / "manifest.json").read_bytes()
    if digest(manifest_data) != FOUNDATION_DIGEST:
        raise RuntimeError("foundation_manifest_mismatch")
    manifest = json.loads(manifest_data)
    actual_files = {
        path.relative_to(BASE).as_posix()
        for path in BASE.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    if actual_files != set(manifest):
        raise RuntimeError("foundation_shape_invalid")
    for path in [BASE, *BASE.rglob("*")]:
        info = path.lstat()
        if path.is_symlink() or (ownership and (info.st_uid != 0 or info.st_mode & 0o022)):
            raise RuntimeError("foundation_trust_failed")
    for relative, expected in manifest.items():
        if digest((BASE / relative).read_bytes()) != expected:
            raise RuntimeError("foundation_content_mismatch")
    return manifest


def verify_staged_installer() -> None:
    if Path(__file__).resolve() != SOURCE / "install.py":
        raise RuntimeError("installer_not_trusted_stage")
    for path in (SOURCE, SOURCE / "install.py", SOURCE / "bundle.tar"):
        info = path.lstat()
        if path.is_symlink() or info.st_uid != 0 or info.st_mode & 0o022:
            raise RuntimeError("installer_stage_untrusted")


def load_bundle(archive_path: Path = SOURCE / "bundle.tar") -> dict[str, bytes]:
    archive_data = archive_path.read_bytes()
    if digest(archive_data) != EXPECTED_BUNDLE_DIGEST:
        raise RuntimeError("bundle_digest_mismatch")
    with tarfile.open(fileobj=io.BytesIO(archive_data), mode="r:") as archive:
        members = archive.getmembers()
        expected_names = {"bundle-manifest.json", *FILES.values(), *AUXILIARY.values()}
        if {member.name for member in members} != expected_names or any(
            not member.isfile() or member.name.startswith("/") or ".." in Path(member.name).parts
            for member in members
        ):
            raise RuntimeError("bundle_shape_invalid")
        contents = {
            member.name: archive.extractfile(member).read()  # type: ignore[union-attr]
            for member in members
        }
    manifest_data = contents.pop("bundle-manifest.json")
    if digest(manifest_data) != EXPECTED_BUNDLE_MANIFEST_DIGEST:
        raise RuntimeError("bundle_manifest_mismatch")
    manifest = json.loads(manifest_data)
    bundle_files = FILES | AUXILIARY
    if set(manifest) != set(bundle_files):
        raise RuntimeError("bundle_manifest_shape_invalid")
    loaded = {}
    for destination, member_name in bundle_files.items():
        data = contents[member_name]
        if digest(data) != manifest[destination]:
            raise RuntimeError("bundle_content_mismatch")
        if destination in FILES:
            loaded[destination] = data
    return loaded


def make_manifest_from_hashes(hashes: dict[str, str]) -> bytes:
    return (json.dumps(hashes, indent=2, sort_keys=True) + "\n").encode()


def expected_release_manifest(
    foundation_manifest: dict[str, str], loaded: dict[str, bytes]
) -> bytes:
    hashes = dict(foundation_manifest)
    hashes.update({relative: digest(data) for relative, data in loaded.items()})
    hashes["seccomp.bpf"] = digest(seccomp_policy())
    return make_manifest_from_hashes(hashes)


def enforce_release_digest(release_manifest: bytes) -> None:
    if digest(release_manifest) != EXPECTED_RELEASE_DIGEST:
        raise RuntimeError("release_digest_mismatch")


def exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def verify_release(
    release: Path, expected_digest: str, *, ownership: bool = True
) -> None:
    info = release.lstat()
    if (
        release.is_symlink()
        or not stat.S_ISDIR(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o555
        or (ownership and (info.st_uid != 0 or info.st_gid != 0))
    ):
        raise RuntimeError("release_metadata_mismatch")
    manifest_path = release / "manifest.json"
    manifest_info = manifest_path.lstat()
    if (
        manifest_path.is_symlink()
        or not stat.S_ISREG(manifest_info.st_mode)
        or stat.S_IMODE(manifest_info.st_mode) != 0o444
        or (ownership and (manifest_info.st_uid != 0 or manifest_info.st_gid != 0))
    ):
        raise RuntimeError("release_manifest_metadata_mismatch")
    manifest_data = manifest_path.read_bytes()
    if digest(manifest_data) != expected_digest:
        raise RuntimeError("release_digest_mismatch")
    manifest = json.loads(manifest_data)
    if (
        not isinstance(manifest, dict)
        or not all(
            isinstance(relative, str)
            and isinstance(value, str)
            and re.fullmatch(r"[0-9a-f]{64}", value) is not None
            for relative, value in manifest.items()
        )
    ):
        raise RuntimeError("release_manifest_shape_invalid")
    actual_files = set()
    for path in [release, *release.rglob("*")]:
        current = path.lstat()
        if path.is_symlink() or (ownership and (current.st_uid != 0 or current.st_gid != 0)):
            raise RuntimeError("release_trust_failed")
        mode = stat.S_IMODE(current.st_mode)
        if stat.S_ISDIR(current.st_mode):
            if mode != 0o555:
                raise RuntimeError("release_metadata_mismatch")
        elif stat.S_ISREG(current.st_mode):
            if path == manifest_path:
                continue
            if mode not in {0o444, 0o555}:
                raise RuntimeError("release_metadata_mismatch")
            actual_files.add(path.relative_to(release).as_posix())
        else:
            raise RuntimeError("release_shape_invalid")
    if actual_files != set(manifest):
        raise RuntimeError("release_shape_invalid")
    for relative, expected in manifest.items():
        if digest((release / relative).read_bytes()) != expected:
            raise RuntimeError("release_content_mismatch")


def verify_target_parent() -> None:
    info = TARGET.parent.lstat()
    if (
        TARGET.parent.is_symlink()
        or not stat.S_ISDIR(info.st_mode)
        or info.st_uid != 0
        or info.st_gid != 0
        or info.st_mode & 0o022
    ):
        raise RuntimeError("target_parent_untrusted")


def reserve_sibling(prefix: str) -> Path:
    sibling = Path(tempfile.mkdtemp(prefix=prefix, dir=TARGET.parent))
    sibling.rmdir()
    return sibling


def move_sibling(source: Path, destination: Path) -> None:
    """Atomically rename only installer-selected siblings on one trusted parent."""
    source.rename(destination)


def materialize_candidate(loaded: dict[str, bytes], release_manifest: bytes) -> Path:
    temporary = Path(tempfile.mkdtemp(prefix=".i044a-v2-candidate-", dir=TARGET.parent))
    try:
        shutil.copytree(BASE, temporary, dirs_exist_ok=True, symlinks=False)
        for relative, data in loaded.items():
            destination = temporary / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        (temporary / "seccomp.bpf").write_bytes(seccomp_policy())
        (temporary / "manifest.json").write_bytes(release_manifest)
        for path in [temporary, *temporary.rglob("*")]:
            os.chown(path, 0, 0, follow_symlinks=False)
            path.chmod(0o555 if path.is_dir() or path.stat().st_mode & 0o111 else 0o444)
        verify_release(temporary, EXPECTED_RELEASE_DIGEST)
        return temporary
    except Exception:
        shutil.rmtree(temporary)
        raise


def trusted_unit(expected: bytes) -> bytes:
    info = UNIT.lstat()
    if (
        UNIT.is_symlink()
        or not stat.S_ISREG(info.st_mode)
        or info.st_uid != 0
        or info.st_gid != 0
        or stat.S_IMODE(info.st_mode) != 0o644
    ):
        raise RuntimeError("unit_metadata_mismatch")
    data = UNIT.read_bytes()
    if data != expected:
        raise RuntimeError("installed_unit_drift")
    return data


def verify_unit_bytes(expected: bytes) -> None:
    info = UNIT.lstat()
    if (
        UNIT.is_symlink()
        or not stat.S_ISREG(info.st_mode)
        or info.st_uid != 0
        or info.st_gid != 0
        or stat.S_IMODE(info.st_mode) != 0o644
        or UNIT.read_bytes() != expected
    ):
        raise RuntimeError("unit_restore_mismatch")


def target_state() -> str:
    if not exists(TARGET):
        return "absent"
    try:
        verify_release(TARGET, EXPECTED_RELEASE_DIGEST)
    except RuntimeError as candidate_error:
        try:
            verify_release(TARGET, ALLOWED_PREDECESSOR_RELEASE_DIGEST)
        except RuntimeError:
            raise RuntimeError("target_release_untrusted") from candidate_error
        return "predecessor"
    return "candidate"


def restore_unit_and_service(previous_unit: bytes) -> None:
    UNIT.write_bytes(previous_unit)
    UNIT.chmod(0o644)
    verify_unit_bytes(previous_unit)
    checked(["/usr/bin/systemctl", "daemon-reload"])
    checked(["/usr/bin/systemctl", "start", "novalton-verification.service"])
    checked(["/usr/bin/systemctl", "is-active", "novalton-verification.service"])


def recover_unchanged_predecessor(previous_unit: bytes) -> None:
    """Recover a predecessor after a stop attempt without release mutation."""
    try:
        verify_release(TARGET, ALLOWED_PREDECESSOR_RELEASE_DIGEST)
        verify_unit_bytes(previous_unit)
        checked(["/usr/bin/systemctl", "start", "novalton-verification.service"])
        checked(["/usr/bin/systemctl", "is-active", "novalton-verification.service"])
        verify_release(TARGET, ALLOWED_PREDECESSOR_RELEASE_DIGEST)
        verify_unit_bytes(previous_unit)
    except Exception as rollback_error:
        raise RuntimeError("service_rollback_failed") from rollback_error


def restore_predecessor(previous_unit: bytes, backup: Path) -> None:
    try:
        # Never quarantine TARGET unless the independently revalidated backup
        # proves that an exact predecessor is available for restoration.
        verify_release(backup, ALLOWED_PREDECESSOR_RELEASE_DIGEST)
        checked(["/usr/bin/systemctl", "stop", "novalton-verification.service"])
        if exists(TARGET):
            failed = reserve_sibling(".i044a-v2-failed-")
            move_sibling(TARGET, failed)
        move_sibling(backup, TARGET)
        restore_unit_and_service(previous_unit)
        verify_release(TARGET, ALLOWED_PREDECESSOR_RELEASE_DIGEST)
        verify_unit_bytes(previous_unit)
    except Exception as rollback_error:
        raise RuntimeError("service_rollback_failed") from rollback_error


def main() -> int:
    if os.geteuid() != 0 or len(sys.argv) != 1:
        raise SystemExit("run the reviewed immutable /run installer as root with no arguments")
    verify_staged_installer()
    verify_target_parent()
    foundation_manifest = verify_foundation()
    loaded = load_bundle()
    release_manifest = expected_release_manifest(foundation_manifest, loaded)
    enforce_release_digest(release_manifest)
    candidate_unit = loaded["novalton-verification.service"]
    state = target_state()
    if state == "candidate":
        previous_unit = trusted_unit(candidate_unit)
    elif state == "predecessor":
        previous_unit = trusted_unit(
            (TARGET / "novalton-verification.service").read_bytes()
        )
    else:
        previous_unit = trusted_unit(
            (BASE / "novalton-verification.service").read_bytes()
        )
    if state == "candidate":
        checked(["/usr/bin/systemctl", "is-active", "novalton-verification.service"])
        verify_release(TARGET, EXPECTED_RELEASE_DIGEST)
        print(EXPECTED_RELEASE_DIGEST)
        return 0

    temporary = materialize_candidate(loaded, release_manifest)

    backup = None
    stop_attempted = False
    predecessor_moved = False
    candidate_promoted = False
    try:
        stop_attempted = True
        checked(["/usr/bin/systemctl", "stop", "novalton-verification.service"])
        if state == "predecessor":
            reserved_backup = reserve_sibling(".i044a-v2-predecessor-")
            move_sibling(TARGET, reserved_backup)
            backup = reserved_backup
            predecessor_moved = True
        move_sibling(temporary, TARGET)
        candidate_promoted = True
        UNIT.write_bytes(candidate_unit)
        UNIT.chmod(0o644)
        verify_unit_bytes(candidate_unit)
        checked(["/usr/bin/systemctl", "daemon-reload"])
        checked(["/usr/bin/systemctl", "start", "novalton-verification.service"])
        checked(["/usr/bin/systemctl", "is-active", "novalton-verification.service"])
        verify_release(TARGET, EXPECTED_RELEASE_DIGEST)
        print(EXPECTED_RELEASE_DIGEST)
        return 0
    except Exception as error:
        if predecessor_moved:
            if backup is None:
                raise RuntimeError("service_rollback_failed") from error
            restore_predecessor(previous_unit, backup)
        elif stop_attempted and state == "predecessor":
            recover_unchanged_predecessor(previous_unit)
        raise RuntimeError("upgrade_failed") from error
    finally:
        if not candidate_promoted and temporary.exists():
            shutil.rmtree(temporary)


if __name__ == "__main__":
    raise SystemExit(main())
