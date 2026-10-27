"""Disposable Chrome/WebDriver acceptance against real Next, FastAPI and PostgreSQL.

Uses ChromeDriver bundled with the GitHub runner, without a browser download.
Only synthetic credentials and project data are created. No agent is launched.
"""

import asyncio
import base64
import http.client
import json
import os
import secrets
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socket import socket
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[3]
ARTIFACTS = (
    Path(os.environ.get("RUNNER_TEMP", tempfile.gettempdir())) / "novalton-graphical"
)
ARTIFACTS.mkdir(parents=True, exist_ok=True)
LOGIN = "graphical-owner"
PASSWORD = os.environ["NOVALTON_E2E_PASSWORD"]


def free_port():
    with socket() as candidate:
        candidate.bind(("127.0.0.1", 0))
        return candidate.getsockname()[1]


def await_http(url, seconds=30):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status < 500:
                    return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.2)
    raise AssertionError(
        f"Disposable server did not start: {urllib.parse.urlsplit(url).path}"
    )


def webdriver(port, method, path, payload=None):
    body = (
        json.dumps({} if payload is None else payload).encode()
        if method == "POST"
        else None
    )
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=35) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        detail = json.load(error)
        raise AssertionError(
            f"WebDriver {method} failed: {detail['value'].get('error')}"
        ) from None
    if isinstance(result.get("value"), dict) and result["value"].get("error"):
        raise AssertionError(f"WebDriver failed: {result['value']['error']}")
    return result["value"]


class Browser:
    def __init__(self, port, session):
        self.port = port
        self.path = f"/session/{session}"

    def call(self, method, suffix, payload=None):
        return webdriver(self.port, method, self.path + suffix, payload)

    def navigate(self, url):
        self.call("POST", "/url", {"url": url})

    def script(self, script, *args):
        return self.call("POST", "/execute/sync", {"script": script, "args": args})

    def find(self, selector):
        return self.call(
            "POST", "/element", {"using": "css selector", "value": selector}
        )["element-6066-11e4-a52e-4f735466cecf"]

    def type(self, selector, value):
        element = self.find(selector)
        self.call("POST", f"/element/{element}/value", {"text": value})

    def click(self, selector):
        element = self.find(selector)
        self.call("POST", f"/element/{element}/click")

    def click_text(self, label):
        clicked = self.script(
            "const button = [...document.querySelectorAll('button')].find(el => "
            "el.textContent.trim() === arguments[0]); if (!button || button.disabled) "
            "return false; button.click(); return true;",
            label,
        )
        assert clicked, f"Button unavailable: {label}"

    def wait(self, predicate, label, seconds=25):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            try:
                if self.script(predicate):
                    return
            except (AssertionError, urllib.error.URLError):
                pass
            time.sleep(0.2)
        raise AssertionError(f"Browser state timed out: {label}")

    def screenshot(self, name):
        data = self.call("GET", "/screenshot")
        (ARTIFACTS / name).write_bytes(base64.b64decode(data))


def proxy_handler(next_port):
    class Proxy(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            self.forward()

        def do_POST(self):
            self.forward()

        def do_PUT(self):
            self.forward()

        def do_PATCH(self):
            self.forward()

        def forward(self):
            size = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(size) if size else None
            upstream = http.client.HTTPConnection("127.0.0.1", next_port, timeout=20)
            headers_sent = False
            headers = dict(self.headers)
            headers.update(
                {
                    "Host": self.headers["Host"],
                    "X-Forwarded-Proto": "https",
                    "X-Forwarded-Host": self.headers["Host"],
                    "Connection": "close",
                }
            )
            try:
                upstream.request(self.command, self.path, body=body, headers=headers)
                response = upstream.getresponse()
                payload = response.read()
                self.send_response(response.status)
                headers_sent = True
                for name, value in response.getheaders():
                    if name.lower() not in {
                        "content-length",
                        "transfer-encoding",
                        "connection",
                    }:
                        self.send_header(name, value)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except (OSError, TimeoutError):
                # Chrome cancels pending asset requests during navigation. Once
                # headers were sent, writing a second HTTP response is invalid.
                if not headers_sent:
                    try:
                        self.send_error(502)
                    except OSError:
                        pass
            finally:
                upstream.close()

        def log_message(self, _format, *_args):
            pass  # URLs can include project identifiers; keep CI logs minimal.

    return Proxy


def provision_second_identity():
    """A separate tenant and local human on the disposable test database only."""
    from datetime import UTC, datetime

    from novalton_api.core.config import get_settings
    from novalton_api.core.database import Database, verify_database_identity
    from novalton_api.modules.durable_dispatch.identity import (
        HumanOperator,
        TenantOperatorMembership,
        WorkspaceOperatorPermission,
    )
    from novalton_api.modules.local_auth.models import LocalCredential
    from novalton_api.modules.local_auth.service import hash_password
    from novalton_api.modules.tenants.models import Tenant
    from novalton_api.modules.workspaces.models import Workspace

    settings = get_settings()
    assert settings.environment == "test"
    login = "graphical-other"
    password = secrets.token_urlsafe(32)

    async def create():
        await verify_database_identity(settings)
        db = Database.from_settings(settings)
        try:
            async with db.session_factory.begin() as session:
                tenant = Tenant(
                    id=uuid4(), name="Other test tenant", slug="graphical-other"
                )
                session.add(tenant)
                await session.flush()
                workspace = Workspace(
                    id=uuid4(),
                    tenant_id=tenant.id,
                    name="Other test workspace",
                    slug="graphical-other",
                )
                person = HumanOperator(label=login, active=True)
                session.add_all([workspace, person])
                await session.flush()
                session.add_all(
                    [
                        LocalCredential(
                            user_id=person.id,
                            login=login,
                            password_hash=hash_password(password),
                            changed_at=datetime.now(UTC),
                        ),
                        TenantOperatorMembership(
                            user_id=person.id,
                            tenant_id=tenant.id,
                            role="OWNER",
                            active=True,
                        ),
                    ]
                )
                for permission in ("workspace.read", "workspace.write"):
                    session.add(
                        WorkspaceOperatorPermission(
                            user_id=person.id,
                            tenant_id=tenant.id,
                            workspace_id=workspace.id,
                            permission=permission,
                            active=True,
                        )
                    )
                return str(tenant.id), str(workspace.id)
        finally:
            await db.dispose()

    return (*asyncio.run(create()), login, password)


def change_second_authority(
    tenant_id, workspace_id, login, *, grant_active=None, revoke=False
):
    from datetime import UTC, datetime

    from novalton_api.core.config import get_settings
    from novalton_api.core.database import Database, verify_database_identity
    from novalton_api.modules.durable_dispatch.identity import (
        WorkspaceOperatorPermission,
    )
    from novalton_api.modules.local_auth.models import LocalCredential, LocalSession
    from sqlalchemy import select, update

    async def change():
        settings = get_settings()
        assert settings.environment == "test"
        await verify_database_identity(settings)
        db = Database.from_settings(settings)
        try:
            async with db.session_factory.begin() as session:
                person = await session.scalar(
                    select(LocalCredential).where(LocalCredential.login == login)
                )
                assert person is not None
                if grant_active is not None:
                    result = await session.execute(
                        update(WorkspaceOperatorPermission)
                        .where(
                            WorkspaceOperatorPermission.user_id == person.user_id,
                            WorkspaceOperatorPermission.tenant_id == UUID(tenant_id),
                            WorkspaceOperatorPermission.workspace_id
                            == UUID(workspace_id),
                            WorkspaceOperatorPermission.permission == "workspace.read",
                        )
                        .values(
                            active=grant_active,
                            revoked_at=None if grant_active else datetime.now(UTC),
                        )
                    )
                    assert result.rowcount == 1
                if revoke:
                    result = await session.execute(
                        update(LocalSession)
                        .where(
                            LocalSession.user_id == person.user_id,
                            LocalSession.revoked_at.is_(None),
                        )
                        .values(revoked_at=datetime.now(UTC))
                    )
                    assert result.rowcount >= 1
        finally:
            await db.dispose()

    asyncio.run(change())


def launch_targets(conversation_id):
    """Resolve actual disposable IDs to test the launch boundary, not random misses."""
    from novalton_api.core.config import get_settings
    from novalton_api.core.database import Database, verify_database_identity
    from novalton_api.modules.cadrage.models import CadrageCompilation, CadragePlan
    from sqlalchemy import select

    async def read():
        settings = get_settings()
        assert settings.environment == "test"
        await verify_database_identity(settings)
        db = Database.from_settings(settings)
        try:
            async with db.session_factory() as session:
                plan = await session.scalar(
                    select(CadragePlan).where(
                        CadragePlan.conversation_id == UUID(conversation_id)
                    )
                )
                assert plan is not None and plan.status == "APPROVED"
                proposal = await session.scalar(
                    select(CadrageCompilation).where(
                        CadrageCompilation.plan_id == plan.id
                    )
                )
                assert proposal is not None and proposal.status == "BLOCKED"
                return str(plan.id), str(proposal.id)
        finally:
            await db.dispose()

    return asyncio.run(read())


def grant_disposable_launch_permissions(tenant_id, workspace_id):
    """Make the obsolete plan, rather than missing grants, decide the denial."""
    from novalton_api.core.config import get_settings
    from novalton_api.core.database import Database, verify_database_identity
    from novalton_api.modules.durable_dispatch.identity import (
        WorkspaceOperatorPermission,
    )
    from novalton_api.modules.local_auth.models import LocalCredential
    from sqlalchemy import select

    async def grant():
        settings = get_settings()
        assert settings.environment == "test"
        await verify_database_identity(settings)
        db = Database.from_settings(settings)
        try:
            async with db.session_factory.begin() as session:
                user_id = await session.scalar(
                    select(LocalCredential.user_id).where(
                        LocalCredential.login == LOGIN
                    )
                )
                assert user_id is not None
                for permission in ("activation.configure", "dispatch.enqueue"):
                    existing = await session.scalar(
                        select(WorkspaceOperatorPermission).where(
                            WorkspaceOperatorPermission.user_id == user_id,
                            WorkspaceOperatorPermission.tenant_id == UUID(tenant_id),
                            WorkspaceOperatorPermission.workspace_id
                            == UUID(workspace_id),
                            WorkspaceOperatorPermission.permission == permission,
                        )
                    )
                    if existing is None:
                        session.add(
                            WorkspaceOperatorPermission(
                                user_id=user_id,
                                tenant_id=UUID(tenant_id),
                                workspace_id=UUID(workspace_id),
                                permission=permission,
                                active=True,
                            )
                        )
        finally:
            await db.dispose()

    asyncio.run(grant())


def direct_api(token, tenant, workspace, suffix, *, method="GET", body=None):
    request = urllib.request.Request(
        f"http://127.0.0.1:8000/api/v1/tenants/{tenant}/workspaces/{workspace}/{suffix}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def run(browser, origin, second):
    browser.navigate(origin + "/projects")
    browser.wait(
        "return document.body.innerText.includes('Connexion requise')",
        "anonymous denial",
    )
    browser.navigate(origin + "/login")
    browser.type("input[name=login]", LOGIN)
    browser.type("input[name=password]", PASSWORD)
    browser.click("form.workspace-form button")
    browser.wait(
        "return location.pathname === '/projects' && !!document.querySelector('form.entry-form')",
        "local login",
    )
    browser.type("form.entry-form input[maxlength='200']", "Projet graphique jetable")
    browser.type("form.entry-form input[pattern]", "graphical-project")
    browser.click("form.entry-form button")
    browser.wait(
        "return location.pathname === '/tasks' && new URLSearchParams(location.search).has('project')",
        "project creation",
    )
    project = browser.script(
        "return new URLSearchParams(location.search).get('project')"
    )
    browser.type("form.entry-form input[maxlength='200']", "Tâche graphique jetable")
    browser.click("form.entry-form button")
    browser.wait(
        "return new URLSearchParams(location.search).has('task')", "task creation"
    )
    task = browser.script("return new URLSearchParams(location.search).get('task')")

    browser.navigate(f"{origin}/projects/{project}/chat")
    browser.wait("return !!document.querySelector('#chat-title')", "project chat")
    browser.type("#chat-title", "Site vitrine jetable")
    browser.click(".chat-list form button")
    browser.wait(
        "return !!document.querySelector('#chat-content') && new URLSearchParams(location.search).has('conversation')",
        "conversation creation",
    )
    conversation = browser.script(
        "return new URLSearchParams(location.search).get('conversation')"
    )
    browser.type("#chat-content", "Je veux créer un site pour mon entreprise.")
    browser.click(".chat-thread > form.workspace-form button")
    browser.wait(
        "return document.body.innerText.includes('Je veux créer un site pour mon entreprise.')",
        "persisted message",
    )
    browser.type("#spec-summary", "Site vitrine pour une entreprise")
    browser.click_text("Ajouter une information")
    browser.type("#spec-value-0", "Présenter les services")
    browser.script(
        "const element = document.querySelector('select[aria-label=\"État de detail_1\"]'); "
        "element.value='CONFIRMED'; element.dispatchEvent(new Event('change', {bubbles:true}));"
    )
    browser.click_text("Enregistrer une nouvelle version")
    browser.wait(
        "return !!document.querySelector('#spec-version option[value=\"1\"]')",
        "saved specification",
    )
    browser.click_text("Préparer un brouillon depuis la version 1")
    browser.wait(
        "return document.body.innerText.includes('état : DRAFT')", "draft plan"
    )
    browser.click_text("Soumettre à la revue")
    browser.wait(
        "return document.body.innerText.includes('état : READY_FOR_REVIEW')", "review"
    )
    browser.click_text("Approuver ce plan")
    browser.wait(
        "return document.body.innerText.includes('état : APPROVED')", "human approval"
    )
    # On the 12C branch, preparation must fail closed for this generic site plan.
    if browser.script("return !!document.querySelector('#execution-task')"):
        browser.wait(
            f"return !!document.querySelector('#execution-task option[value=\"{task}\"]')",
            "task available for compilation",
        )
        browser.script(
            "const element=document.querySelector('#execution-task'); "
            "element.value=arguments[0]; element.dispatchEvent(new Event('change',{bubbles:true}));",
            task,
        )
        browser.click_text("Préparer l’exécution")
        browser.wait(
            "return document.body.innerText.includes('Proposition : BLOCKED')",
            "generic plan refused compilation",
        )
        assert not browser.script(
            "return [...document.querySelectorAll('button')].some(button => "
            "button.textContent.includes('Lancer le test autorisé') && !button.disabled)"
        ), "blocked proposal must not expose an executable launch"
    plan_id, compilation_id = launch_targets(conversation)
    launch_path = (
        f"projects/{project}/conversations/{conversation}/plans/{plan_id}/"
        f"compilations/{compilation_id}/launch-authorizations"
    )
    # The blocked proposal cannot be turned into an authority by direct HTTP
    # even when the owner supplies valid credentials and a fresh request.
    primary_tenant = os.environ.get(
        "NOVALTON_TENANT_ID", "89cfc055-366e-5bcb-b65f-4f367185bf6d"
    )
    primary_workspace = os.environ.get(
        "NOVALTON_WORKSPACE_ID", "b640b64f-8e55-53e8-a5b2-3beff9d5af82"
    )
    grant_disposable_launch_permissions(primary_tenant, primary_workspace)
    owner_login = urllib.request.Request(
        "http://127.0.0.1:8000/api/v1/local-auth/login",
        data=json.dumps({"login": LOGIN, "password": PASSWORD}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(owner_login, timeout=10) as response:
        owner_token = json.load(response)["token"]
    authorization_body = {
        "confirmation": "AUTHORIZE_DISPOSABLE_TEST_LAUNCH",
        "request_id": str(uuid4()),
        "environment": "DISPOSABLE_TEST",
        "provider_id": "local",
        "model_id": "simulated",
        "max_model_calls": 3,
        "max_duration_seconds": 180,
        "current_password": PASSWORD,
    }
    assert (
        direct_api(
            owner_token,
            primary_tenant,
            primary_workspace,
            launch_path,
            method="POST",
            body=authorization_body,
        )
        == 409
    )
    assert direct_api(
        owner_token,
        primary_tenant,
        primary_workspace,
        f"{launch_path}/{uuid4()}/dispatch",
        method="POST",
        body={
            "confirmation": "ENQUEUE_DISPOSABLE_TEST_WORKFLOW",
            "request_id": str(uuid4()),
            "current_password": PASSWORD,
        },
    ) in (403, 404, 409)
    browser.navigate(f"{origin}/projects/{project}/chat?conversation={conversation}")
    browser.wait(
        "return document.body.innerText.includes('état : APPROVED') && "
        "document.body.innerText.includes('Je veux créer un site pour mon entreprise.')",
        "reload history",
    )

    browser.navigate(origin + "/settings")
    browser.wait(
        "return document.body.innerText.includes('Clés personnelles')",
        "provider settings",
    )
    for theme in ("Sombre", "Clair"):
        browser.click_text(theme)
        for width in (1440, 768, 390, 320):
            browser.call(
                "POST",
                "/goog/cdp/execute",
                {
                    "cmd": "Emulation.setDeviceMetricsOverride",
                    "params": {
                        "width": width,
                        "height": 900,
                        "deviceScaleFactor": 1,
                        "mobile": width < 768,
                    },
                },
            )
            browser.navigate(
                f"{origin}/projects/{project}/chat?conversation={conversation}"
            )
            browser.wait(
                "return document.body.innerText.includes('état : APPROVED') && "
                "document.body.innerText.includes('Je veux créer un site pour mon entreprise.') && "
                "!document.body.innerText.includes('Chargement des conversations')",
                "persisted responsive chat and plan",
            )
            assert not browser.script(
                "return [...document.querySelectorAll('button')].some(button => "
                "button.textContent.includes('Lancer le test autorisé') && !button.disabled)"
            ), "blocked launch became actionable after responsive reload"
            metrics = browser.script(
                "return {width: innerWidth, page: document.documentElement.scrollWidth, "
                "theme: document.documentElement.dataset.theme}"
            )
            if metrics["width"] != width or metrics["page"] > width + 2:
                metrics["overflowing"] = browser.script(
                    "return [...document.querySelectorAll('*')].filter(e => "
                    "e.getBoundingClientRect().right > innerWidth + 2).slice(0, 12)"
                    ".map(e => ({tag:e.tagName, className:String(e.className).slice(0, 90), "
                    "right:Math.round(e.getBoundingClientRect().right)}))"
                )
                raise AssertionError(metrics)
            assert metrics["theme"] == ("light" if theme == "Clair" else "dark"), (
                metrics
            )
            if width <= 680:
                navigation_height = browser.script(
                    "return Math.round(document.querySelector('.primary-nav')"
                    ".getBoundingClientRect().height)"
                )
                assert navigation_height <= 80, {
                    "width": width,
                    "nav": navigation_height,
                }
            browser.screenshot(f"chat-{theme.lower()}-{width}.png")
            browser.navigate(origin + "/settings")
            browser.wait(
                "return document.body.innerText.includes('Clés personnelles')",
                "return to settings",
            )
    # A new specification supersedes the approved snapshot. The direct API
    # must reject the exact old plan and proposal IDs after this mutation.
    assert (
        direct_api(
            owner_token,
            primary_tenant,
            primary_workspace,
            f"projects/{project}/conversations/{conversation}/specifications",
            method="PUT",
            body={"expected_version": 1, "summary": "Version obsolète", "items": []},
        )
        == 200
    )
    assert (
        direct_api(
            owner_token,
            primary_tenant,
            primary_workspace,
            launch_path,
            method="POST",
            body=authorization_body | {"request_id": str(uuid4())},
        )
        == 409
    )
    browser.navigate(f"{origin}/projects/{project}/chat?conversation={conversation}")
    browser.wait(
        "return document.body.innerText.includes('état : SUPERSEDED')",
        "obsolete plan displayed without launch action",
    )
    assert not browser.script(
        "return [...document.querySelectorAll('button')].some(button => "
        "button.textContent.includes('Lancer le test autorisé') && !button.disabled)"
    )
    browser.click_text("Se déconnecter")
    browser.wait("return location.pathname === '/login'", "local logout")
    browser.navigate(origin + "/projects")
    browser.wait(
        "return document.body.innerText.includes('Connexion requise')",
        "session denied after logout",
    )
    tenant2, workspace2, login2, password2 = second
    browser.navigate(origin + "/login")
    browser.type("input[name=login]", login2)
    browser.type("input[name=password]", password2)
    browser.click("form.workspace-form button")
    browser.wait(
        "return location.pathname === '/projects' && "
        "document.body.innerText.includes('Aucun projet')",
        "other tenant empty project list",
    )
    browser.navigate(f"{origin}/projects/{project}/chat?conversation={conversation}")
    browser.wait(
        "return document.body.innerText.includes('Ressource introuvable ou inaccessible.')",
        "foreign project denied in browser",
    )
    assert not browser.script(
        "return document.body.innerText.includes('Je veux créer un site pour mon entreprise.')"
    ), "foreign conversation was displayed"
    # Independent backend boundary: the second identity must not read or mutate
    # the first tenant's plan, compilation or financial policy via direct API.
    request = urllib.request.Request(
        "http://127.0.0.1:8000/api/v1/local-auth/login",
        data=json.dumps({"login": login2, "password": password2}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        token2 = json.load(response)["token"]
    for method, suffix, body in (
        ("GET", f"projects/{project}", None),
        ("GET", f"projects/{project}/conversations/{conversation}/plans", None),
        ("GET", f"projects/{project}/financial-authorizations", None),
        ("POST", f"projects/{project}/conversations", {"title": "foreign mutation"}),
        ("GET", f"{launch_path}/{uuid4()}/dispatch", None),
        ("POST", launch_path, authorization_body),
        (
            "POST",
            f"{launch_path}/{uuid4()}/dispatch",
            {
                "confirmation": "ENQUEUE_DISPOSABLE_TEST_WORKFLOW",
                "request_id": str(uuid4()),
                "current_password": password2,
            },
        ),
    ):
        url = (
            f"http://127.0.0.1:8000/api/v1/tenants/{tenant2}/workspaces/{workspace2}/"
            + suffix
        )
        req = urllib.request.Request(
            url,
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={
                "Authorization": f"Bearer {token2}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                raise AssertionError(
                    f"Foreign resource allowed: {method} {response.status}"
                )
        except urllib.error.HTTPError as error:
            assert error.code in (403, 404), (method, error.code)
    foreign_vault = urllib.request.Request(
        f"http://127.0.0.1:8000/api/v1/tenants/{primary_tenant}/"
        f"workspaces/{primary_workspace}/provider-keys",
        headers={"Authorization": f"Bearer {token2}"},
    )
    try:
        with urllib.request.urlopen(foreign_vault, timeout=10) as response:
            raise AssertionError(f"Foreign BYOK allowed: {response.status}")
    except urllib.error.HTTPError as error:
        assert error.code == 403, error.code
    browser.navigate(origin + "/settings")
    browser.wait(
        "return document.body.innerText.includes('Clés personnelles')",
        "other tenant settings",
    )
    change_second_authority(tenant2, workspace2, login2, grant_active=False)
    browser.navigate(origin + "/projects")
    browser.wait(
        "return document.body.innerText.includes('Vous n’avez pas accès à cet espace.')",
        "grant removed while page open",
    )
    change_second_authority(tenant2, workspace2, login2, grant_active=True)
    browser.navigate(origin + "/projects")
    browser.wait(
        "return document.body.innerText.includes('Aucun projet')", "grant restored"
    )
    change_second_authority(tenant2, workspace2, login2, revoke=True)
    browser.navigate(origin + "/projects")
    browser.wait(
        "return document.body.innerText.includes('Connexion requise')",
        "revoked session denied after page reload",
    )
    revoked_request = urllib.request.Request(
        f"http://127.0.0.1:8000/api/v1/tenants/{tenant2}/workspaces/{workspace2}/projects",
        headers={"Authorization": f"Bearer {token2}"},
    )
    try:
        with urllib.request.urlopen(revoked_request, timeout=10) as response:
            raise AssertionError(f"Revoked session allowed: {response.status}")
    except urllib.error.HTTPError as error:
        assert error.code == 401, error.code
    assert (
        direct_api(
            token2,
            tenant2,
            workspace2,
            f"{launch_path}/{uuid4()}/dispatch",
            method="POST",
            body={
                "confirmation": "ENQUEUE_DISPOSABLE_TEST_WORKFLOW",
                "request_id": str(uuid4()),
                "current_password": password2,
            },
        )
        == 401
    )
    print(
        json.dumps(
            {
                "browser": "Chrome headless",
                "identity": "local disposable owner",
                "isolation": "real launch IDs denied to second tenant; grant and session revoked",
                "database": "novalton_test",
                "project_chat_plan": "persisted and approved",
                "screenshots": 8,
                "model": "unconfigured",
            }
        )
    )


def main():
    second = provision_second_identity()
    api_port, next_port, proxy_port, driver_port = (
        8000,
        free_port(),
        free_port(),
        free_port(),
    )
    processes = []
    server = None
    browser = None
    with tempfile.TemporaryDirectory(prefix="novalton-browser-") as temp:
        key, cert = Path(temp) / "key.pem", Path(temp) / "cert.pem"
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "1",
                "-subj",
                "/CN=localhost",
                "-addext",
                "subjectAltName=DNS:localhost",
                "-keyout",
                str(key),
                "-out",
                str(cert),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            processes.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "novalton_api.main:app",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(api_port),
                    ],
                    cwd=ROOT / "apps/api",
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
            await_http(f"http://127.0.0.1:{api_port}/api/v1/health")
            origin = f"https://localhost:{proxy_port}"
            environment = {
                **os.environ,
                "NOVALTON_WEB_ORIGIN": origin,
                "NOVALTON_API_BASE_URL": f"http://127.0.0.1:{api_port}",
                "NOVALTON_OPERATOR_WORKSPACE_SCOPES": (
                    f"{os.environ.get('NOVALTON_TENANT_ID', '89cfc055-366e-5bcb-b65f-4f367185bf6d')}:"
                    f"{os.environ.get('NOVALTON_WORKSPACE_ID', 'b640b64f-8e55-53e8-a5b2-3beff9d5af82')},"
                    f"{second[0]}:{second[1]}"
                ),
            }
            processes.append(
                subprocess.Popen(
                    [
                        "node",
                        "../../node_modules/next/dist/bin/next",
                        "start",
                        "-p",
                        str(next_port),
                        "-H",
                        "127.0.0.1",
                    ],
                    cwd=ROOT / "apps/web",
                    env=environment,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
            await_http(f"http://127.0.0.1:{next_port}/login")
            server = ThreadingHTTPServer(
                ("127.0.0.1", proxy_port), proxy_handler(next_port)
            )
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(str(cert), str(key))
            server.socket = context.wrap_socket(server.socket, server_side=True)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            processes.append(
                subprocess.Popen(
                    [
                        "chromedriver",
                        f"--port={driver_port}",
                        "--allowed-ips=127.0.0.1",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
            await_http(f"http://127.0.0.1:{driver_port}/status")
            session = webdriver(
                driver_port,
                "POST",
                "/session",
                {
                    "capabilities": {
                        "alwaysMatch": {
                            "browserName": "chrome",
                            "goog:chromeOptions": {
                                "args": [
                                    "--headless=new",
                                    "--ignore-certificate-errors",
                                    "--disable-dev-shm-usage",
                                ]
                            },
                        }
                    }
                },
            )["sessionId"]
            browser = Browser(driver_port, session)
            browser.call("POST", "/timeouts", {"implicit": 10000, "pageLoad": 30000})
            run(browser, origin, second)
        finally:
            if browser:
                try:
                    browser.call("DELETE", "")
                except (OSError, AssertionError):
                    pass
            if server:
                server.shutdown()
                server.server_close()
            for process in reversed(processes):
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    main()
