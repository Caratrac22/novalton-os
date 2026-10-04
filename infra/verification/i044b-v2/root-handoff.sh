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
aec46813d4f940b49fb30c64d43d738e9eca5c25330db02f06a4c4e75e25d367  foundation-input.json
f8d19c9cbcc14604062391bc68cac5247e9633244adb27a8399d821c4f481a16  provision.py
a60b68df56299c4cb6d1a913d7653e7ca4f623637d00faace9bdc5bc99b7ca3e  worker/worker.py
e89f08ade9dbd1422a99de0527f3ce7c8ae0a75b789e585f6dfefd94448e021c  worker/userns-helper.c
c941eed4705d9d14fefcedbe766ffaba1380f144982405b089cf57926534892a  novalton-userns.apparmor
439773325ea683d8e98c0143174b2950df88955e049060aed6c3a081310a5fdc  client/i044b_client.py
069690d522aec58683b64e7597a851ee0a5694bd7cfdfb4a978aebdfd3cd5a98  novalton-verification.service
24b1d592f2b21cef4dd319484375c4aa660135f565aae0604beca2c7c545a438  var-lib-novalton\x2dverification.mount
0e43622f895e34b29f933743a508698bc7e38fb4d2519bbe38e6d8c8255235c9  runtime.lock.json
c59f897134a7c21b34c8fabff396affda6e1d90ff9b0aa18e8cafaba72eb3e1b  tests/accept_i044b_installed.py
1632130f0557107d5f1950b8fe78f491e138434a25b7e70b75043091c797674a  tests/accept_apparmor_installed.py
EOF
exec /usr/bin/python3 -I -S -B "$stage/provision.py"
