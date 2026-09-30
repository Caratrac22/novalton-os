#!/bin/sh
set -efu

source=/home/alexandre/projects/novalton-os/infra/verification/i044a-v2
stage=/run/novalton-i044a-v2-reviewed
installer_sha256=635d87c5ee108486f99be6c3fb615b79d9105d47211931fd10507738d7ab514f
bundle_sha256=f804c28ff27cbff40e6a9ae8448633262c61421e87c5e9dd1444aed1e30fd137

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
exec /opt/novalton-verification/i044b-v1/rootfs/lib64/ld-linux-x86-64.so.2 \
    --library-path /opt/novalton-verification/i044b-v1/rootfs/usr/lib/x86_64-linux-gnu \
    /opt/novalton-verification/i044b-v1/rootfs/runtime/bin/python3.13 \
    -I -S -B "$stage/install.py"
