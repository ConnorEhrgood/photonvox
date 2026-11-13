"""An engine's own settings that PhotonVox keeps (ARCHITECTURE §5): its outgoing mail, for voicemail to email. FusionPBX sends voicemail
emails from its email queue with its `email` default settings (SMTP); PhotonVox writes those, nothing else of FusionPBX's settings. Photon's
choice is Postmark's SMTP (smtp.postmarkapp.com, port 587, STARTTLS, a Postmark server's token as user and password; a server of its own keeps
voicemail on its own stream)."""
from __future__ import annotations

import uuid
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.engine import Connection

FIELDS = {  # FusionPBX's subcategory: (our key, its type)
    "smtp_host": ("host", "text"), "smtp_port": ("port", "numeric"), "smtp_secure": ("secure", "text"), "smtp_auth": ("auth", "boolean"),
    "smtp_username": ("username", "text"), "smtp_password": ("password", "text"), "smtp_from": ("from", "text"),
    "smtp_from_name": ("from_name", "text"),
}


def email_values(cfg: Mapping[str, Any], password: str) -> dict:
    v = {"host": cfg["host"], "port": str(cfg.get("port", 587)), "secure": cfg.get("secure", "tls"), "username": cfg.get("username", ""),
         "password": password, "from": cfg["from"], "from_name": cfg.get("from_name", "")}
    v["auth"] = "true" if v["username"] else "false"
    return v


def write_email(conn: Connection, instance_id: str, cfg: Mapping[str, Any], password: str) -> None:
    """Set FusionPBX's `email` default settings to this instance's outgoing mail (each row updated, or added if the install lacks it)."""
    values = email_values(cfg, password)
    for sub, (key, kind) in FIELDS.items():
        row = conn.execute(text("update v_default_settings set default_setting_value = :v, default_setting_enabled = true where "
                                "default_setting_category = 'email' and default_setting_subcategory = :s"), {"v": values[key], "s": sub})
        if row.rowcount == 0:
            conn.execute(text("insert into v_default_settings (default_setting_uuid, default_setting_category, default_setting_subcategory, "
                              "default_setting_name, default_setting_value, default_setting_enabled, default_setting_description) "
                              "values (:u, 'email', :s, :k, :v, true, 'PhotonVox')"),
                         {"u": str(uuid.uuid5(uuid.UUID(instance_id), "email:" + sub)), "s": sub, "k": kind, "v": values[key]})
