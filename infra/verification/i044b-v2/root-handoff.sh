#!/bin/sh
# Root-owned stage only; hashes below are the reviewed source closure.
set -efu

stage=/run/novalton-i044b-v2-reviewed
source=/run/novalton-i044b-v2-input
test "$(/usr/bin/id -u)" = 0
test "$(/usr/bin/stat -c '%u:%g:%a' "$stage/root-handoff.sh")" = 0:0:400
/usr/bin/install -d -o root -g root -m 0500 "$stage/worker" "$stage/client" "$stage/tests"
for relative in provision.py foundation-input.json runtime.lock.json \
    novalton-verification.service worker/worker.py worker/userns-helper.c \
    novalton-userns.apparmor client/i044b_client.py \
    'var-lib-novalton\x2dverification.mount' tests/accept_i044b_installed.py \
    tests/accept_apparmor_installed.py; do
    test ! -L "$source/$relative"
    test -f "$source/$relative"
    /usr/bin/install -o root -g root -m 0400 "$source/$relative" "$stage/$relative"
done
cd "$stage"
/usr/bin/sha256sum -c <<'EOF'
ed5fc88315005d2928340d9ecb4a4bb168a31405040941cacfd2e2ac30516297  foundation-input.json
6f7ac7c00e57dae33a939334a8fa6033e3935698939ee80095e36cf32bb6d654  provision.py
49d6d4f9d29c1d671568d79c4226d1ddd1da3dd6cd73488449a6807a210c5ffd  worker/worker.py
3bac81bc367bac46817faa87a73bbc52e2f428ba7d37183914133a77fbfea254  worker/userns-helper.c
04b5f7b4a880f3fb2bb16c2efc60b8ccfe242363ec5af1f9b1f0686928ca85f6  novalton-userns.apparmor
439773325ea683d8e98c0143174b2950df88955e049060aed6c3a081310a5fdc  client/i044b_client.py
3e1c6243f805b1f792154d57d7fd40bf953a232630262695bc414a75fee857df  novalton-verification.service
24b1d592f2b21cef4dd319484375c4aa660135f565aae0604beca2c7c545a438  var-lib-novalton\x2dverification.mount
0e43622f895e34b29f933743a508698bc7e38fb4d2519bbe38e6d8c8255235c9  runtime.lock.json
79ce8a096aa3590b7613cb8b88fd160fe57beeb9f9a0c6bc28cbf963839ba4fa  tests/accept_i044b_installed.py
3d149471078fcc490df41c3aef82c74807e8e84b35a4dc2e7c41bb228407c14f  tests/accept_apparmor_installed.py
EOF
exec /usr/bin/python3 -I -S -B "$stage/provision.py"
