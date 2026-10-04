# I-044B v2 reproducible verification foundation

This directory is the complete reviewed input for a new, reproducible
foundation.  It deliberately does **not** claim equivalence with the historical
host-only `6643fdf075190c785de92ee28e0776915297640208fd091b64045313fe16bd7c`
release. That digest is historical evidence only. A fresh installation uses
`foundation_input_sha256`
`0c4be7938e1c1d0284fccb1d2440b5e3298a5bf3ca0c9bb0f84af4db27c3863c`
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
The loader's only LSM capability permissions are SYS_ADMIN for namespace
construction, NET_ADMIN for its private loopback, and SETPCAP for dropping its
bounding set. The fixed non-setuid path needs no SETUID, SETGID or SYS_CHROOT
permission. Neither profile adds Linux capabilities to the worker. Its capability bounding
set, NoNewPrivileges, host protections and address-family limits are unchanged.
The helper also asserts that a mount operation before unshare is denied by the
kernel, even though its LSM rule permits the operation in a new user namespace.

Provisioning installs the exact reviewed policy at
`/etc/apparmor.d/novalton-verification-userns` and loads only these two profiles.
Policy bytes and helper source belong to `foundation-input.json`; the compiled
helper and dedicated loader also belong to the installed manifest. The installer
and installed verifier reject missing, changed or non-enforced policy. No sysctl,
global AppArmor mode, stock profile or systemd capability grant is changed.

The sole unit addition is a service-private bind of the host's full proc view at
`/run/novalton-verification-proc/full`. Its parent is validated root:root `0700`;
the service cannot traverse it before or after unshare. This is necessary for
Linux's `mount_too_revealing` check: inherited locked child mounts from systemd's
ProtectKernelTunables/PrivateDevices otherwise prevent mounting proc even in a
new PID namespace. The hidden anchor supplies kernel visibility, not a path or
descriptor to the worker. ProtectKernelTunables and the original masked proc
view remain in force. The helper proves anchor reads denied in both namespaces,
then mounts fresh proc for its new PID namespace and sets its own namespace's
`max_user_namespaces` to zero. `CAP_SYS_RESOURCE` is an LSM permission solely for
this namespaced limit; initial capabilities remain empty. Installed acceptance
also proves that the host namespace limit and host mount namespace are unchanged.
`tests/accept_apparmor_installed.py` removes only these profiles, proves that
execution and the installed verifier fail closed, and always reloads them before
the positive acceptance. Run it only on the disposable CI runner.

After reviewing a source change, `tools/refresh_reviewed_inputs.py` computes the
foundation, bundle and handoff pins in dependency order. It is unprivileged build
plumbing, not installed authority. Run it twice to check deterministic output;
review the complete generated diff before a validation push.

The rootfs precreates the four fixed child mount destinations `dev`, `proc`,
`source` and `scratch` before it becomes read-only. Each contains a static regular
marker, covered by both manifests, so I-044A's exact file-derived directory
closure remains strict. Child mounts hide the markers; no writable rootfs or
unexpected-directory exception is required.

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
