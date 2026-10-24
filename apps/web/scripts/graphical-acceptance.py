"""Disposable Chrome/WebDriver acceptance against real Next, FastAPI and PostgreSQL.

Uses ChromeDriver bundled with the GitHub runner, without a browser download.
Only synthetic credentials and project data are created. No agent is launched.
"""

import base64
import http.client
import json
import os
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


def run(browser, origin):
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
                "return document.body.innerText.includes('Cahier des charges')",
                "responsive chat",
            )
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
            browser.screenshot(f"chat-{theme.lower()}-{width}.png")
            browser.navigate(origin + "/settings")
            browser.wait(
                "return document.body.innerText.includes('Clés personnelles')",
                "return to settings",
            )
    print(
        json.dumps(
            {
                "browser": "Chrome headless",
                "identity": "local disposable owner",
                "database": "novalton_test",
                "project_chat_plan": "persisted and approved",
                "screenshots": 8,
                "model": "unconfigured",
            }
        )
    )


def main():
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
                                    "--no-sandbox",
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
            run(browser, origin)
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
