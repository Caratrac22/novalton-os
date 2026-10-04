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
a0969ea18ac2e52f8aafb21c9b02286d25f3375703e41253e1cbcc102a943eb5  foundation-input.json
cb8e96d4f1b73356058cb405d4174ec2b2b1ac6fb541919d0fa93e8ae9f3ccc5  provision.py
2307b9c0616fc63cada69199e42d83f8f851a9e4fbf0beae7091f280280a4213  worker/worker.py
6dc64477906b4d2c5a626c3aa940a1f9490630fe1c6daf8b9cf4b3ed923a504e  worker/userns-helper.c
888ebcef4e20116457fcbf2cdf967bd92fc12865d7c87f38513a3043e8548b19  novalton-userns.apparmor
439773325ea683d8e98c0143174b2950df88955e049060aed6c3a081310a5fdc  client/i044b_client.py
069690d522aec58683b64e7597a851ee0a5694bd7cfdfb4a978aebdfd3cd5a98  novalton-verification.service
24b1d592f2b21cef4dd319484375c4aa660135f565aae0604beca2c7c545a438  var-lib-novalton\x2dverification.mount
0e43622f895e34b29f933743a508698bc7e38fb4d2519bbe38e6d8c8255235c9  runtime.lock.json
a03ab1ea9be9baff66a27c6d8466baf9743e5256a3c3bb6984bbfce18ebbf68e  tests/accept_i044b_installed.py
c1063c0de593264440480b9067596b98e65262c6521dd8151a2393fb5b0a4c90  tests/accept_apparmor_installed.py
EOF
exec /usr/bin/python3 -I -S -B "$stage/provision.py"
