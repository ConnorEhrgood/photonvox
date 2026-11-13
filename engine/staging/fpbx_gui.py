"""FusionPBX's own screens, driven over HTTPS the way a person uses them (staging only): log in, read a form's fields (hidden tokens included),
post it back. Used to build hand-made test domains exactly as FusionPBX's pages write them (the takeover importer's stand-ins, ARCHITECTURE §17).
The admin password is passed in by the caller (from staging's root-only file); it is never printed."""
from __future__ import annotations

import html
import http.cookiejar
import re
import ssl
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple

Fields = List[Tuple[str, str]]


class Gui:
    def __init__(self, base: str, username: str, password: str) -> None:
        self.base = base.rstrip("/")
        ctx = ssl.create_default_context()
        ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE          # staging's self-signed certificate
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx), urllib.request.HTTPCookieProcessor(self.jar))
        self.get("/login.php")
        page = self.post("/login.php", [("username", username), ("password", password)])
        if "name='password'" in page:
            raise RuntimeError("FusionPBX refused the sign-in")

    def get(self, path: str) -> str:
        with self.op.open(self.base + path, timeout=30) as r:
            return r.read().decode("utf-8", "replace")

    def post(self, path: str, fields: Fields, files: Optional[Dict[str, Tuple[str, bytes, str]]] = None) -> str:
        if files:
            boundary = "----photonvox-gui"
            body = b""
            for k, v in fields:
                body += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
            for k, (name, data, ctype) in files.items():
                body += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; filename="{name}"\r\nContent-Type: {ctype}\r\n\r\n'.encode() + data + b"\r\n"
            body += f"--{boundary}--\r\n".encode()
            req = urllib.request.Request(self.base + path, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        else:
            req = urllib.request.Request(self.base + path, data=urllib.parse.urlencode(fields).encode())
        with self.op.open(req, timeout=60) as r:
            return r.read().decode("utf-8", "replace")

    def form(self, path: str, name: Optional[str] = None) -> Tuple[str, Fields]:
        """The page's form (the first, or the one named): its action and its fields with their current values, as the browser would send them."""
        page = self.get(path)
        forms = re.findall(r"<form\b([^>]*)>(.*?)</form>", page, re.S | re.I)
        attrs, body = next(((a, b) for a, b in forms if not name or re.search(rf"name=['\"]{name}['\"]", a)), forms[0])
        action = re.search(r"action=['\"]([^'\"]*)['\"]", attrs)
        out: Fields = []
        selects = {m.group(1): m.group(2) for m in re.finditer(r"<select\b[^>]*name=['\"]([^'\"]+)['\"][^>]*>(.*?)</select>", body, re.S | re.I)}
        for tag in re.findall(r"<(?:input|select|textarea)\b[^>]*>", body, re.I):
            n = re.search(r"name=['\"]([^'\"]+)['\"]", tag)
            if not n:
                continue
            t = (re.search(r"type=['\"]([^'\"]+)['\"]", tag) or [None, "text"])[1].lower()
            if t in ("submit", "button", "file") or (t in ("checkbox", "radio") and "checked" not in tag.lower()):
                continue
            if tag.lower().startswith("<select"):
                opts = re.findall(r"<option\b([^>]*)>", selects.get(n.group(1), ""), re.I)
                pick = next((o for o in opts if re.search(r"\bselected\b", o, re.I)), opts[0] if opts else "")
                v = re.search(r"value=['\"]([^'\"]*)['\"]", pick)
            else:
                v = re.search(r"value=['\"]([^'\"]*)['\"]", tag)
            out.append((n.group(1), html.unescape(v.group(1)) if v else ""))
        return (action.group(1) if action and action.group(1) else path), out


def setf(fields: Fields, **values: str) -> Fields:
    """The form's fields with these set (replacing a field of that name, or adding it)."""
    out = [(k, v) for k, v in fields if k not in values]
    return out + [(k, str(v)) for k, v in values.items()]
