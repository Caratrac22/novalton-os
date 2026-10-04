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
f8dd991d21f02481755d3c3bf325dacad80ef0f01defaab5a76a7ea7e8078fa5  foundation-input.json
9ba0c90bed43356928f960d0caa06aaebfd5667feaf46d769cbc43ead3d255d3  provision.py
9a17aae1cbab4135efa4f48c2e21d6e9ef7387a21c3a4a4338356a514e8401a2  worker/worker.py
6dc64477906b4d2c5a626c3aa940a1f9490630fe1c6daf8b9cf4b3ed923a504e  worker/userns-helper.c
6c23d9654a8c3a72059f6379cabe13f5d839802b675beea1f8f5d73c5074d55f  novalton-userns.apparmor
439773325ea683d8e98c0143174b2950df88955e049060aed6c3a081310a5fdc  client/i044b_client.py
069690d522aec58683b64e7597a851ee0a5694bd7cfdfb4a978aebdfd3cd5a98  novalton-verification.service
24b1d592f2b21cef4dd319484375c4aa660135f565aae0604beca2c7c545a438  var-lib-novalton\x2dverification.mount
0e43622f895e34b29f933743a508698bc7e38fb4d2519bbe38e6d8c8255235c9  runtime.lock.json
852195ae169fd6726365dd2954b66f500d4915f73abddcf28a71d0f7b27e37f1  tests/accept_i044b_installed.py
1632130f0557107d5f1950b8fe78f491e138434a25b7e70b75043091c797674a  tests/accept_apparmor_installed.py
EOF
exec /usr/bin/python3 -I -S -B "$stage/provision.py"
