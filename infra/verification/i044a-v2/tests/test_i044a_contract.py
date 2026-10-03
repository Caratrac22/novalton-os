"""Provider-free authority, provenance, digest, and seccomp contract tests."""

import ast
import hashlib
import importlib.util
import io
import json
import os
import shutil
import struct
import tempfile
import threading
import time
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

artifacts = Path(__file__).resolve().parent.parent
installed = Path("/opt/novalton-verification/i044a-v2")
foundation = Path("/opt/novalton-verification/i044b-v2")
overlay = None
if installed.is_dir():
    release = installed
else:
    overlay = tempfile.TemporaryDirectory()
    release = Path(overlay.name)
    (release / "worker").mkdir()
    for name in ("i044a.py", "i044a_launch.py"):
        shutil.copyfile(artifacts / "worker" / name, release / "worker" / name)
    shutil.copyfile(
        artifacts / "tests/fixtures/i044b_worker_contract_shim.py",
        release / "worker/worker.py",
    )


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


i044a = load("i044a", release / "worker/i044a.py")
i044a_client = load("i044a_client", artifacts / "client/i044a_client.py")
i044a_acceptance = load(
    "i044a_acceptance", artifacts / "tests/accept_i044a_installed.py"
)
installer = load("i044a_installer", artifacts / "install.py")


def finalize_test_release(root: Path) -> tuple[bytes, str]:
    foundation_metadata = {
        "schema": "novalton.i044b.foundation-metadata.v1",
        "foundation_input_sha256": installer.FOUNDATION_INPUT_SHA256,
        "installed_manifest_sha256": "f" * 64,
        "runtime_version": "3.13.15",
    }
    (root / "foundation-metadata.json").write_text(
        json.dumps(foundation_metadata, sort_keys=True) + "\n"
    )
    hashes = {
        path.relative_to(root).as_posix(): installer.digest(path.read_bytes())
        for path in root.rglob("*") if path.is_file()
    }
    manifest = installer.make_manifest_from_hashes(hashes)
    (root / "manifest.json").write_bytes(manifest)
    (root / "release-metadata.json").write_bytes(
        installer.release_metadata(manifest, foundation_metadata)
    )
    for path in [root, *root.rglob("*")]:
        path.chmod(0o555 if path.is_dir() else 0o444)
    return manifest, installer.digest(manifest)


def assert_installed_acceptance_authority(
    case: unittest.TestCase, source: str
) -> None:
    """Enforce the deliberately small process-authority surface of acceptance."""
    tree = ast.parse(source)
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }

    # This is a positive inventory of every callable expression in the reviewed
    # module.  It deliberately includes ordinary helpers: an added call cannot
    # acquire authority merely because its API has not appeared on a blacklist.
    reviewed_call_targets = {
        "(RELEASE / 'manifest.json').read_bytes",
        "(RELEASE / 'release-metadata.json').read_bytes",
        '(base / name).relative_to',
        '(base / name).relative_to(root).as_posix',
        "(run_group / 'cgroup.procs').read_text",
        "(run_group / 'cgroup.procs').read_text().split",
        "(run_group / 'cpu.max').read_text",
        "(run_group / 'cpu.max').read_text().strip",
        "(run_group / 'memory.max').read_text",
        "(run_group / 'memory.max').read_text().strip",
        "(run_group / 'memory.swap.max').read_text",
        "(run_group / 'memory.swap.max').read_text().strip",
        "(run_group / 'pids.max').read_text",
        "(run_group / 'pids.max').read_text().strip",
        'AssertionError',
        'Path',
        "Path('/proc', main_pid, 'environ').read_bytes",
        "Path('/proc', main_pid, 'status').read_text",
        "Path('/proc', main_pid, 'status').read_text().splitlines",
        "Path('/var/lib/novalton-verification').glob",
        'PurePosixPath',
        'RuntimeError',
        'SystemExit',
        'TypeError',
        'all',
        'any',
        'assert_exited',
        "clean['checks'].values",
        'client',
        'create_host_marker',
        'ctl',
        "ctl('show', UNIT, '-p', 'ControlGroup', '--value').lstrip",
        'dict',
        'digest.hexdigest',
        'digest.update',
        'files.append',
        'frozenset',
        'hashlib.sha256',
        'hashlib.sha256(manifest_data).hexdigest',
        'int',
        'isinstance',
        'item[0].as_posix',
        'item[0].as_posix().encode',
        'json.dumps',
        'json.loads',
        'kept.append',
        'len',
        'line.split',
        'list',
        'main',
        'names.clear',
        'names.extend',
        'os.close',
        'os.fchmod',
        'os.fdopen',
        'os.fstat',
        'os.ftruncate',
        'os.getegid',
        'os.geteuid',
        'os.getgrouplist',
        'os.open',
        'os.pidfd_open',
        'os.walk',
        'parent.lstat',
        'part.startswith',
        'path.is_symlink',
        'path.lstat',
        'path.relative_to',
        'path.relative_to(root).as_posix',
        'path.unlink',
        'pending.discard',
        'poller.poll',
        'poller.register',
        'print',
        'pwd.getpwnam',
        'reader.read',
        'relative.as_posix',
        'relative.as_posix().encode',
        'remove_host_marker',
        'result.get',
        'security_response',
        'select.poll',
        'self._populate',
        'self._temporary.cleanup',
        'self.cleanup',
        'self.fixture_path.lstat',
        'self.path.joinpath',
        'self.path.lstat',
        'service_group.glob',
        'set',
        'sorted',
        'stat.S_IMODE',
        'stat.S_ISDIR',
        'stat.S_ISLNK',
        'stat.S_ISREG',
        "status['CapEff'].strip",
        "status['NoNewPrivs'].strip",
        'str',
        'str(len(data)).encode',
        'subprocess.check_output',
        "subprocess.check_output(['/usr/bin/systemctl', *arguments], text=True).strip",
        'tempfile.TemporaryDirectory',
        'time.monotonic',
        'time.sleep',
        'track_processes',
        'tracked.append',
        'wait_population',
        'wait_ready',
        'wait_result',
        'workspace.lstat',
        'workspace.mkdir',
        'writer.fileno',
        'writer.write',
    }
    actual_call_targets = {
        ast.unparse(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }

    expected_imports = {
        ("import", "hashlib"),
        ("import", "json"),
        ("import", "os"),
        ("import", "pwd"),
        ("import", "select"),
        ("import", "stat"),
        ("import", "subprocess"),
        ("import", "sys"),
        ("import", "time"),
        ("from", "pathlib", "Path"),
        ("from", "pathlib", "PurePosixPath"),
        ("from", "typing", "Self"),
        ("import", "tempfile"),
    }
    actual_imports = []
    for statement in ast.walk(tree):
        if isinstance(statement, ast.Import):
            case.assertIs(parents[statement], tree)
            case.assertEqual(len(statement.names), 1)
            for name in statement.names:
                case.assertIsNone(name.asname)
                actual_imports.append(("import", name.name))
        elif isinstance(statement, ast.ImportFrom):
            case.assertIs(parents[statement], tree)
            case.assertEqual(statement.level, 0)
            for name in statement.names:
                case.assertIsNone(name.asname)
                actual_imports.append(("from", statement.module, name.name))
    case.assertEqual(set(actual_imports), expected_imports)
    case.assertEqual(len(actual_imports), len(expected_imports))

    def functions_named(name: str) -> list[ast.FunctionDef]:
        return [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == name
        ]

    def assigned_values(name: str) -> list[ast.expr]:
        return [
            assignment.value
            for assignment in tree.body
            if isinstance(assignment, ast.Assign)
            and len(assignment.targets) == 1
            and isinstance(assignment.targets[0], ast.Name)
            and assignment.targets[0].id == name
        ]

    def bindings(name: str) -> list[ast.AST]:
        found = []
        for node in ast.walk(tree):
            is_binding = (
                isinstance(node, ast.Name)
                and node.id == name
                and isinstance(node.ctx, (ast.Store, ast.Del))
            ) or (
                isinstance(node, ast.arg)
                and node.arg == name
            ) or (
                isinstance(
                    node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                )
                and node.name == name
            ) or (
                isinstance(node, ast.alias)
                and node.asname == name
            ) or (
                isinstance(node, (ast.Global, ast.Nonlocal))
                and name in node.names
            ) or (
                isinstance(node, ast.ExceptHandler)
                and node.name == name
            ) or (
                isinstance(node, (ast.MatchAs, ast.MatchStar))
                and node.name == name
            )
            if is_binding:
                found.append(node)
        return found

    def containing_function(node: ast.AST) -> ast.FunctionDef | None:
        while node in parents:
            node = parents[node]
            if isinstance(node, ast.FunctionDef):
                return node
        return None

    imported_bindings = {
        entry[-1] if entry[0] == "from" else entry[1].split(".", 1)[0]
        for entry in expected_imports
    }
    for name in imported_bindings:
        case.assertEqual(bindings(name), [])

    def literal_truth(node: ast.AST) -> bool | None:
        try:
            return bool(ast.literal_eval(node))
        except (ValueError, TypeError):
            return None

    def is_trivially_dead(node: ast.AST) -> bool:
        child = node
        while child in parents:
            parent = parents[child]
            if isinstance(parent, ast.If):
                truth = literal_truth(parent.test)
                if truth is False and child in parent.body:
                    return True
                if truth is True and child in parent.orelse:
                    return True
            elif isinstance(parent, ast.IfExp):
                truth = literal_truth(parent.test)
                if truth is False and child is parent.body:
                    return True
                if truth is True and child is parent.orelse:
                    return True
            elif isinstance(parent, ast.While):
                if literal_truth(parent.test) is False and child in parent.body:
                    return True
            elif isinstance(parent, ast.BoolOp):
                position = parent.values.index(child)
                earlier = [literal_truth(value) for value in parent.values[:position]]
                if isinstance(parent.op, ast.And) and False in earlier:
                    return True
                if isinstance(parent.op, ast.Or) and True in earlier:
                    return True
            child = parent
        return False

    # CLIENT has one authoritative module binding and no shadowing or rebinding.
    client_values = assigned_values("CLIENT")
    case.assertEqual(len(client_values), 1)
    client_value = client_values[0]
    case.assertIsInstance(client_value, ast.Call)
    case.assertIsInstance(client_value.func, ast.Name)
    case.assertEqual(client_value.func.id, "str")
    case.assertEqual(len(client_value.args), 1)
    case.assertIsInstance(client_value.args[0], ast.BinOp)
    case.assertIsInstance(client_value.args[0].op, ast.Div)
    case.assertIsInstance(client_value.args[0].left, ast.Name)
    case.assertEqual(client_value.args[0].left.id, "RELEASE")
    case.assertIsInstance(client_value.args[0].right, ast.Constant)
    case.assertEqual(client_value.args[0].right.value, "client/i044a_client.py")
    client_bindings = bindings("CLIENT")
    case.assertEqual(len(client_bindings), 1)
    case.assertIsInstance(parents[client_bindings[0]], ast.Assign)
    case.assertIn(parents[client_bindings[0]], tree.body)

    # Pin PYTHON too: argv[0] must not become a caller-controlled interpreter.
    python_values = assigned_values("PYTHON")
    case.assertEqual(len(python_values), 1)
    python_value = python_values[0]
    case.assertIsInstance(python_value, ast.Call)
    case.assertIsInstance(python_value.func, ast.Name)
    case.assertEqual(python_value.func.id, "str")
    case.assertEqual(len(python_value.args), 1)
    case.assertIsInstance(python_value.args[0], ast.BinOp)
    case.assertIsInstance(python_value.args[0].left, ast.Name)
    case.assertEqual(python_value.args[0].left.id, "RELEASE")
    case.assertIsInstance(python_value.args[0].right, ast.Constant)
    case.assertEqual(python_value.args[0].right.value, "rootfs/runtime/bin/python3.13")
    case.assertEqual(len(bindings("PYTHON")), 1)
    case.assertIsInstance(parents[bindings("PYTHON")[0]], ast.Assign)

    release_values = assigned_values("RELEASE")
    case.assertEqual(len(release_values), 1)
    release_value = release_values[0]
    case.assertIsInstance(release_value, ast.Call)
    case.assertIsInstance(release_value.func, ast.Name)
    case.assertEqual(release_value.func.id, "Path")
    case.assertEqual(len(release_value.args), 1)
    case.assertIsInstance(release_value.args[0], ast.Constant)
    case.assertEqual(
        release_value.args[0].value, "/opt/novalton-verification/i044a-v2"
    )
    case.assertEqual(len(bindings("RELEASE")), 1)

    for name, expected in (("UNIT", "novalton-verification.service"),):
        values = assigned_values(name)
        case.assertEqual(len(values), 1)
        case.assertIsInstance(values[0], ast.Constant)
        case.assertEqual(values[0].value, expected)
        case.assertEqual(len(bindings(name)), 1)

    # The sole subprocess binding is the exact, unaliased module import above.
    case.assertEqual(bindings("subprocess"), [])

    forbidden_names = {
        "__builtins__",
        "__import__",
        "compile",
        "delattr",
        "eval",
        "exec",
        "getattr",
        "globals",
        "locals",
        "setattr",
        "vars",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            case.assertNotIn(node.id, forbidden_names)
        elif isinstance(node, ast.Attribute):
            case.assertNotIn(node.attr, forbidden_names)
            if isinstance(node.ctx, ast.Store):
                parent = parents[node]
                case.assertIsInstance(parent, ast.Assign)
                case.assertIn(ast.unparse(node), {"self.path", "self.fixture_path", "self._temporary"})
                owner = containing_function(node)
                case.assertIsNotNone(owner)
                case.assertEqual(owner.name, "__init__")
            else:
                case.assertIsInstance(node.ctx, ast.Load)
        elif isinstance(node, ast.Subscript):
            case.assertIsInstance(node.ctx, ast.Load)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            case.assertNotIn(node.value, forbidden_names)
        if isinstance(node, ast.keyword) and node.arg == "shell":
            case.fail("shell keyword is outside the acceptance authority surface")
        if isinstance(node, ast.Name) and node.id == "subprocess":
            case.assertIsInstance(node.ctx, ast.Load)
            parent = parents[node]
            case.assertIsInstance(parent, ast.Attribute)
            case.assertIs(parent.value, node)
        if isinstance(node, ast.Name) and node.id == "os":
            parent = parents[node]
            case.assertIsInstance(parent, ast.Attribute)
            case.assertIn(
                parent.attr,
                {
                    "O_CLOEXEC",
                    "O_NOFOLLOW",
                    "O_RDONLY",
                    "O_WRONLY",
                    "O_CREAT",
                    "O_EXCL",
                    "close",
                    "fchmod",
                    "fdopen",
                    "fstat",
                    "ftruncate",
                    "getegid",
                    "geteuid",
                    "getgrouplist",
                    "open",
                    "pidfd_open",
                    "walk",
                },
            )
        if isinstance(node, ast.Name) and node.id == "sys":
            parent = parents[node]
            case.assertIsInstance(parent, ast.Attribute)
            case.assertEqual(parent.attr, "argv")

    case.assertEqual(actual_call_targets, reviewed_call_targets)

    subprocess_attributes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "subprocess"
    ]
    case.assertTrue(subprocess_attributes)
    case.assertTrue(
        all(
            node.attr in {"check_output", "DEVNULL", "SubprocessError"}
            for node in subprocess_attributes
        )
    )
    check_output_attributes = [
        node for node in subprocess_attributes if node.attr == "check_output"
    ]
    check_output_calls = []
    for attribute in check_output_attributes:
        parent = parents[attribute]
        case.assertIsInstance(parent, ast.Call)
        case.assertIs(parent.func, attribute)
        case.assertFalse(is_trivially_dead(parent))
        check_output_calls.append(parent)
    case.assertEqual(len(check_output_calls), 3)

    client_functions = functions_named("client")
    case.assertEqual(len(client_functions), 1)
    case.assertEqual(bindings("client"), [client_functions[0]])
    client_function = client_functions[0]
    case.assertEqual(client_function.decorator_list, [])
    client_calls = [
        call
        for call in check_output_calls
        if containing_function(call) is client_function
    ]
    case.assertEqual(len(client_calls), 1)
    invocation = client_calls[0]
    case.assertEqual(len(invocation.args), 1)
    case.assertIsInstance(invocation.args[0], ast.List)
    argv = invocation.args[0].elts
    case.assertEqual(len(argv), 8)
    expected_argv = (
        (ast.Name, "PYTHON"),
        (ast.Constant, "-I"),
        (ast.Constant, "-S"),
        (ast.Constant, "-B"),
        (ast.Name, "CLIENT"),
        (ast.Name, "INSTALLED_MANIFEST_SHA256"),
        (ast.Name, "action"),
        (ast.Starred, None),
    )
    for value, (kind, expected) in zip(argv, expected_argv, strict=True):
        case.assertIsInstance(value, kind)
        if isinstance(value, ast.Name):
            case.assertEqual(value.id, expected)
        elif isinstance(value, ast.Constant):
            case.assertEqual(value.value, expected)
    run_id_arg = argv[7]
    case.assertIsInstance(run_id_arg.value, ast.IfExp)
    case.assertIsInstance(run_id_arg.value.test, ast.Compare)
    case.assertEqual(
        {keyword.arg for keyword in invocation.keywords},
        {
            "close_fds",
            "env",
            "extra_groups",
            "group",
            "stderr",
            "stdin",
            "text",
            "timeout",
            "user",
        },
    )
    client_keywords = {keyword.arg: keyword.value for keyword in invocation.keywords}
    for name in ("close_fds", "text"):
        case.assertIsInstance(client_keywords[name], ast.Constant)
        case.assertIs(client_keywords[name].value, True)
    case.assertIsInstance(client_keywords["timeout"], ast.Name)
    case.assertEqual(client_keywords["timeout"].id, "timeout")
    for name, attribute in (("user", "pw_uid"), ("group", "pw_gid")):
        case.assertIsInstance(client_keywords[name], ast.Attribute)
        case.assertIsInstance(client_keywords[name].value, ast.Name)
        case.assertEqual(client_keywords[name].value.id, "account")
        case.assertEqual(client_keywords[name].attr, attribute)
    case.assertIsInstance(client_keywords["env"], ast.Dict)
    case.assertEqual(
        [key.value for key in client_keywords["env"].keys],
        ["GITHUB_TOKEN", "OPENAI_API_KEY"],
    )
    case.assertEqual(
        [value.value for value in client_keywords["env"].values],
        ["I044A_FAKE_ONLY", "I044A_FAKE_ONLY"],
    )
    extra_groups = client_keywords["extra_groups"]
    case.assertIsInstance(extra_groups, ast.Call)
    case.assertIsInstance(extra_groups.func, ast.Attribute)
    case.assertIsInstance(extra_groups.func.value, ast.Name)
    case.assertEqual(extra_groups.func.value.id, "os")
    case.assertEqual(extra_groups.func.attr, "getgrouplist")
    case.assertEqual(len(extra_groups.args), 2)
    case.assertTrue(
        all(isinstance(argument, ast.Attribute) for argument in extra_groups.args)
    )
    case.assertEqual(
        [argument.attr for argument in extra_groups.args], ["pw_name", "pw_gid"]
    )
    case.assertTrue(
        all(
            isinstance(argument.value, ast.Name) and argument.value.id == "account"
            for argument in extra_groups.args
        )
    )

    # The two non-client launches are existing, fixed administrative probes.
    ctl_functions = functions_named("ctl")
    case.assertEqual(len(ctl_functions), 1)
    case.assertEqual(bindings("ctl"), [ctl_functions[0]])
    case.assertEqual(ctl_functions[0].decorator_list, [])
    ctl_arguments = ctl_functions[0].args
    case.assertEqual(ctl_arguments.posonlyargs, [])
    case.assertEqual(ctl_arguments.args, [])
    case.assertEqual(ctl_arguments.kwonlyargs, [])
    case.assertIsNone(ctl_arguments.kwarg)
    case.assertIsNotNone(ctl_arguments.vararg)
    case.assertEqual(ctl_arguments.vararg.arg, "arguments")
    case.assertIsInstance(ctl_arguments.vararg.annotation, ast.Name)
    case.assertEqual(ctl_arguments.vararg.annotation.id, "str")
    ctl_calls = [
        call
        for call in check_output_calls
        if containing_function(call) is ctl_functions[0]
    ]
    case.assertEqual(len(ctl_calls), 1)
    ctl_call = ctl_calls[0]
    case.assertEqual(
        [
            (keyword.arg, getattr(keyword.value, "value", None))
            for keyword in ctl_call.keywords
        ],
        [("text", True)],
    )
    ctl_argv = ctl_call.args[0]
    case.assertIsInstance(ctl_argv, ast.List)
    case.assertEqual(len(ctl_argv.elts), 2)
    case.assertIsInstance(ctl_argv.elts[0], ast.Constant)
    case.assertEqual(ctl_argv.elts[0].value, "/usr/bin/systemctl")
    case.assertIsInstance(ctl_argv.elts[1], ast.Starred)
    case.assertIsInstance(ctl_argv.elts[1].value, ast.Name)
    case.assertEqual(ctl_argv.elts[1].value.id, "arguments")

    ctl_site_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "ctl"
        and containing_function(node) is not ctl_functions[0]
    ]

    def fixed_ctl_shape(call: ast.Call) -> tuple[str, ...]:
        case.assertEqual(call.keywords, [])
        shape = []
        for argument in call.args:
            case.assertNotIsInstance(argument, ast.Starred)
            if isinstance(argument, ast.Name):
                case.assertEqual(argument.id, "UNIT")
                shape.append("$UNIT")
            else:
                case.assertIsInstance(argument, ast.Constant)
                case.assertIsInstance(argument.value, str)
                shape.append(argument.value)
        return tuple(shape)

    case.assertEqual(
        sorted(fixed_ctl_shape(call) for call in ctl_site_calls),
        sorted(
            (
                ("is-active", "$UNIT"),
                ("show", "$UNIT", "-p", "MainPID", "--value"),
                ("show", "$UNIT", "-p", "ControlGroup", "--value"),
                ("kill", "--kill-whom=main", "--signal=KILL", "$UNIT"),
            )
        ),
    )

    main_functions = functions_named("main")
    case.assertEqual(len(main_functions), 1)
    case.assertEqual(bindings("main"), [main_functions[0]])
    main_function = main_functions[0]
    case.assertEqual(main_function.decorator_list, [])
    main_process_calls = [
        call for call in check_output_calls if containing_function(call) is main_function
    ]
    case.assertEqual(len(main_process_calls), 1)
    journal_call = main_process_calls[0]
    case.assertEqual(
        [
            (keyword.arg, getattr(keyword.value, "value", None))
            for keyword in journal_call.keywords
        ],
        [("text", True)],
    )
    journal_argv = journal_call.args[0]
    case.assertIsInstance(journal_argv, ast.List)
    case.assertEqual(len(journal_argv.elts), 8)
    case.assertTrue(
        all(isinstance(element, ast.Constant) for element in journal_argv.elts[:2])
    )
    case.assertEqual(
        [element.value for element in journal_argv.elts[:2]],
        ["/usr/bin/journalctl", "-u"],
    )
    case.assertIsInstance(journal_argv.elts[2], ast.Name)
    case.assertEqual(journal_argv.elts[2].id, "UNIT")
    case.assertTrue(
        all(isinstance(element, ast.Constant) for element in journal_argv.elts[3:])
    )
    case.assertEqual(
        [element.value for element in journal_argv.elts[3:]],
        ["--since", "-3min", "--no-pager", "-o", "cat"],
    )

    devnull_attributes = [
        node for node in subprocess_attributes if node.attr == "DEVNULL"
    ]
    case.assertEqual(len(devnull_attributes), 2)
    case.assertEqual(
        {
            parents[node].arg
            for node in devnull_attributes
            if isinstance(parents[node], ast.keyword)
        },
        {"stderr", "stdin"},
    )
    case.assertTrue(
        all(parents[parents[node]] is invocation for node in devnull_attributes)
    )
    error_attributes = [
        node for node in subprocess_attributes if node.attr == "SubprocessError"
    ]
    case.assertEqual(len(error_attributes), 1)
    case.assertIsInstance(parents[error_attributes[0]], ast.ExceptHandler)

    live_main_client_calls = [
        call
        for call in ast.walk(main_function)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "client"
        and not is_trivially_dead(call)
    ]
    case.assertTrue(live_main_client_calls)
    guards = [
        statement
        for statement in tree.body
        if isinstance(statement, ast.If)
        and isinstance(statement.test, ast.Compare)
        and any(
            isinstance(node, ast.Constant) and node.value == "__main__"
            for node in ast.walk(statement.test)
        )
    ]
    case.assertEqual(len(guards), 1)
    guard = guards[0]
    case.assertIsInstance(guard.test.left, ast.Name)
    case.assertEqual(guard.test.left.id, "__name__")
    case.assertEqual(len(guard.test.ops), 1)
    case.assertIsInstance(guard.test.ops[0], ast.Eq)
    case.assertEqual(len(guard.test.comparators), 1)
    case.assertIsInstance(guard.test.comparators[0], ast.Constant)
    case.assertEqual(guard.test.comparators[0].value, "__main__")
    case.assertEqual(guard.orelse, [])
    case.assertEqual(len(guard.body), 1)
    case.assertTrue(
        any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "main"
            for node in ast.walk(guard)
        )
    )

    # Pin the complete reviewed AST as a final closed-world backstop.  The
    # checks above provide focused failures; this prevents receiver rebinding or
    # a helper-body rewrite from preserving the visible call spelling.
    reviewed_ast_digest = (
        "83c65add5235c22593219672f1dbf90964052b0ad8fa8567de292a8e7c60e436"
    )
    canonical_ast = ast.dump(tree, annotate_fields=True, include_attributes=False)
    case.assertEqual(hashlib.sha256(canonical_ast.encode()).hexdigest(), reviewed_ast_digest)


def evaluate_filter(policy: bytes, syscall: int, argument0: int = 0) -> int:
    instructions = [
        struct.unpack("HBBI", policy[index : index + 8])
        for index in range(0, len(policy), 8)
    ]
    accumulator = 0
    pc = 0
    while True:
        code, jump_true, jump_false, value = instructions[pc]
        if code == 0x20:
            accumulator = {0: syscall, 4: 0xC000003E, 16: argument0 & 0xFFFFFFFF}[value]
            pc += 1
        elif code == 0x15:
            pc += 1 + (jump_true if accumulator == value else jump_false)
        elif code == 0x45:
            pc += 1 + (jump_true if accumulator & value else jump_false)
        elif code == 0x06:
            return value
        else:
            raise AssertionError(f"unexpected BPF instruction {code:#x}")


class I044AContractTests(unittest.TestCase):
    def run_update_case(
        self,
        failure: str | None = None,
        *,
        state: str = "predecessor",
        target_error: str | None = None,
        installed_unit: bytes | None = None,
    ):
        """Exercise installer.main with a real sibling filesystem and fake systemd."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "i044b-v2"
            base.mkdir()
            base_unit = b"base unit"
            (base / "novalton-verification.service").write_bytes(base_unit)
            target = root / "i044a-v2"
            target_unit = (
                b"candidate unit" if state == "candidate" else b"predecessor unit"
            )
            if state != "absent":
                target.mkdir()
                (target / "identity").write_text(state)
                (target / "novalton-verification.service").write_bytes(target_unit)
            candidate = root / ".i044a-v2-candidate"
            candidate.mkdir()
            (candidate / "identity").write_text("candidate")
            unit = root / "novalton-verification.service"
            initial_unit = installed_unit
            if initial_unit is None:
                initial_unit = base_unit if state == "absent" else target_unit
            unit.write_bytes(initial_unit)
            calls: list[tuple[str, ...]] = []
            events: list[str] = []
            moves: list[tuple[Path, Path]] = []
            sibling_number = 0
            original_write_bytes = Path.write_bytes

            def reserve(prefix: str) -> Path:
                nonlocal sibling_number
                sibling_number += 1
                return root / f"{prefix}{sibling_number}"

            def move(source: Path, destination: Path) -> None:
                moves.append((source, destination))
                if failure == "predecessor_rename" and source == target:
                    raise OSError("predecessor rename failure")
                if failure == "promotion" and source == candidate:
                    raise OSError("promotion failure")
                source.rename(destination)

            def checked(command: list[str]) -> None:
                calls.append(tuple(command))
                phase = command[1] if len(command) > 1 else ""
                if failure == "stop" and phase == "stop" and calls.count(tuple(command)) == 1:
                    raise RuntimeError("stop failure after invocation")
                if failure == phase and calls.count(tuple(command)) == 1:
                    raise RuntimeError(f"{phase} failure")

            def write_bytes(path: Path, data: bytes) -> int:
                if failure == "unit" and path == unit and data == b"candidate unit":
                    raise OSError("unit replacement failure")
                return original_write_bytes(path, data)

            def marker(path: Path) -> str | None:
                identity = path / "identity"
                return identity.read_text() if identity.exists() else None

            def target_state() -> str:
                events.append("target")
                if target_error is not None:
                    raise RuntimeError(target_error)
                return state

            with ExitStack() as stack:
                stack.enter_context(patch.object(installer, "BASE", base))
                stack.enter_context(patch.object(installer, "TARGET", target))
                stack.enter_context(patch.object(installer, "UNIT", unit))
                stack.enter_context(patch.object(installer.os, "geteuid", return_value=0))
                stack.enter_context(patch.object(installer.sys, "argv", ["install.py"]))
                stack.enter_context(patch.object(installer, "verify_staged_installer", side_effect=lambda: events.append("stage")))
                stack.enter_context(patch.object(installer, "verify_target_parent", side_effect=lambda: events.append("parent")))
                stack.enter_context(patch.object(installer, "verify_foundation", side_effect=lambda: events.append("foundation") or ({}, {"installed_manifest_sha256": "f" * 64})))
                stack.enter_context(patch.object(installer, "load_bundle", side_effect=lambda: events.append("bundle") or {"novalton-verification.service": b"candidate unit"}))
                stack.enter_context(patch.object(installer, "expected_release_manifest", side_effect=lambda *_: events.append("manifest") or b"candidate manifest"))
                def trusted_unit(expected: bytes) -> bytes:
                    events.append("unit")
                    if unit.read_bytes() != expected:
                        raise RuntimeError("installed_unit_drift")
                    return expected

                stack.enter_context(patch.object(installer, "trusted_unit", side_effect=trusted_unit))
                stack.enter_context(patch.object(installer, "materialize_candidate", side_effect=lambda *_: events.append("materialize") or candidate))
                stack.enter_context(patch.object(installer, "target_state", side_effect=target_state))
                stack.enter_context(patch.object(installer, "verify_release", side_effect=lambda *_: events.append("verify_release") or {"installed_manifest_sha256": installer.digest(b"candidate manifest")}))
                stack.enter_context(patch.object(installer, "verify_unit_bytes", side_effect=lambda _: events.append("verify_unit")))
                stack.enter_context(patch.object(installer, "reserve_sibling", side_effect=reserve))
                stack.enter_context(patch.object(installer, "move_sibling", side_effect=move))
                stack.enter_context(patch.object(installer, "checked", side_effect=checked))
                stack.enter_context(patch.object(Path, "write_bytes", new=write_bytes))
                try:
                    result = installer.main()
                    error = None
                except RuntimeError as raised:
                    result = None
                    error = raised
            return {
                "calls": calls,
                "candidate": marker(target) == "candidate",
                "error": error,
                "events": events,
                "moves": moves,
                "result": result,
                "target": marker(target),
                "unit": unit.read_bytes(),
            }

    def test_health_client_has_no_workspace_or_filesystem_authority(self):
        expected = "a" * 64
        response = {
            "state": "ready",
            "active": False,
            "definition": "repository-probe-v1",
            "foundation_input_sha256": i044a_client.FOUNDATION_INPUT_SHA256,
            "foundation_installed_manifest_sha256": "b" * 64,
            "i044a_input_sha256": "c" * 64,
            "installed_manifest_sha256": expected,
            "db_mode": False,
        }
        with patch.object(i044a_client, "request", return_value=response) as request:
            self.assertEqual(i044a_client.health(expected), response)
        request.assert_called_once_with({"op": "health"})
        source = (artifacts / "client/i044a_client.py").read_text()
        tree = ast.parse(source)
        self.assertNotIn("workspace", source)
        self.assertNotIn("pathlib", source)
        self.assertNotIn("source_digest(root", source)
        self.assertFalse(
            any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "open"
                for node in ast.walk(tree)
            )
        )

    def test_installed_security_response_preserves_client_error(self):
        normal = {
            "accepted": {"state": "accepted", "run_id": "a" * 32},
            "arbitrary_fd": {"error": "invalid_request"},
            "extra_fd": {"error": "invalid_request"},
            "other_pid": {"error": "invalid_capability"},
            "replay": {"error": "invalid_capability"},
            "wrong_capability": {"error": "invalid_capability"},
            "wrong_digest": {"error": "invalid_request"},
        }
        account = SimpleNamespace(pw_name="test-client", pw_uid=123, pw_gid=456)
        with (
            patch.object(i044a_acceptance.pwd, "getpwnam", return_value=account),
            patch.object(i044a_acceptance.os, "getgrouplist", return_value=[]),
            patch.object(
                i044a_acceptance.subprocess,
                "check_output",
                side_effect=(json.dumps(normal), '{"error":"example"}'),
            ) as output,
        ):
            self.assertEqual(i044a_acceptance.security_response(), normal)
            with self.assertRaises(AssertionError) as raised:
                i044a_acceptance.security_response()
        self.assertIn("security_client_error", str(raised.exception))
        self.assertIn("example", str(raised.exception))
        self.assertNotIn("arbitrary_fd", str(raised.exception))
        self.assertEqual(output.call_count, 2)
        self.assertEqual(output.call_args_list[0].args[0][-1], "security")

    def test_client_rejects_legacy_workspace_and_arbitrary_path_shapes(self):
        expected = "a" * 64
        arguments = (
            ["i044a_client.py", "/inaccessible/workspace", expected, "health"],
            ["i044a_client.py", expected, "health", "/etc"],
            ["i044a_client.py", expected, '{"op":"health"}'],
        )
        for argv in arguments:
            with (
                self.subTest(argv=argv),
                patch.object(i044a_client.sys, "argv", argv),
                patch.object(i044a_client, "request") as request,
                self.assertRaisesRegex(RuntimeError, "release_identity|action_shape"),
            ):
                i044a_client.main()
            request.assert_not_called()

    def test_client_verify_binds_result_to_server_snapshot_identity(self):
        expected = "a" * 64
        run_id = "b" * 32
        responses = (
            {
                "state": "ready",
                "definition": "repository-probe-v1",
                "foundation_input_sha256": i044a_client.FOUNDATION_INPUT_SHA256,
                "foundation_installed_manifest_sha256": "f" * 64,
                "i044a_input_sha256": "e" * 64,
                "installed_manifest_sha256": expected,
                "db_mode": False,
            },
            {"state": "prepared", "capability": "c" * 64, "source_digest": "d" * 64},
            {"state": "accepted", "run_id": run_id},
            {"state": "passed", "run_id": run_id, "source_digest": "e" * 64},
        )
        with (
            patch.object(i044a_client, "request", side_effect=responses),
            self.assertRaisesRegex(RuntimeError, "snapshot_identity_mismatch"),
        ):
            i044a_client.verify(expected)

    def test_root_side_stale_check_matches_worker_snapshot_digest(self):
        with i044a_acceptance.TrustedFixtureWorkspace() as fixture, tempfile.TemporaryDirectory() as storage:
            source = fixture.path
            with (
                patch.object(i044a, "SNAPSHOT_SOURCE", source),
                patch.object(i044a.foundation, "STORAGE", Path(storage)),
            ):
                snapshot, snapshot_digest = i044a.stage_snapshot("f" * 32)
            self.assertEqual(i044a_acceptance.source_digest(source), snapshot_digest)
            fixture.replace_fixture(i044a_acceptance.FIXTURE_BYTES + b"# changed\n")
            self.assertNotEqual(i044a_acceptance.source_digest(source), snapshot_digest)
            self.assertEqual(
                (snapshot / "workspace/untrusted_probe.py").read_bytes(),
                i044a_acceptance.FIXTURE_BYTES,
            )
            self.assertTrue(i044a.destroy_snapshot(snapshot))

    def test_trusted_fixture_is_private_deterministic_and_cleanup_is_idempotent(self):
        fixture = i044a_acceptance.TrustedFixtureWorkspace()
        root = fixture.path
        self.assertEqual(root.stat().st_uid, i044a_acceptance.os.geteuid())
        self.assertEqual(root.stat().st_gid, i044a_acceptance.os.getegid())
        self.assertEqual(root.stat().st_mode & 0o777, 0o700)
        self.assertEqual(fixture.fixture_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(fixture.fixture_path.read_bytes(), i044a_acceptance.FIXTURE_BYTES)
        fixture.cleanup()
        fixture.cleanup()
        self.assertFalse(root.exists())

    def test_fixture_symlink_substitution_and_interrupt_cleanup_are_safe(self):
        with tempfile.TemporaryDirectory() as outside:
            sentinel = Path(outside) / "sentinel"
            sentinel.write_bytes(b"unchanged")
            fixture = i044a_acceptance.TrustedFixtureWorkspace()
            fixture.fixture_path.unlink()
            fixture.fixture_path.symlink_to(sentinel)
            with self.assertRaises(OSError):
                fixture.replace_fixture(b"attacker payload")
            self.assertEqual(sentinel.read_bytes(), b"unchanged")
            root = fixture.path
            fixture.cleanup()
            self.assertFalse(root.exists())

        root = None
        with (
            self.assertRaises(KeyboardInterrupt),
            i044a_acceptance.TrustedFixtureWorkspace() as fixture,
        ):
            root = fixture.path
            raise KeyboardInterrupt
        self.assertFalse(root.exists())

    def test_privileged_acceptance_rejects_checkout_argument_without_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            checkout = Path(directory) / "checkout"
            outside = Path(directory) / "sentinel"
            checkout.mkdir()
            outside.write_bytes(b"unchanged")
            expected = checkout / "apps/api/src/novalton_api/infrastructure/verification_sandbox.py"
            expected.parent.mkdir(parents=True)
            expected.symlink_to(outside)
            before = {path.relative_to(checkout): (path.is_symlink(), path.readlink() if path.is_symlink() else path.read_bytes() if path.is_file() else None) for path in checkout.rglob("*")}
            with (
                patch.object(i044a_acceptance.os, "geteuid", return_value=0),
                patch.object(i044a_acceptance.sys, "argv", ["accept_i044a_installed.py", str(checkout)]),
                patch.object(i044a_acceptance, "ctl") as ctl,
                patch.object(i044a_acceptance, "client") as client,
                self.assertRaisesRegex(SystemExit, "usage"),
            ):
                i044a_acceptance.main()
            ctl.assert_not_called()
            client.assert_not_called()
            self.assertEqual(outside.read_bytes(), b"unchanged")
            self.assertTrue(expected.is_symlink())
            after = {path.relative_to(checkout): (path.is_symlink(), path.readlink() if path.is_symlink() else path.read_bytes() if path.is_file() else None) for path in checkout.rglob("*")}
            self.assertEqual(after, before)

    def test_privileged_acceptance_never_writes_caller_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkout = root / "checkout"
            release = root / "verified-release"
            checkout.mkdir()
            release.mkdir()
            sentinel = root / "outside-sentinel"
            sentinel.write_bytes(b"unchanged")
            link = checkout / "attacker-link"
            link.symlink_to(sentinel)
            manifest = b"trusted test manifest\n"
            manifest_path = release / "manifest.json"
            manifest_path.write_bytes(manifest)
            (release / "release-metadata.json").write_text(json.dumps({
                "schema": "novalton.i044a.release-metadata.v1",
                "i044a_input_sha256": "a" * 64,
                "foundation_input_sha256": "b" * 64,
                "foundation_installed_manifest_sha256": "c" * 64,
                "installed_manifest_sha256": hashlib.sha256(manifest).hexdigest(),
            }))
            before = {p.relative_to(checkout): (p.is_symlink(), p.readlink() if p.is_symlink() else p.read_bytes() if p.is_file() else None) for p in checkout.rglob("*")}
            original_read_bytes = Path.read_bytes
            original_read_text = Path.read_text

            def read_bytes(path: Path) -> bytes:
                if path == manifest_path:
                    return manifest
                if path == Path("/proc/123/environ"):
                    return b""
                return original_read_bytes(path)

            def read_text(path: Path, *args, **kwargs) -> str:
                if path == Path("/proc/123/status"):
                    return "NoNewPrivs:\t1\nCapEff:\t00000000\n"
                return original_read_text(path, *args, **kwargs)

            def control(*args: str) -> str:
                if args[0] == "is-active":
                    return "active"
                if "MainPID" in args:
                    return "123"
                return "/novalton-test.service"

            marker = (root / "marker", (1, 2))
            original_cwd = os.getcwd()
            try:
                os.chdir(checkout)
                with (
                    patch.object(i044a_acceptance.os, "geteuid", return_value=0),
                    patch.object(i044a_acceptance.sys, "argv", ["accept_i044a_installed.py"]),
                    patch.object(i044a_acceptance, "RELEASE", release),
                    patch.object(i044a_acceptance, "INSTALLED_MANIFEST_SHA256", hashlib.sha256(manifest).hexdigest()),
                    patch.object(i044a_acceptance, "ctl", side_effect=control),
                    patch.object(i044a_acceptance, "create_host_marker", return_value=marker),
                    patch.object(i044a_acceptance, "remove_host_marker") as remove_marker,
                    patch.object(i044a_acceptance, "wait_ready", side_effect=RuntimeError("stop after setup")),
                    patch.object(Path, "read_bytes", new=read_bytes),
                    patch.object(Path, "read_text", new=read_text),
                    self.assertRaisesRegex(RuntimeError, "stop after setup"),
                ):
                    i044a_acceptance.main()
            finally:
                os.chdir(original_cwd)
            remove_marker.assert_called_once_with(marker)
            after = {p.relative_to(checkout): (p.is_symlink(), p.readlink() if p.is_symlink() else p.read_bytes() if p.is_file() else None) for p in checkout.rglob("*")}
            self.assertEqual(after, before)
            self.assertEqual(sentinel.read_bytes(), b"unchanged")

    def test_wrong_installed_manifest_fails_before_non_health_operation(self):
        expected = "a" * 64
        response = {
            "state": "ready",
            "definition": "repository-probe-v1",
            "foundation_input_sha256": i044a_client.FOUNDATION_INPUT_SHA256,
            "foundation_installed_manifest_sha256": "c" * 64,
            "i044a_input_sha256": "d" * 64,
            "installed_manifest_sha256": "b" * 64,
            "db_mode": False,
        }
        with (
            patch.object(i044a_client, "request", return_value=response) as request,
            self.assertRaisesRegex(RuntimeError, "sandbox_definition_mismatch"),
        ):
            i044a_client.start(expected)
        request.assert_called_once_with({"op": "health"})

    def test_closed_world_request_shapes(self):
        self.assertEqual(i044a.decode(b'{"op":"prepare"}', 0), {"op": "prepare"})
        value = {"op": "verify", "capability": "a" * 64}
        self.assertEqual(i044a.decode(json.dumps(value).encode(), 0), value)
        for operation in ("health", "diagnostic"):
            self.assertEqual(
                i044a.decode(json.dumps({"op": operation}).encode(), 0),
                {"op": operation},
            )
        for operation in ("result", "cancel", "cleanup"):
            value = {"op": operation, "run_id": "b" * 32}
            self.assertEqual(i044a.decode(json.dumps(value).encode(), 0), value)

    def test_health_requires_authorized_peer_identity_before_request_decode(self):
        class Connection:
            def __init__(self):
                self.sent = []
                self.received = False

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def settimeout(self, timeout):
                self.timeout = timeout

            def getsockopt(self, *args):
                return struct.pack("3i", 123, 999, 999)

            def recvmsg(self, *args):
                self.received = True
                return b'{"op":"health"}\n', [], 0, None

            def sendall(self, value):
                self.sent.append(value)

        connection = Connection()

        class Server:
            def __init__(self):
                self.accepted = False

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def bind(self, endpoint):
                self.endpoint = endpoint

            def listen(self, backlog):
                self.backlog = backlog

            def accept(self):
                if self.accepted:
                    raise KeyboardInterrupt
                self.accepted = True
                return connection, None

        server = Server()

        class Endpoint:
            def unlink(self, missing_ok=False):
                self.missing_ok = missing_ok

            def __str__(self):
                return "/unused/control.sock"

        class Policy:
            def read_bytes(self):
                return b'{"client_gid":1}'

        with (
            patch.object(i044a.foundation, "ENDPOINT", Endpoint()),
            patch.object(i044a.foundation, "POLICY", Policy()),
            patch.object(i044a.socket, "socket", return_value=server),
            patch.object(i044a.os, "chmod"),
            patch.object(i044a.os, "chown"),
            self.assertRaises(KeyboardInterrupt),
        ):
            i044a.serve(object(), 1000)
        self.assertFalse(connection.received)
        self.assertEqual(
            connection.sent,
            [i044a.foundation.encode({"error": "unauthorized"})],
        )

    def test_no_generic_or_caller_snapshot_authority_fields(self):
        fields = (
            "argv",
            "command",
            "cwd",
            "digest",
            "docker",
            "env",
            "executable",
            "fd",
            "image",
            "limits",
            "mount",
            "network",
            "path",
            "runtime",
            "shell",
            "source_digest",
            "systemd",
        )
        for field in fields:
            with self.subTest(field=field), self.assertRaises(ValueError):
                i044a.decode(json.dumps({"op": "prepare", field: "x"}).encode(), 0)

    def test_arbitrary_and_extra_directory_fds_are_rejected(self):
        requests = (
            ({"op": "prepare"}, 1),
            ({"op": "verify", "capability": "a" * 64}, 1),
            ({"op": "verify", "capability": "a" * 64}, 2),
        )
        for value, count in requests:
            with (
                self.subTest(value=value, count=count),
                self.assertRaisesRegex(ValueError, "descriptor_shape"),
            ):
                i044a.decode(json.dumps(value).encode(), count)

    def test_worker_creates_and_hashes_snapshot_from_fixed_source(self):
        with (
            tempfile.TemporaryDirectory() as source_directory,
            tempfile.TemporaryDirectory() as storage,
        ):
            source = Path(source_directory)
            (source / "untrusted.py").write_text(
                "raise RuntimeError('must not execute')\n"
            )
            (source / ".git").mkdir()
            (source / ".git/HEAD").write_text("not admitted")
            (source / ".env.test").write_text("not admitted")
            with (
                patch.object(i044a, "SNAPSHOT_SOURCE", source),
                patch.object(i044a.foundation, "STORAGE", Path(storage)),
            ):
                snapshot, expected = i044a.stage_snapshot("a" * 32)
                self.assertEqual(i044a._snapshot_digest(snapshot), expected)
                self.assertFalse((snapshot / ".git").exists())
                self.assertFalse((snapshot / ".env.test").exists())
                self.assertTrue(i044a.destroy_snapshot(snapshot))

    def test_capability_is_pid_bound_wrong_value_rejected_and_replay_rejected(self):
        worker = i044a.Worker.__new__(i044a.Worker)
        worker.lock = threading.Lock()
        worker.blocked = False
        worker.active = None
        worker.pending = None
        worker.recent = None
        worker.cgroup = Path("/unused")
        worker.execute_probe = lambda job: None
        snapshot = Path("/server-owned-snapshot")

        class NoStartThread:
            def __init__(self, *args, **kwargs):
                pass

            def start(self):
                pass

        with (
            patch.object(i044a, "stage_snapshot", return_value=(snapshot, "d" * 64)),
            patch.object(i044a.foundation, "write_state"),
            patch.object(i044a.threading, "Thread", NoStartThread),
        ):
            prepared = worker.request({"op": "prepare"}, 101)
            capability = prepared["capability"]
            self.assertEqual(
                worker.request({"op": "verify", "capability": "0" * 64}, 101),
                {"error": "invalid_capability"},
            )
            self.assertEqual(
                worker.request({"op": "verify", "capability": capability}, 202),
                {"error": "invalid_capability"},
            )
            accepted = worker.request({"op": "verify", "capability": capability}, 101)
            self.assertEqual(accepted["state"], "accepted")
            self.assertEqual(
                worker.request({"op": "verify", "capability": capability}, 101),
                {"error": "invalid_capability"},
            )

    def test_expired_capability_destroys_server_snapshot(self):
        worker = i044a.Worker.__new__(i044a.Worker)
        worker.lock = threading.Lock()
        worker.blocked = False
        worker.active = None
        worker.recent = None
        worker.digest = "release"
        worker.evidence = {
            "i044a_input_sha256": "a" * 64,
            "installed_manifest_sha256": "b" * 64,
            "foundation_input_sha256": "c" * 64,
            "foundation_installed_manifest_sha256": "d" * 64,
        }
        worker.reconciled = 0
        worker.pending = {"expires": time.monotonic() - 1, "snapshot": Path("/expired")}
        with patch.object(i044a, "destroy_snapshot", return_value=True) as destroy:
            worker.request({"op": "health"}, 1)
        destroy.assert_called_once_with(Path("/expired"))
        self.assertIsNone(worker.pending)

    def test_clone_filter_allows_processes_but_denies_all_namespace_classes(self):
        policy = installer.seccomp_policy()
        allow = 0x7FFF0000
        denied = 0x00050001
        self.assertEqual(evaluate_filter(policy, 56, 17), allow)
        for flag in (
            0x80,
            0x00020000,
            0x02000000,
            0x04000000,
            0x08000000,
            0x10000000,
            0x20000000,
            0x40000000,
        ):
            with self.subTest(flag=hex(flag)):
                self.assertEqual(evaluate_filter(policy, 56, flag | 17), denied)
        self.assertEqual(evaluate_filter(policy, 435), denied)

    def test_bundle_input_is_fixed_and_installed_identity_is_derived(self):
        loaded = installer.load_bundle(artifacts / "bundle.tar")
        if not installer.BASE.is_dir():
            self.skipTest("pinned I-044B foundation unavailable; release derivation is install-only")
        foundation_files, foundation_metadata = installer.verify_foundation(ownership=False)
        manifest = installer.expected_release_manifest(foundation_files, loaded)
        metadata = json.loads(installer.release_metadata(manifest, foundation_metadata))
        self.assertEqual(metadata["i044a_input_sha256"], installer.I044A_INPUT_SHA256)
        self.assertEqual(metadata["installed_manifest_sha256"], installer.digest(manifest))
        altered = bytearray((artifacts / "bundle.tar").read_bytes())
        altered[-1] ^= 1
        with tempfile.NamedTemporaryFile() as candidate:
            candidate.write(altered)
            candidate.flush()
            with self.assertRaisesRegex(RuntimeError, "bundle_digest_mismatch"):
                installer.load_bundle(Path(candidate.name))

    def test_release_closure_validation_rejects_extra_files_and_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            release = Path(directory) / "release"
            (release / "client").mkdir(parents=True)
            client = release / "client/i044a_client.py"
            client.write_bytes(b"reviewed client\n")
            manifest, expected = finalize_test_release(release)
            installer.verify_release(release, expected, ownership=False)
            release.chmod(0o755)
            (release / "extra").write_bytes(b"unexpected")
            (release / "extra").chmod(0o444)
            release.chmod(0o555)
            with self.assertRaisesRegex(RuntimeError, "release_shape_invalid"):
                installer.verify_release(release, expected, ownership=False)
            release.chmod(0o755)
            (release / "extra").unlink()
            (release / "unexpected-empty-directory").mkdir(mode=0o555)
            release.chmod(0o555)
            with self.assertRaisesRegex(RuntimeError, "release_shape_invalid"):
                installer.verify_release(release, expected, ownership=False)
            release.chmod(0o755)
            (release / "unexpected-empty-directory").rmdir()
            (release / "link").symlink_to("client/i044a_client.py")
            release.chmod(0o555)
            with self.assertRaisesRegex(RuntimeError, "release_trust_failed"):
                installer.verify_release(release, expected, ownership=False)

    def test_target_state_is_closed_to_predecessor_or_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            release = Path(directory) / "release"
            release.mkdir()
            with patch.object(installer, "TARGET", release), patch.object(
                installer, "verify_release", return_value={"installed_manifest_sha256": "a" * 64}
            ):
                self.assertEqual(installer.target_state(), "candidate")

            def predecessor_only(_path, expected_digest=None):
                if expected_digest is None:
                    raise RuntimeError("not candidate")
                return {"installed_manifest_sha256": expected_digest}

            with patch.object(installer, "TARGET", release), patch.object(
                installer, "verify_release", side_effect=predecessor_only
            ):
                self.assertEqual(installer.target_state(), "predecessor")

            with patch.object(installer, "TARGET", release), patch.object(
                installer, "verify_release", side_effect=RuntimeError("untrusted")
            ), self.assertRaisesRegex(RuntimeError, "target_release_untrusted"):
                installer.target_state()

    def test_target_validation_rejects_symlinks_modes_ownership_and_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = root / "release"
            release.mkdir()
            payload = release / "payload"
            payload.write_bytes(b"reviewed")
            manifest, expected = finalize_test_release(release)
            release.chmod(0o755)
            with self.assertRaisesRegex(RuntimeError, "release_metadata_mismatch"):
                installer.verify_release(release, expected)
            release.chmod(0o555)
            installer.verify_release(release, expected, ownership=False)
            linked = root / "linked-release"
            linked.symlink_to(release)
            with self.assertRaisesRegex(RuntimeError, "release_metadata_mismatch"):
                installer.verify_release(linked, expected, ownership=False)
            release.chmod(0o755)
            with self.assertRaisesRegex(RuntimeError, "release_metadata_mismatch"):
                installer.verify_release(release, expected, ownership=False)
            release.chmod(0o555)
            release.chmod(0o755)
            payload.chmod(0o644)
            payload.write_bytes(b"tampered")
            payload.chmod(0o444)
            release.chmod(0o555)
            with self.assertRaisesRegex(RuntimeError, "release_content_mismatch"):
                installer.verify_release(release, expected, ownership=False)

    def test_target_rejections_happen_before_systemctl(self):
        for rejection in (
            "target_symlink",
            "target_wrong_owner",
            "target_unsafe_mode",
            "target_tampered_closure",
            "target_release_untrusted",
        ):
            with self.subTest(rejection=rejection):
                outcome = self.run_update_case(target_error=rejection)
                self.assertIsInstance(outcome["error"], RuntimeError)
                self.assertEqual(outcome["calls"], [])
                self.assertEqual(outcome["target"], "predecessor")
                self.assertEqual(outcome["unit"], b"predecessor unit")

    def test_stop_failure_recovers_without_target_mutation(self):
        outcome = self.run_update_case("stop")
        self.assertIsInstance(outcome["error"], RuntimeError)
        self.assertEqual(outcome["target"], "predecessor")
        self.assertEqual(outcome["unit"], b"predecessor unit")
        self.assertEqual(outcome["moves"], [])
        self.assertEqual(
            outcome["calls"],
            [
                ("/usr/bin/systemctl", "stop", "novalton-verification.service"),
                ("/usr/bin/systemctl", "start", "novalton-verification.service"),
                ("/usr/bin/systemctl", "is-active", "novalton-verification.service"),
            ],
        )

    def test_predecessor_rename_failure_never_attempts_nonexistent_backup_restore(self):
        outcome = self.run_update_case("predecessor_rename")
        self.assertIsInstance(outcome["error"], RuntimeError)
        self.assertEqual(outcome["target"], "predecessor")
        self.assertEqual(outcome["unit"], b"predecessor unit")
        self.assertEqual(len(outcome["moves"]), 1)
        self.assertEqual(outcome["moves"][0][0].name, "i044a-v2")
        self.assertEqual(
            outcome["calls"][-2:],
            [
                ("/usr/bin/systemctl", "start", "novalton-verification.service"),
                ("/usr/bin/systemctl", "is-active", "novalton-verification.service"),
            ],
        )

    def test_promotion_and_service_failures_restore_predecessor_through_main(self):
        for failure in ("promotion", "unit", "daemon-reload", "start", "is-active"):
            with self.subTest(failure=failure):
                outcome = self.run_update_case(failure)
                self.assertIsInstance(outcome["error"], RuntimeError)
                self.assertEqual(outcome["target"], "predecessor")
                self.assertEqual(outcome["unit"], b"predecessor unit")
                self.assertIn(
                    ("/usr/bin/systemctl", "start", "novalton-verification.service"),
                    outcome["calls"],
                )
                self.assertIn(
                    ("/usr/bin/systemctl", "is-active", "novalton-verification.service"),
                    outcome["calls"],
                )
                self.assertGreaterEqual(len(outcome["moves"]), 2)

    def test_successful_upgrade_is_validation_complete_before_stop(self):
        outcome = self.run_update_case()
        self.assertIsNone(outcome["error"])
        self.assertEqual(outcome["result"], 0)
        self.assertEqual(outcome["target"], "candidate")
        self.assertEqual(outcome["unit"], b"candidate unit")
        self.assertLess(outcome["events"].index("manifest"), outcome["events"].index("target"))
        self.assertLess(outcome["events"].index("target"), outcome["events"].index("materialize"))
        self.assertEqual(outcome["calls"][0][1], "stop")
        self.assertEqual(len(outcome["moves"]), 2)

    def test_exact_candidate_is_idempotent_without_upgrade_mutation(self):
        outcome = self.run_update_case(state="candidate")
        self.assertIsNone(outcome["error"])
        self.assertEqual(outcome["result"], 0)
        self.assertEqual(outcome["target"], "candidate")
        self.assertEqual(outcome["unit"], b"candidate unit")
        self.assertEqual(outcome["moves"], [])
        self.assertEqual(
            outcome["calls"],
            [("/usr/bin/systemctl", "is-active", "novalton-verification.service")],
        )

    def test_real_candidate_unit_state_is_idempotent_without_mutation(self):
        """Model the reproduced installed state with actual reviewed unit bytes."""
        if not foundation.is_dir():
            self.skipTest("pinned I-044B foundation unavailable; installer integration is install-only")
        loaded = installer.load_bundle(artifacts / "bundle.tar")
        foundation_manifest, foundation_metadata = installer.verify_foundation(ownership=False)
        real_verify_foundation = installer.verify_foundation
        release_manifest = installer.expected_release_manifest(
            foundation_manifest, loaded
        )
        candidate_unit = loaded["novalton-verification.service"]
        base_unit = (foundation / "novalton-verification.service").read_bytes()
        self.assertEqual(
            installer.digest(candidate_unit),
            "cdb346c91e686bf07b0e9699fb1f8f6c46f478b3a36cf53ef00a407a5ba695ab",
        )
        self.assertEqual(
            installer.digest(base_unit),
            "3e1c6243f805b1f792154d57d7fd40bf953a232630262695bc414a75fee857df",
        )
        self.assertNotEqual(candidate_unit, base_unit)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "i044a-v2"
            shutil.copytree(foundation, target, symlinks=False)
            for path in [target, *target.rglob("*")]:
                if path.is_dir():
                    path.chmod(0o755)
                else:
                    path.chmod(0o755 if path.stat().st_mode & 0o111 else 0o644)
            for relative, data in loaded.items():
                destination = target / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
            (target / "seccomp.bpf").write_bytes(installer.seccomp_policy())
            (target / "manifest.json").write_bytes(release_manifest)
            (target / "release-metadata.json").write_bytes(
                installer.release_metadata(release_manifest, foundation_metadata)
            )
            for path in [target, *target.rglob("*")]:
                path.chmod(0o555 if path.is_dir() or path.stat().st_mode & 0o111 else 0o444)

            unit = root / "novalton-verification.service"
            unit.write_bytes(candidate_unit)
            calls: list[tuple[str, ...]] = []
            release_checks: list[tuple[Path, str]] = []
            reserve_calls: list[str] = []
            unit_writes = []
            original_write_bytes = Path.write_bytes
            real_verify_release = installer.verify_release

            def verify_release(path: Path, expected: str | None = None) -> dict[str, str]:
                release_checks.append((path, expected))
                return real_verify_release(path, expected, ownership=False)

            def trusted_unit(expected: bytes) -> bytes:
                self.assertEqual(expected, candidate_unit)
                self.assertEqual(unit.read_bytes(), expected)
                return expected

            def checked(command: list[str]) -> None:
                calls.append(tuple(command))
                self.assertEqual(
                    command,
                    ["/usr/bin/systemctl", "is-active", "novalton-verification.service"],
                )

            def write_bytes(path: Path, data: bytes) -> int:
                if path == unit:
                    unit_writes.append(data)
                    raise AssertionError("idempotent path must not write UNIT")
                return original_write_bytes(path, data)

            def reserve_sibling(prefix: str) -> Path:
                reserve_calls.append(prefix)
                raise AssertionError("idempotent path must not create a predecessor backup")

            with (
                patch.object(installer, "TARGET", target),
                patch.object(installer, "UNIT", unit),
                patch.object(installer.os, "geteuid", return_value=0),
                patch.object(installer.sys, "argv", ["install.py"]),
                patch.object(installer, "verify_staged_installer"),
                patch.object(installer, "verify_target_parent"),
                patch.object(installer, "load_bundle", return_value=loaded),
                patch.object(
                    installer, "expected_release_manifest", return_value=release_manifest
                ),
                patch.object(
                    installer,
                    "verify_foundation",
                    side_effect=lambda: real_verify_foundation(ownership=False),
                ),
                patch.object(installer, "verify_release", side_effect=verify_release),
                patch.object(installer, "trusted_unit", side_effect=trusted_unit),
                patch.object(
                    installer,
                    "materialize_candidate",
                    side_effect=AssertionError("idempotent path must not materialize"),
                ),
                patch.object(
                    installer,
                    "move_sibling",
                    side_effect=AssertionError("idempotent path must not rename"),
                ),
                patch.object(installer, "reserve_sibling", side_effect=reserve_sibling),
                patch.object(installer, "checked", side_effect=checked),
                patch.object(Path, "write_bytes", new=write_bytes),
            ):
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(installer.main(), 0)
            installed_identity = installer.digest(release_manifest)
            self.assertEqual(output.getvalue(), installed_identity + "\n")
            self.assertEqual(unit_writes, [])
            self.assertEqual(reserve_calls, [])
            self.assertEqual(
                calls,
                [("/usr/bin/systemctl", "is-active", "novalton-verification.service")],
            )
            self.assertEqual(
                release_checks,
                [
                    (target, None),
                    (target, installed_identity),
                ],
            )

            def previous_order() -> None:
                if unit.read_bytes() != base_unit:
                    raise RuntimeError("installed_unit_drift")
                installer.target_state()

            with self.assertRaisesRegex(RuntimeError, "installed_unit_drift"):
                previous_order()

    def test_absent_target_with_wrong_unit_fails_before_materialization(self):
        if not foundation.is_dir():
            self.skipTest("pinned I-044B foundation unavailable; installer integration is install-only")
        base_unit = (foundation / "novalton-verification.service").read_bytes()
        real_verify_foundation = installer.verify_foundation
        loaded = installer.load_bundle(artifacts / "bundle.tar")
        foundation_manifest, _ = installer.verify_foundation(ownership=False)
        release_manifest = installer.expected_release_manifest(
            foundation_manifest, loaded
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "absent-i044a-v2"
            unit = root / "novalton-verification.service"
            unit.write_bytes(b"wrong unit")
            calls: list[tuple[str, ...]] = []

            def trusted_unit(expected: bytes) -> bytes:
                self.assertEqual(expected, base_unit)
                if unit.read_bytes() != expected:
                    raise RuntimeError("installed_unit_drift")
                return expected

            with (
                patch.object(installer, "TARGET", target),
                patch.object(installer, "UNIT", unit),
                patch.object(installer.os, "geteuid", return_value=0),
                patch.object(installer.sys, "argv", ["install.py"]),
                patch.object(installer, "verify_staged_installer"),
                patch.object(installer, "verify_target_parent"),
                patch.object(installer, "load_bundle", return_value=loaded),
                patch.object(
                    installer, "expected_release_manifest", return_value=release_manifest
                ),
                patch.object(
                    installer,
                    "verify_foundation",
                    side_effect=lambda: real_verify_foundation(ownership=False),
                ),
                patch.object(
                    installer,
                    "materialize_candidate",
                    side_effect=AssertionError("wrong unit must fail before materialization"),
                ),
                patch.object(
                    installer,
                    "move_sibling",
                    side_effect=AssertionError("wrong unit must fail before promotion"),
                ),
                patch.object(
                    installer,
                    "checked",
                    side_effect=lambda command: calls.append(tuple(command)),
                ),
                patch.object(installer, "trusted_unit", side_effect=trusted_unit),
                patch.object(
                    Path,
                    "write_bytes",
                    side_effect=AssertionError("wrong unit must not be rewritten"),
                ),
                self.assertRaisesRegex(RuntimeError, "installed_unit_drift"),
            ):
                installer.main()
            self.assertFalse(target.exists())
            self.assertEqual(calls, [])

    def test_candidate_unit_authority_is_exact_and_state_bound(self):
        for installed_unit in (b"base unit", b"arbitrary unit"):
            with self.subTest(installed_unit=installed_unit):
                outcome = self.run_update_case(
                    state="candidate", installed_unit=installed_unit
                )
                self.assertIsInstance(outcome["error"], RuntimeError)
                self.assertRegex(str(outcome["error"]), "installed_unit_drift")
                self.assertEqual(outcome["calls"], [])
                self.assertEqual(outcome["moves"], [])
                self.assertEqual(outcome["target"], "candidate")
                self.assertEqual(outcome["unit"], installed_unit)
                self.assertNotIn("materialize", outcome["events"])

    def test_predecessor_and_absent_unit_authority_are_exact_and_state_bound(self):
        predecessor = self.run_update_case(state="predecessor")
        self.assertIsNone(predecessor["error"])
        self.assertEqual(predecessor["result"], 0)
        for installed_unit in (b"candidate unit", b"arbitrary unit"):
            with self.subTest(installed_unit=installed_unit):
                outcome = self.run_update_case(
                    state="predecessor", installed_unit=installed_unit
                )
                self.assertIsInstance(outcome["error"], RuntimeError)
                self.assertRegex(str(outcome["error"]), "installed_unit_drift")
                self.assertEqual(outcome["calls"], [])
                self.assertEqual(outcome["moves"], [])
                self.assertEqual(outcome["target"], "predecessor")
        fresh = self.run_update_case(state="absent")
        self.assertIsNone(fresh["error"])
        self.assertEqual(fresh["result"], 0)
        self.assertEqual(fresh["target"], "candidate")
        self.assertEqual(fresh["unit"], b"candidate unit")

    def test_unit_metadata_and_exact_bytes_remain_fail_closed(self):
        class Unit:
            def __init__(self, *, symlink=False, uid=0, gid=0, mode=0o644, data=b"unit"):
                self.symlink = symlink
                self.uid = uid
                self.gid = gid
                self.mode = mode
                self.data = data

            def is_symlink(self):
                return self.symlink

            def lstat(self):
                return SimpleNamespace(
                    st_mode=installer.stat.S_IFREG | self.mode,
                    st_uid=self.uid,
                    st_gid=self.gid,
                )

            def read_bytes(self):
                return self.data

        cases = (
            Unit(symlink=True),
            Unit(uid=1),
            Unit(gid=1),
            Unit(mode=0o600),
            Unit(data=b"unexpected"),
        )
        for unit in cases:
            with (
                self.subTest(unit=unit.__dict__),
                patch.object(installer, "UNIT", unit),
                self.assertRaisesRegex(
                    RuntimeError, "unit_.*mismatch|installed_unit_drift"
                ),
            ):
                installer.trusted_unit(b"unit")

    def test_rollback_restores_the_predecessor_and_preserves_failed_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "i044a-v2"
            target.mkdir()
            (target / "candidate").write_text("candidate")
            backup = root / ".i044a-v2-predecessor"
            backup.mkdir()
            (backup / "predecessor").write_text("predecessor")
            unit = root / "novalton-verification.service"
            unit.write_bytes(b"candidate unit")
            failed = root / ".i044a-v2-failed"
            calls = []
            with (
                patch.object(installer, "TARGET", target),
                patch.object(installer, "UNIT", unit),
                patch.object(installer, "reserve_sibling", return_value=failed),
                patch.object(installer, "checked", side_effect=lambda command: calls.append(command)),
                patch.object(installer, "verify_release") as verify,
                patch.object(installer, "verify_unit_bytes"),
            ):
                installer.restore_predecessor(b"predecessor unit", backup)
            self.assertEqual((target / "predecessor").read_text(), "predecessor")
            self.assertEqual((failed / "candidate").read_text(), "candidate")
            self.assertEqual(unit.read_bytes(), b"predecessor unit")
            self.assertEqual(
                calls,
                [
                    ["/usr/bin/systemctl", "stop", "novalton-verification.service"],
                    ["/usr/bin/systemctl", "daemon-reload"],
                    ["/usr/bin/systemctl", "start", "novalton-verification.service"],
                    ["/usr/bin/systemctl", "is-active", "novalton-verification.service"],
                ],
            )
            self.assertEqual(
                verify.call_args_list,
                [
                    ((backup, installer.ALLOWED_PREDECESSOR_RELEASE_DIGEST), {}),
                    ((target, installer.ALLOWED_PREDECESSOR_RELEASE_DIGEST), {}),
                ],
            )

    def test_launcher_executes_only_release_owned_probe(self):
        launcher = (release / "worker/i044a_launch.py").read_text()
        self.assertIn('"/runtime/i044a_probe.py"', launcher)
        self.assertNotIn('"/source/', launcher)
        self.assertNotIn("sys.argv[3]", launcher)

    def test_installed_acceptance_executes_only_the_release_owned_client(self):
        acceptance = (artifacts / "tests/accept_i044a_installed.py").read_text()
        acceptance_tree = ast.parse(acceptance)
        assert_installed_acceptance_authority(self, acceptance)
        try:
            evidence = installer.verify_release(installed)
        except (FileNotFoundError, RuntimeError):
            self.skipTest("candidate release is not installed yet")
        manifest_data = (installed / "manifest.json").read_bytes()
        manifest = json.loads(manifest_data)
        client_path = installed / "client/i044a_client.py"
        client_info = client_path.lstat()
        client_data = client_path.read_bytes()
        self.assertEqual(installer.digest(manifest_data), evidence["installed_manifest_sha256"])
        self.assertFalse(client_path.is_symlink())
        self.assertTrue(client_path.is_file())
        self.assertEqual((client_info.st_uid, client_info.st_gid), (0, 0))
        self.assertEqual(client_info.st_mode & 0o777, 0o444)
        self.assertEqual(
            installer.digest(client_data), manifest["client/i044a_client.py"]
        )
        client = client_data.decode()

        def assigned_values(name: str) -> list[ast.expr]:
            return [
                assignment.value
                for assignment in acceptance_tree.body
                if isinstance(assignment, ast.Assign)
                and len(assignment.targets) == 1
                and isinstance(assignment.targets[0], ast.Name)
                and assignment.targets[0].id == name
            ]

        def top_level_stores(name: str) -> list[ast.Name]:
            return [
                node
                for statement in acceptance_tree.body
                if not isinstance(statement, ast.FunctionDef)
                for node in ast.walk(statement)
                if isinstance(node, ast.Name)
                and isinstance(node.ctx, ast.Store)
                and node.id == name
            ]

        release_values = assigned_values("RELEASE")
        self.assertEqual(len(release_values), 1)
        self.assertEqual(len(top_level_stores("RELEASE")), 1)
        release_value = release_values[0]
        self.assertIsInstance(release_value, ast.Call)
        self.assertIsInstance(release_value.func, ast.Name)
        self.assertEqual(release_value.func.id, "Path")
        self.assertEqual(len(release_value.args), 1)
        self.assertIsInstance(release_value.args[0], ast.Constant)
        self.assertEqual(release_value.args[0].value, str(installed))

        client_values = assigned_values("CLIENT")
        self.assertEqual(len(client_values), 1)
        self.assertEqual(len(top_level_stores("CLIENT")), 1)
        client_value = client_values[0]
        self.assertIsInstance(client_value, ast.Call)
        self.assertIsInstance(client_value.func, ast.Name)
        self.assertEqual(client_value.func.id, "str")
        self.assertEqual(len(client_value.args), 1)
        self.assertIsInstance(client_value.args[0], ast.BinOp)
        self.assertIsInstance(client_value.args[0].op, ast.Div)
        self.assertIsInstance(client_value.args[0].left, ast.Name)
        self.assertEqual(client_value.args[0].left.id, "RELEASE")
        self.assertIsInstance(client_value.args[0].right, ast.Constant)
        self.assertEqual(client_value.args[0].right.value, "client/i044a_client.py")

        client_functions = [
            function
            for function in acceptance_tree.body
            if isinstance(function, ast.FunctionDef) and function.name == "client"
        ]
        self.assertEqual(len(client_functions), 1)
        client_function = client_functions[0]
        self.assertFalse(
            any(
                isinstance(node, ast.Name)
                and isinstance(node.ctx, ast.Store)
                and node.id == "CLIENT"
                for node in ast.walk(client_function)
            )
        )
        invocations = [
            call
            for call in ast.walk(client_function)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "subprocess"
            and call.func.attr == "check_output"
        ]
        self.assertEqual(len(invocations), 1)
        invocation = invocations[0]
        self.assertFalse(any(keyword.arg == "shell" for keyword in invocation.keywords))
        self.assertGreaterEqual(len(invocation.args), 1)
        self.assertIsInstance(invocation.args[0], ast.List)
        argv = invocation.args[0].elts
        self.assertEqual(len(argv), 8)
        self.assertIsInstance(argv[4], ast.Name)
        self.assertEqual(argv[4].id, "CLIENT")

        main_functions = [
            function
            for function in acceptance_tree.body
            if isinstance(function, ast.FunctionDef) and function.name == "main"
        ]
        self.assertEqual(len(main_functions), 1)
        self.assertTrue(
            any(
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "client"
                for call in ast.walk(main_functions[0])
            )
        )

        self.assertIn("checkout adapter must remain data", acceptance)
        self.assertNotIn("importlib", acceptance)
        self.assertNotIn("spec_from_file_location", acceptance)
        self.assertNotIn('"-c"', acceptance)
        self.assertNotIn("novalton_api", client)
        self.assertNotIn("spec_from_file_location", client)

    def test_installed_acceptance_process_authority_is_closed_world(self):
        acceptance = (artifacts / "tests/accept_i044a_installed.py").read_text()
        assert_installed_acceptance_authority(self, acceptance)

    def test_installed_acceptance_process_authority_mutations_fail_closed(self):
        acceptance = (artifacts / "tests/accept_i044a_installed.py").read_text()

        acceptance_tree = ast.parse(acceptance)
        client_function = next(
            node
            for node in acceptance_tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "client"
        )
        client_invocation = next(
            node
            for node in ast.walk(client_function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "subprocess"
            and node.func.attr == "check_output"
        )
        client_assignment = next(
            node
            for node in client_function.body
            if isinstance(node, ast.Assign) and client_invocation in ast.walk(node)
        )
        line_offsets = []
        offset = 0
        for line in acceptance.splitlines(keepends=True):
            line_offsets.append(offset)
            offset += len(line)

        def replace_client_assignment(replacement: str) -> str:
            start = line_offsets[client_assignment.lineno - 1] + client_assignment.col_offset
            end = line_offsets[client_assignment.end_lineno - 1] + client_assignment.end_col_offset
            return acceptance[:start] + replacement + acceptance[end:]

        mutations = {
            "terra_dead_call_and_live_alias": replace_client_assignment(
                'if False:\n'
                '        subprocess.check_output([PYTHON, "-I", "-S", "-B", CLIENT])\n'
                '    runner = subprocess.check_output\n'
                '    output = runner([PYTHON, "-I", "-S", "-B", "/tmp/not-client.py"])'
            ),
            "check_output_alias": acceptance.replace(
                '    account = pwd.getpwnam("novalton-verify-client")\n',
                '    runner = subprocess.check_output\n'
                '    runner([PYTHON, "-I", "-S", "-B", CLIENT])\n'
                '    account = pwd.getpwnam("novalton-verify-client")\n',
                1,
            ),
            "wrong_direct_client": acceptance.replace(
                "            CLIENT,\n",
                '            "/tmp/not-client.py",\n',
                1,
            ),
            "dynamic_getattr": acceptance.replace(
                '    account = pwd.getpwnam("novalton-verify-client")\n',
                '    runner = getattr(subprocess, "check_output")\n'
                '    account = pwd.getpwnam("novalton-verify-client")\n',
                1,
            ),
            "alternate_subprocess_api": acceptance.replace(
                '    account = pwd.getpwnam("novalton-verify-client")\n',
                '    subprocess.run([PYTHON, CLIENT])\n'
                '    account = pwd.getpwnam("novalton-verify-client")\n',
                1,
            ),
            "local_client_rebinding": acceptance.replace(
                '    account = pwd.getpwnam("novalton-verify-client")\n',
                '    CLIENT = "/tmp/not-client.py"\n'
                '    account = pwd.getpwnam("novalton-verify-client")\n',
                1,
            ),
            "second_competing_call": acceptance.replace(
                '    account = pwd.getpwnam("novalton-verify-client")\n',
                '    subprocess.check_output([PYTHON, "/tmp/not-client.py"])\n'
                '    account = pwd.getpwnam("novalton-verify-client")\n',
                1,
            ),
            "shell_execution": acceptance.replace(
                '    account = pwd.getpwnam("novalton-verify-client")\n',
                '    os.system("/tmp/not-client.py")\n'
                '    account = pwd.getpwnam("novalton-verify-client")\n',
                1,
            ),
            "subprocess_rebinding": acceptance.replace(
                '    account = pwd.getpwnam("novalton-verify-client")\n',
                '    subprocess = object()\n'
                '    account = pwd.getpwnam("novalton-verify-client")\n',
                1,
            ),
            "dynamic_exec": acceptance.replace(
                '    account = pwd.getpwnam("novalton-verify-client")\n',
                '    exec("pass")\n'
                '    account = pwd.getpwnam("novalton-verify-client")\n',
                1,
            ),
            "dynamic_eval": acceptance.replace(
                '    account = pwd.getpwnam("novalton-verify-client")\n',
                '    eval("1 + 1")\n'
                '    account = pwd.getpwnam("novalton-verify-client")\n',
                1,
            ),
            "aliased_execution_import": acceptance.replace(
                "import hashlib\n",
                "import hashlib\nimport os as execution_module\n",
                1,
            ),
            "I_builtins_attribute_import": acceptance.replace(
                '    account = pwd.getpwnam("novalton-verify-client")\n',
                '    __builtins__.__import__("subprocess").run(["true"])\n'
                '    account = pwd.getpwnam("novalton-verify-client")\n',
                1,
            ),
            "J_builtins_subscript_import": acceptance.replace(
                '    account = pwd.getpwnam("novalton-verify-client")\n',
                '    __builtins__["__import__"]("os").system("true")\n'
                '    account = pwd.getpwnam("novalton-verify-client")\n',
                1,
            ),
            "K_builtins_exec": acceptance.replace(
                '    account = pwd.getpwnam("novalton-verify-client")\n',
                '    __builtins__.exec("pass")\n'
                '    account = pwd.getpwnam("novalton-verify-client")\n',
                1,
            ),
            "L_builtins_globals_client_mutation": acceptance.replace(
                '    account = pwd.getpwnam("novalton-verify-client")\n',
                '    __builtins__.globals()["CLIENT"] = "/tmp/not-client.py"\n'
                '    account = pwd.getpwnam("novalton-verify-client")\n',
                1,
            ),
            "M_unreviewed_ctl_tuple": acceptance.replace(
                '    account = pwd.getpwnam("novalton-verify-client")\n',
                '    ctl("start", "unreviewed.service")\n'
                '    account = pwd.getpwnam("novalton-verify-client")\n',
                1,
            ),
            "N_unknown_import_and_authority_call": acceptance.replace(
                "import hashlib\n",
                "import hashlib\nimport socket\n",
                1,
            ).replace(
                '    account = pwd.getpwnam("novalton-verify-client")\n',
                '    socket.create_connection(("127.0.0.1", 1))\n'
                '    account = pwd.getpwnam("novalton-verify-client")\n',
                1,
            ),
            "O_dynamic_callable": acceptance.replace(
                '    account = pwd.getpwnam("novalton-verify-client")\n',
                '    f = some_object.method\n'
                '    f("unexpected")\n'
                '    account = pwd.getpwnam("novalton-verify-client")\n',
                1,
            ),
            "P_unexpected_helper_target": acceptance.replace(
                "def ctl(*arguments: str) -> str:\n",
                "def unexpected_helper() -> None:\n"
                "    print('unexpected')\n\n\n"
                "def ctl(*arguments: str) -> str:\n",
                1,
            ).replace(
                '    account = pwd.getpwnam("novalton-verify-client")\n',
                '    unexpected_helper()\n'
                '    account = pwd.getpwnam("novalton-verify-client")\n',
                1,
            ),
        }
        for name, mutated in mutations.items():
            self.assertNotEqual(mutated, acceptance)
            with self.subTest(name=name), self.assertRaises(AssertionError):
                assert_installed_acceptance_authority(self, mutated)

    def test_installed_acceptance_control_call_shapes_fail_closed(self):
        acceptance = (artifacts / "tests/accept_i044a_installed.py").read_text()
        mutations = {
            "systemctl_is_active": acceptance.replace(
                'ctl("is-active", UNIT)', 'ctl("is-failed", UNIT)', 1
            ),
            "systemctl_main_pid": acceptance.replace(
                'ctl("show", UNIT, "-p", "MainPID", "--value")',
                'ctl("show", UNIT, "-p", "ExecMainPID", "--value")',
                1,
            ),
            "systemctl_control_group": acceptance.replace(
                'ctl("show", UNIT, "-p", "ControlGroup", "--value")',
                'ctl("show", UNIT, "-p", "FragmentPath", "--value")',
                1,
            ),
            "systemctl_kill": acceptance.replace(
                'ctl("kill", "--kill-whom=main", "--signal=KILL", UNIT)',
                'ctl("kill", "--kill-whom=all", "--signal=KILL", UNIT)',
                1,
            ),
            "journalctl_arguments": acceptance.replace(
                '["/usr/bin/journalctl", "-u", UNIT, "--since", "-3min",',
                '["/usr/bin/journalctl", "-u", UNIT, "--since", "-30min",',
                1,
            ),
            "journalctl_bare_executable": acceptance.replace(
                '["/usr/bin/journalctl", "-u", UNIT,',
                '["journalctl", "-u", UNIT,',
                1,
            ),
            "journalctl_tmp_executable": acceptance.replace(
                '["/usr/bin/journalctl", "-u", UNIT,',
                '["/tmp/journalctl", "-u", UNIT,',
                1,
            ),
            "journalctl_variable_executable": acceptance.replace(
                '    logs = subprocess.check_output(["/usr/bin/journalctl",',
                '    journal_executable = "/usr/bin/journalctl"\n'
                "    logs = subprocess.check_output([journal_executable,",
                1,
            ),
            "journalctl_which_lookup": acceptance.replace(
                "import select\n", "import select\nimport shutil\n", 1
            ).replace(
                '["/usr/bin/journalctl", "-u", UNIT,',
                '[shutil.which("journalctl"), "-u", UNIT,',
                1,
            ),
            "journalctl_path_derived": acceptance.replace(
                '["/usr/bin/journalctl", "-u", UNIT,',
                '[os.environ["PATH"] + "/journalctl", "-u", UNIT,',
                1,
            ),
            "journalctl_second_call": acceptance.replace(
                '    logs = subprocess.check_output(["/usr/bin/journalctl",',
                "    subprocess.check_output("
                '["/usr/bin/journalctl", "--list-boots"], text=True)\n'
                '    logs = subprocess.check_output(["/usr/bin/journalctl",',
                1,
            ),
            "journalctl_alternate_process_api": acceptance.replace(
                '    logs = subprocess.check_output(["/usr/bin/journalctl",',
                "    subprocess.run("
                '["/usr/bin/journalctl", "-u", UNIT], check=True)\n'
                '    logs = subprocess.check_output(["/usr/bin/journalctl",',
                1,
            ),
        }
        for name, mutated in mutations.items():
            self.assertNotEqual(mutated, acceptance)
            with self.subTest(name=name), self.assertRaises(AssertionError):
                assert_installed_acceptance_authority(self, mutated)

    def test_installed_kernel_seccomp_proof_is_manifest_pinned_and_has_no_fallback(
        self,
    ):
        self.assertIn("tests/test_i044a_seccomp_kernel.py", installer.AUXILIARY)
        proof = (artifacts / "tests/test_i044a_seccomp_kernel.py").read_text()
        self.assertIn('RELEASE / "seccomp.bpf"', proof)
        self.assertIn('RELEASE / "manifest.json"', proof)
        self.assertIn('RELEASE / "release-metadata.json"', proof)
        self.assertIn('metadata.get("installed_manifest_sha256")', proof)
        self.assertIn("filters_before + 1", proof)
        self.assertIn("ordinary_arguments", proof)
        self.assertIn("clone3_once(ordinary_arguments)", proof)
        self.assertIn("load_exact_policy(policy)", proof)
        self.assertIn("stable_process_state()", proof)
        self.assertIn("clone_once(0)", proof)
        self.assertIn("fork_once()", proof)
        self.assertNotIn("ARTIFACTS", proof)
        self.assertNotIn("importlib", proof)
        self.assertNotIn("seccomp_policy()", proof)

    def test_staging_seccomp_proof_is_separate_from_installed_acceptance(self):
        staging = (artifacts / "tests/test_i044a_seccomp_staging.py").read_text()
        self.assertIn('ARTIFACTS / "install.py"', staging)
        self.assertIn("installer.seccomp_policy()", staging)
        self.assertIn("tests/test_i044a_seccomp_staging.py", installer.AUXILIARY)


if __name__ == "__main__":
    unittest.main()
