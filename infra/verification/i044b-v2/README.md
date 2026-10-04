# I-044B v2 reproducible verification foundation

This directory is the complete reviewed input for a new, reproducible
foundation.  It deliberately does **not** claim equivalence with the historical
host-only `6643fdf075190c785de92ee28e0776915297640208fd091b64045313fe16bd7c`
release. That digest is historical evidence only. A fresh installation uses
`foundation_input_sha256`
`9d84b28f44f3cc19587b30382e737ced3c1df8fb91722177306335ca223249d0`
and generates a separate `installed_manifest_sha256` for its concrete bytes.

Ubuntu's restricted user namespaces are handled by two confined, explicit
AppArmor profiles. The static `userns-helper` admits only an authenticated
inherited socket and a 32-hex run identifier, rejects root/initial capabilities,
requires NoNewPrivileges, and moves itself into that run's bounded cgroup before
unshare. It maps only its own UID/GID, mounts a private proc in new mount/PID
namespaces and sets only its new user namespace's nesting limit. It never accepts
a command, environment or filesystem path. The profile requires enforcement.
The second profile attaches to the immutable `bwrap-loader`, permits only the
fixed bubblewrap construction paths and inherits into the seccomp-filtered probe.
Neither profile adds Linux capabilities to the worker; its unit is unchanged.
The helper also asserts that a mount operation before unshare is denied by the
kernel, even though its LSM rule permits the operation in a new user namespace.

Provisioning installs the exact reviewed policy at
`/etc/apparmor.d/novalton-verification-userns` and loads only these two profiles.
Policy bytes and helper source belong to `foundation-input.json`; the compiled
helper and dedicated loader also belong to the installed manifest. The installer
and installed verifier reject missing, changed or non-enforced policy. No sysctl,
global AppArmor mode, stock profile or systemd capability grant is changed.
`tests/accept_apparmor_installed.py` removes only these profiles, proves that
execution and the installed verifier fail closed, and always reloads them before
the positive acceptance. Run it only on the disposable CI runner.

After reviewing a source change, `tools/refresh_reviewed_inputs.py` computes the
foundation, bundle and handoff pins in dependency order. It is unprivileged build
plumbing, not installed authority. Run it twice to check deterministic output;
review the complete generated diff before a validation push.

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
