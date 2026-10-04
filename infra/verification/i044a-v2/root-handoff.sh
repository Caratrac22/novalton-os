#!/bin/sh
set -efu

source=/run/novalton-i044a-v2-input
stage=/run/novalton-i044a-v2-reviewed
installer_sha256=774b9e6ae164cfc4f18aff0c61dfda647884764f864f6f62ae0a3f28a06084b5
bundle_sha256=cfdbf8f0139b97e9c9fb4c196da3348a0b540c0d8722779f42ac81e8898ebbad

test "$(/usr/bin/id -u)" = 0
test "$(/usr/bin/stat -c '%u:%g:%a' "$stage/root-handoff.sh")" = 0:0:400
/usr/bin/install -o root -g root -m 0400 "$source/install.py" "$stage/install.py"
/usr/bin/install -o root -g root -m 0400 "$source/bundle.tar" "$stage/bundle.tar"
printf '%s  %s\n' "$installer_sha256" "$stage/install.py" | /usr/bin/sha256sum -c -
printf '%s  %s\n' "$bundle_sha256" "$stage/bundle.tar" | /usr/bin/sha256sum -c -
/usr/bin/tar --extract --file "$stage/bundle.tar" --directory "$stage" \
    tests/accept_i044a_installed.py tests/test_i044a_contract.py \
    tests/fixtures/i044b_worker_contract_shim.py \
    tests/test_i044a_seccomp_kernel.py tests/test_i044a_seccomp_staging.py
/usr/bin/chown -R root:root "$stage/tests"
/usr/bin/chmod 0500 "$stage/tests"
/usr/bin/chmod 0400 "$stage/tests/accept_i044a_installed.py" \
    "$stage/tests/test_i044a_contract.py" "$stage/tests/test_i044a_seccomp_kernel.py" \
    "$stage/tests/test_i044a_seccomp_staging.py"
/usr/bin/chmod 0400 "$stage/tests/fixtures/i044b_worker_contract_shim.py"
exec /opt/novalton-verification/i044b-v2/rootfs/lib64/ld-linux-x86-64.so.2 \
    --library-path /opt/novalton-verification/i044b-v2/rootfs/usr/lib/x86_64-linux-gnu \
    /opt/novalton-verification/i044b-v2/rootfs/runtime/bin/python3.13 \
    -I -S -B "$stage/install.py"
