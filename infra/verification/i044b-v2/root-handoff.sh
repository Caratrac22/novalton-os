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
9d84b28f44f3cc19587b30382e737ced3c1df8fb91722177306335ca223249d0  foundation-input.json
6f7ac7c00e57dae33a939334a8fa6033e3935698939ee80095e36cf32bb6d654  provision.py
8275dde74dec2c5e4472242e4f58f1692f702fbc087cb23cf087060bd3b30ac9  worker/worker.py
1a470f9e66711b2a57b35cfa52c421665736c806e0fa0706d2e02930c14e054e  worker/userns-helper.c
d336672706f3037fe936eac82608af61b010271da685c840f94c5b12b27032f0  novalton-userns.apparmor
439773325ea683d8e98c0143174b2950df88955e049060aed6c3a081310a5fdc  client/i044b_client.py
3e1c6243f805b1f792154d57d7fd40bf953a232630262695bc414a75fee857df  novalton-verification.service
24b1d592f2b21cef4dd319484375c4aa660135f565aae0604beca2c7c545a438  var-lib-novalton\x2dverification.mount
0e43622f895e34b29f933743a508698bc7e38fb4d2519bbe38e6d8c8255235c9  runtime.lock.json
79ce8a096aa3590b7613cb8b88fd160fe57beeb9f9a0c6bc28cbf963839ba4fa  tests/accept_i044b_installed.py
3d149471078fcc490df41c3aef82c74807e8e84b35a4dc2e7c41bb228407c14f  tests/accept_apparmor_installed.py
EOF
exec /usr/bin/python3 -I -S -B "$stage/provision.py"
