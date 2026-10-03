# I-044B v2 reproducible verification foundation

This directory is the complete reviewed input for a new, reproducible
foundation.  It deliberately does **not** claim equivalence with the historical
host-only `6643fdf075190c785de92ee28e0776915297640208fd091b64045313fe16bd7c`
release. That digest is historical evidence only. A fresh installation uses
`foundation_input_sha256`
`e687edcdf0e1bd8ea8fe1f1fb5111a3956fbe086bdd4baaf48835454455d38e5`
and generates a separate `installed_manifest_sha256` for its concrete bytes.

`provision.py` accepts no arguments, runs only as root, downloads the exact
CPython source and Ubuntu bubblewrap package named in `runtime.lock.json`, and
checks both package SHA-256 values before unpacking. The extracted bubblewrap
binary has a second, independent SHA-256 pin. The provisioner builds CPython
outside the checkout and materializes a root-owned immutable
release below `/opt/novalton-verification/i044b-v2`. The CPython source inputs
are reproducible; compiler-dependent installed bytes are not claimed to be
byte-reproducible. `installed-manifest.json` binds paths, types, ownership,
modes, and file digests. `foundation-metadata.json` binds that manifest to the
reviewed foundation input generation. It accepts no caller path,
command, environment, mount, network, or cgroup configuration.

The foundation service exposes no execution operation. An authenticated client
receives only `i044a_overlay_required`; other peer credentials are rejected.
The release-owned installed acceptance verifies the full closure, service
hardening, peer authentication, and absence of generic execution authority.
