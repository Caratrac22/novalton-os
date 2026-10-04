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
0fbdcd09ba415769899a546a166e2a9e642acf115ac50268a03bb0cf1424756c  foundation-input.json
f8d19c9cbcc14604062391bc68cac5247e9633244adb27a8399d821c4f481a16  provision.py
9a17aae1cbab4135efa4f48c2e21d6e9ef7387a21c3a4a4338356a514e8401a2  worker/worker.py
6dc64477906b4d2c5a626c3aa940a1f9490630fe1c6daf8b9cf4b3ed923a504e  worker/userns-helper.c
e9db782b67eab87b11a378e343e68e9a6f3d4bdd550a6072b4a2f4a37a171a90  novalton-userns.apparmor
439773325ea683d8e98c0143174b2950df88955e049060aed6c3a081310a5fdc  client/i044b_client.py
069690d522aec58683b64e7597a851ee0a5694bd7cfdfb4a978aebdfd3cd5a98  novalton-verification.service
24b1d592f2b21cef4dd319484375c4aa660135f565aae0604beca2c7c545a438  var-lib-novalton\x2dverification.mount
0e43622f895e34b29f933743a508698bc7e38fb4d2519bbe38e6d8c8255235c9  runtime.lock.json
dbbe039067b4d058e6573f0f3ee2791dcbd3ebb59b425d38466cadd8a3c1b14e  tests/accept_i044b_installed.py
1632130f0557107d5f1950b8fe78f491e138434a25b7e70b75043091c797674a  tests/accept_apparmor_installed.py
EOF
exec /usr/bin/python3 -I -S -B "$stage/provision.py"
