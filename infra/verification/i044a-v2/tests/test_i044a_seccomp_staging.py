"""Non-installed staging proof for the deterministically generated I-044A policy."""

import hashlib
import importlib.util
import json
from pathlib import Path

ARTIFACTS = Path(__file__).resolve().parent.parent


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


installer = load("i044a_staging_installer", ARTIFACTS / "install.py")
kernel = load("i044a_staging_kernel", ARTIFACTS / "tests/test_i044a_seccomp_kernel.py")


class I044AStagingSeccompKernelTests(kernel.unittest.TestCase):
    def test_generated_policy_same_process_clone3_attribution(self):
        self.assertEqual(
            kernel.platform.machine(), "x86_64", "I-044A policy requires x86_64"
        )
        policy = installer.seccomp_policy()
        mode_before, filters_before = kernel.proc_status()
        state_before = kernel.stable_process_state()

        ordinary_arguments = kernel.CloneArgs(
            flags=0, exit_signal=kernel.signal.SIGCHLD
        )
        argument_identity = bytes(ordinary_arguments)
        pre_filter_errno = kernel.clone3_once(ordinary_arguments)
        self.assertEqual(
            pre_filter_errno,
            0,
            f"ordinary clone3 must succeed before I-044A installation; errno={pre_filter_errno}",
        )
        self.assertEqual(bytes(ordinary_arguments), argument_identity)

        setns_before = kernel.setns_invalid_fd_errno()
        self.assertEqual(setns_before, kernel.errno.EBADF)
        kernel.load_exact_policy(policy)
        setns_after = kernel.setns_invalid_fd_errno()
        self.assertEqual(setns_after, kernel.errno.EPERM)
        mode_after, filters_after = kernel.proc_status()
        self.assertEqual(mode_after, 2)
        self.assertEqual(filters_after, filters_before + 1)
        self.assertEqual(kernel.stable_process_state(), state_before)

        self.assertEqual(bytes(ordinary_arguments), argument_identity)
        post_filter_errno = kernel.clone3_once(ordinary_arguments)
        self.assertEqual(post_filter_errno, kernel.errno.EPERM)
        self.assertEqual(bytes(ordinary_arguments), argument_identity)

        self.assertEqual(kernel.clone_once(0), 0)
        self.assertEqual(kernel.fork_once(), 0)
        self.assertEqual(kernel.clone_once(kernel.CLONE_NEWUSER), kernel.errno.EPERM)
        self.assertEqual(kernel.clone_once(kernel.CLONE_NEWNS), kernel.errno.EPERM)
        self.assertEqual(kernel.clone_once(kernel.CLONE_NEWNET), kernel.errno.EPERM)
        for flag in (kernel.CLONE_NEWUSER, kernel.CLONE_NEWNS, kernel.CLONE_NEWNET):
            with self.subTest(flag=flag):
                arguments = kernel.CloneArgs(
                    flags=flag, exit_signal=kernel.signal.SIGCHLD
                )
                self.assertEqual(kernel.clone3_once(arguments), kernel.errno.EPERM)

        print(
            json.dumps(
                {
                    "argument_bytes_sha256": hashlib.sha256(
                        argument_identity
                    ).hexdigest(),
                    "clone3_post_filter_errno": post_filter_errno,
                    "clone3_pre_filter_errno": pre_filter_errno,
                    "setns_pre_filter_errno": setns_before,
                    "setns_post_filter_errno": setns_after,
                    "filters_after": filters_after,
                    "filters_before": filters_before,
                    "mode_after": mode_after,
                    "mode_before": mode_before,
                    "policy_sha256": hashlib.sha256(policy).hexdigest(),
                    "stable_process_state_sha256": hashlib.sha256(
                        json.dumps(state_before, sort_keys=True).encode()
                    ).hexdigest(),
                    "test_mode": "staging_generated_policy_not_installed_acceptance",
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    kernel.unittest.main()
