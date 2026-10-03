#!/bin/sh
# Root-owned stage only; hashes below are the reviewed source closure.
set -efu

stage=/run/novalton-i044b-v2-reviewed
source=/run/novalton-i044b-v2-input
test "$(/usr/bin/id -u)" = 0
test "$(/usr/bin/stat -c '%u:%g:%a' "$stage/root-handoff.sh")" = 0:0:400
/usr/bin/install -d -o root -g root -m 0500 "$stage/worker" "$stage/client" "$stage/tests"
for relative in provision.py foundation-input.json runtime.lock.json \
    novalton-verification.service worker/worker.py client/i044b_client.py \
    'var-lib-novalton\x2dverification.mount' tests/accept_i044b_installed.py; do
    test ! -L "$source/$relative"
    test -f "$source/$relative"
    /usr/bin/install -o root -g root -m 0400 "$source/$relative" "$stage/$relative"
done
cd "$stage"
/usr/bin/sha256sum -c <<'EOF'
b5de20dc86b829c8e17cf1ddb2b8061fe174aaf7cbe64e2a3d10dc3fb5d1460e  provision.py
ca6d193c19291ab61e5233e55d51bd099e04356387db146646ce4615e213ae06  foundation-input.json
0e43622f895e34b29f933743a508698bc7e38fb4d2519bbe38e6d8c8255235c9  runtime.lock.json
3e1c6243f805b1f792154d57d7fd40bf953a232630262695bc414a75fee857df  novalton-verification.service
9c270bd9e774a91e92ed091f9ff90663ca63e69fe79e8dc5b48738e43d5373ca  worker/worker.py
439773325ea683d8e98c0143174b2950df88955e049060aed6c3a081310a5fdc  client/i044b_client.py
24b1d592f2b21cef4dd319484375c4aa660135f565aae0604beca2c7c545a438  var-lib-novalton\x2dverification.mount
db8c8ccb40d817cad7a16cd094321c22c282ac7fe1649bf08a0b0cdbc6701e45  tests/accept_i044b_installed.py
EOF
exec /usr/bin/python3 -I -S -B "$stage/provision.py"
