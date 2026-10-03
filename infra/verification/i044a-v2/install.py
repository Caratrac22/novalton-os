"""Root-only offline installer for one independently pinned I-044A bundle."""

import hashlib
import importlib.util
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
BASE = Path("/opt/novalton-verification/i044b-v2")
TARGET = Path("/opt/novalton-verification/i044a-v2")
UNIT = Path("/etc/systemd/system/novalton-verification.service")
FOUNDATION_INPUT_SHA256 = "ca6d193c19291ab61e5233e55d51bd099e04356387db146646ce4615e213ae06"
EXPECTED_BUNDLE_DIGEST = "bb9e8620dad57a5e44c3aeae3e6135c6474886f73e552bb20498c6344725fea8"
EXPECTED_BUNDLE_MANIFEST_DIGEST = "dd58c58a2ba3763bb87a425635fec8036549470246af98aae208c72d94b13b85"
I044A_INPUT_SHA256 = EXPECTED_BUNDLE_MANIFEST_DIGEST
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


def verify_foundation(*, ownership: bool = True) -> tuple[dict[str, str], dict[str, str]]:
    identity_data = (BASE / "foundation-input.json").read_bytes()
    if digest(identity_data) != FOUNDATION_INPUT_SHA256:
        raise RuntimeError("foundation_identity_mismatch")
    identity = json.loads(identity_data)
    if (not isinstance(identity, dict) or set(identity) != {
        "schema", "runtime_version", "cpython_source_sha256", "bubblewrap_sha256", "source"
    } or identity.get("schema") != "novalton.i044b.foundation-input.v1"
        or not isinstance(identity.get("source"), dict)
        or identity["source"].get("provision.py") != digest((BASE / "provision.py").read_bytes())):
        raise RuntimeError("foundation_identity_shape")
    spec = importlib.util.spec_from_file_location("i044b_installed_verifier", BASE / "provision.py")
    verifier = importlib.util.module_from_spec(spec)
    if spec.loader is None:
        raise RuntimeError("foundation_verifier_unavailable")
    spec.loader.exec_module(verifier)
    metadata = verifier.verify_release(
        BASE, FOUNDATION_INPUT_SHA256 if ownership else None
    )
    if metadata.get("foundation_input_sha256") != FOUNDATION_INPUT_SHA256:
        raise RuntimeError("foundation_identity_mismatch")
    files = {
        path.relative_to(BASE).as_posix(): digest(path.read_bytes())
        for path in BASE.rglob("*") if path.is_file()
    }
    return files, metadata


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


def release_metadata(release_manifest: bytes, foundation_metadata: dict[str, str]) -> bytes:
    value = {
        "schema": "novalton.i044a.release-metadata.v1",
        "i044a_input_sha256": I044A_INPUT_SHA256,
        "foundation_input_sha256": FOUNDATION_INPUT_SHA256,
        "foundation_installed_manifest_sha256": foundation_metadata["installed_manifest_sha256"],
        "installed_manifest_sha256": digest(release_manifest),
    }
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def verify_release(
    release: Path, expected_digest: str | None = None, *, ownership: bool = True
) -> dict[str, str]:
    info = release.lstat()
    if (
        release.is_symlink()
        or not stat.S_ISDIR(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o555
        or (ownership and (info.st_uid != 0 or info.st_gid != 0))
    ):
        raise RuntimeError("release_metadata_mismatch")
    manifest_path = release / "manifest.json"
    metadata_path = release / "release-metadata.json"
    manifest_info = manifest_path.lstat()
    if (
        manifest_path.is_symlink()
        or not stat.S_ISREG(manifest_info.st_mode)
        or stat.S_IMODE(manifest_info.st_mode) != 0o444
        or (ownership and (manifest_info.st_uid != 0 or manifest_info.st_gid != 0))
    ):
        raise RuntimeError("release_manifest_metadata_mismatch")
    manifest_data = manifest_path.read_bytes()
    installed_manifest_sha256 = digest(manifest_data)
    if expected_digest is not None and installed_manifest_sha256 != expected_digest:
        raise RuntimeError("installed_manifest_mismatch")
    if (not exists(metadata_path) and expected_digest == ALLOWED_PREDECESSOR_RELEASE_DIGEST):
        return verify_predecessor_release(release, manifest_data, ownership=ownership)
    metadata_info = metadata_path.lstat()
    if (metadata_path.is_symlink() or not stat.S_ISREG(metadata_info.st_mode)
            or stat.S_IMODE(metadata_info.st_mode) != 0o444
            or (ownership and (metadata_info.st_uid != 0 or metadata_info.st_gid != 0))):
        raise RuntimeError("release_metadata_mismatch")
    metadata = json.loads(metadata_path.read_bytes())
    if (not isinstance(metadata, dict) or set(metadata) != {
        "schema", "i044a_input_sha256", "foundation_input_sha256",
        "foundation_installed_manifest_sha256", "installed_manifest_sha256",
    } or metadata.get("schema") != "novalton.i044a.release-metadata.v1"
        or metadata.get("i044a_input_sha256") != I044A_INPUT_SHA256
        or metadata.get("foundation_input_sha256") != FOUNDATION_INPUT_SHA256
        or not isinstance(metadata.get("foundation_installed_manifest_sha256"), str)
        or len(metadata["foundation_installed_manifest_sha256"]) != 64
        or metadata.get("installed_manifest_sha256") != installed_manifest_sha256):
        raise RuntimeError("release_metadata_mismatch")
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
    actual_directories = set()
    for path in [release, *release.rglob("*")]:
        current = path.lstat()
        if path.is_symlink() or (ownership and (current.st_uid != 0 or current.st_gid != 0)):
            raise RuntimeError("release_trust_failed")
        mode = stat.S_IMODE(current.st_mode)
        if stat.S_ISDIR(current.st_mode):
            if mode != 0o555:
                raise RuntimeError("release_metadata_mismatch")
            if path != release:
                actual_directories.add(path.relative_to(release).as_posix())
        elif stat.S_ISREG(current.st_mode):
            if path in {manifest_path, metadata_path}:
                continue
            if mode not in {0o444, 0o555}:
                raise RuntimeError("release_metadata_mismatch")
            actual_files.add(path.relative_to(release).as_posix())
        else:
            raise RuntimeError("release_shape_invalid")
    expected_directories = {
        parent.as_posix()
        for relative in manifest
        for parent in Path(relative).parents
        if parent.as_posix() != "."
    }
    if actual_files != set(manifest) or actual_directories != expected_directories:
        raise RuntimeError("release_shape_invalid")
    for relative, expected in manifest.items():
        if digest((release / relative).read_bytes()) != expected:
            raise RuntimeError("release_content_mismatch")
    foundation_copy = json.loads((release / "foundation-metadata.json").read_bytes())
    if (not isinstance(foundation_copy, dict)
            or foundation_copy.get("foundation_input_sha256") != metadata["foundation_input_sha256"]
            or foundation_copy.get("installed_manifest_sha256") != metadata["foundation_installed_manifest_sha256"]):
        raise RuntimeError("release_metadata_mismatch")
    return metadata


def verify_predecessor_release(
    release: Path, manifest_data: bytes, *, ownership: bool = True
) -> dict[str, str]:
    """Verify the one exact pre-migration release solely for atomic rollback."""
    manifest = json.loads(manifest_data)
    if not isinstance(manifest, dict):
        raise RuntimeError("release_manifest_shape_invalid")
    actual_files: set[str] = set()
    actual_directories: set[str] = set()
    for path in [release, *release.rglob("*")]:
        current = path.lstat()
        if path.is_symlink() or (ownership and (current.st_uid != 0 or current.st_gid != 0)):
            raise RuntimeError("release_trust_failed")
        if path.is_dir() and path != release:
            actual_directories.add(path.relative_to(release).as_posix())
        if path.is_file() and path.name != "manifest.json":
            actual_files.add(path.relative_to(release).as_posix())
    expected_directories = {
        parent.as_posix()
        for relative in manifest
        for parent in Path(relative).parents
        if parent.as_posix() != "."
    }
    if actual_files != set(manifest) or actual_directories != expected_directories:
        raise RuntimeError("release_shape_invalid")
    for relative, expected in manifest.items():
        if not isinstance(relative, str) or not isinstance(expected, str) or digest((release / relative).read_bytes()) != expected:
            raise RuntimeError("release_content_mismatch")
    return {"installed_manifest_sha256": ALLOWED_PREDECESSOR_RELEASE_DIGEST}


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


def materialize_candidate(
    loaded: dict[str, bytes], release_manifest: bytes, foundation_metadata: dict[str, str]
) -> Path:
    temporary = Path(tempfile.mkdtemp(prefix=".i044a-v2-candidate-", dir=TARGET.parent))
    try:
        shutil.copytree(BASE, temporary, dirs_exist_ok=True, symlinks=False)
        for relative, data in loaded.items():
            destination = temporary / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        (temporary / "seccomp.bpf").write_bytes(seccomp_policy())
        (temporary / "manifest.json").write_bytes(release_manifest)
        (temporary / "release-metadata.json").write_bytes(
            release_metadata(release_manifest, foundation_metadata)
        )
        for path in [temporary, *temporary.rglob("*")]:
            os.chown(path, 0, 0, follow_symlinks=False)
            path.chmod(0o555 if path.is_dir() or path.stat().st_mode & 0o111 else 0o444)
        verify_release(temporary, digest(release_manifest))
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
        verify_release(TARGET)
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
    foundation_manifest, foundation_metadata = verify_foundation()
    loaded = load_bundle()
    release_manifest = expected_release_manifest(foundation_manifest, loaded)
    installed_manifest_sha256 = digest(release_manifest)
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
        evidence = verify_release(TARGET, installed_manifest_sha256)
        print(evidence["installed_manifest_sha256"])
        return 0

    temporary = materialize_candidate(loaded, release_manifest, foundation_metadata)

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
        evidence = verify_release(TARGET, installed_manifest_sha256)
        print(evidence["installed_manifest_sha256"])
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
