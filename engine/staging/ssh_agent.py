"""The staging engine's agent for the harness: app/engine/agent.py's SshAgent, pointed at staging."""
from __future__ import annotations

import os

from app.engine.agent import SshAgent

HOST = os.environ.get("VOX_STAGING", "root@10.10.0.60")
KEY = os.path.expanduser(os.environ.get("VOX_STAGING_KEY", "~/.ssh/vox_staging"))


def staging_agent() -> SshAgent:
    return SshAgent(HOST, KEY)
