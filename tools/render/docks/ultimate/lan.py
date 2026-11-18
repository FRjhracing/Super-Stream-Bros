"""Optional LAN access for a dock (off by default). Standard library only.

Off (the default): the dock listens on 127.0.0.1 only, exactly as before.

On (dock_config.json):
    "lan": true,
    "lanPin": "at least 6 characters",      other PCs/tablets: full control (report, start, overlay...)
    "lanViewPin": "optional, different",   other PCs/TVs: look only (bracket screens), every change refused
The dock then listens on every network interface. A browser on another device opens
http://<hub IP>:<port>/, gets a PIN page once, and a cookie remembers it (per dock port, 7 days, until
the PIN changes). The PC running the dock never needs the PIN.

Same file in docks\\melee\\ and docks\\ultimate\\ (each dock stays self-contained); keep them equal.
Plain HTTP: use it on a trusted, wired event LAN, not on public venue Wi-Fi.
"""
import hashlib
import hmac
import html
import ipaddress
import socket
import time
import urllib.parse

MIN_PIN = 6
COOKIE_DAYS = 7


class Lan:
    def __init__(self, config, port, title):
        self.port = port
        self.title = title
        self.pin = str(config.get("lanPin") or "").strip()
        self.view_pin = str(config.get("lanViewPin") or "").strip()
        self.on = bool(config.get("lan"))
        self.problem = ""
        if self.on and len(self.pin) < MIN_PIN:
            self.problem = f'"lan" is on but "lanPin" is shorter than {MIN_PIN} characters: LAN access stays OFF.'
            self.on = False
        if self.view_pin and (self.view_pin == self.pin or len(self.view_pin) < MIN_PIN):
            self.problem += f' "lanViewPin" must differ from lanPin and have {MIN_PIN}+ characters: view PIN ignored.'
            self.view_pin = ""
        self.cookie = f"ssb_dock_{port}"  # cookies ignore the port, so two docks on one hub need their own name
        self.failures = {}  # client address -> recent wrong PIN times

    @property
    def host(self):
        return "0.0.0.0" if self.on else "127.0.0.1"

    @staticmethod
    def is_local(addr):
        try:
            ip = ipaddress.ip_address(addr)
            return ip.is_loopback or bool(getattr(ip, "ipv4_mapped", None) and ip.ipv4_mapped.is_loopback)
        except ValueError:
            return False

    def _token(self, role, pin):
        return hashlib.sha256(f"ssb-dock|{self.port}|{role}|{pin}".encode("utf-8")).hexdigest()

    def role(self, handler):
        """'local' (this PC), 'full' / 'view' (logged-in LAN device) or None (not allowed yet)."""
        if self.is_local(handler.client_address[0]):
            return "local"
        if not self.on:
            return None
        jar = {}
        for part in (handler.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            jar[k] = v
        got = jar.get(self.cookie, "")
        if got and hmac.compare_digest(got, self._token("full", self.pin)):
            return "full"
        if got and self.view_pin and hmac.compare_digest(got, self._token("view", self.view_pin)):
            return "view"
        return None

    def check_pin(self, addr, pin):
        """Role for a typed PIN, or None. Slows down guessing: 5 wrong tries a minute per device."""
        now = time.time()
        recent = [t for t in self.failures.get(addr, []) if now - t < 60]
        if len(recent) >= 5:
            self.failures[addr] = recent
            return "wait"
        pin = (pin or "").strip()
        if pin and hmac.compare_digest(pin, self.pin):
            return "full"
        if pin and self.view_pin and hmac.compare_digest(pin, self.view_pin):
            return "view"
        self.failures[addr] = recent + [now]
        time.sleep(1)
        return None

    def cookie_header(self, role):
        pin = self.pin if role == "full" else self.view_pin
        return (f"{self.cookie}={self._token(role, pin)}; Path=/; Max-Age={COOKIE_DAYS * 86400}; "
                "HttpOnly; SameSite=Strict")

    def login_page(self, nxt="/", error=""):
        nxt = nxt if nxt.startswith("/") and not nxt.startswith("//") else "/"
        err = f'<p class="err">{html.escape(error)}</p>' if error else ""
        return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{html.escape(self.title)}: PIN</title>
<style>body{{margin:0;background:#0b0b0b;color:#eee;font:18px/1.4 system-ui,"Segoe UI",sans-serif;display:grid;place-items:center;min-height:100vh}}
form{{background:#161616;border:1px solid #333;border-radius:12px;padding:24px;width:min(360px,90vw)}}
h1{{font-size:20px;margin:0 0 6px}}p{{color:#aaa;font-size:14px;margin:0 0 14px}}.err{{color:#ff8080}}
input,button{{font:inherit;width:100%;box-sizing:border-box;padding:12px;border-radius:8px;border:1px solid #444;background:#0b0b0b;color:#eee;margin-top:8px}}
button{{background:#d1fa50;color:#111;border:0;font-weight:700;cursor:pointer}}</style></head>
<body><form method="post" action="/login"><h1>{html.escape(self.title)}</h1>
<p>Enter the event PIN from the head TO. This device remembers it.</p>{err}
<input type="hidden" name="next" value="{html.escape(nxt)}">
<input name="pin" type="password" autocomplete="current-password" autofocus placeholder="PIN">
<button>Open</button></form></body></html>"""

    def urls(self):
        """Addresses other devices can use (best guess: this PC's IPv4 addresses)."""
        ips = set()
        try:
            ips.update(socket.gethostbyname_ex(socket.gethostname())[2])
        except OSError:
            pass
        try:  # the address used to reach the internet (no packet is sent)
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("192.0.2.1", 9))
            ips.add(s.getsockname()[0])
            s.close()
        except OSError:
            pass
        ips = sorted(ip for ip in ips if not ip.startswith(("127.", "169.254.")))
        return [f"http://{ip}:{self.port}/" for ip in ips]

    def describe(self):
        if not self.on:
            return "LAN access: off (this PC only)." + (f" {self.problem}" if self.problem else "")
        lines = ["LAN access: ON. Other devices on this network can open:"] + [f"   {u}" for u in self.urls()]
        lines.append("   PIN: full control" + (" / view PIN: look only" if self.view_pin else "") +
                     ". Allow Python in the Windows Firewall prompt (Private networks only).")
        if self.problem:
            lines.append("   " + self.problem.strip())
        return "\n".join(lines)


def read_form(handler, limit=4096):
    n = min(int(handler.headers.get("Content-Length") or 0), limit)
    data = handler.rfile.read(n).decode("utf-8", "replace") if n else ""
    return {k: v[0] for k, v in urllib.parse.parse_qs(data).items()}
