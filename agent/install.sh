#!/usr/bin/env bash
# Install or update vox-agent on an engine:   agent/install.sh <user@host> <ssh key> [bind address:port]
#   e.g. agent/install.sh root@10.10.0.60 ~/.ssh/vox_staging 127.0.0.1:8780
# The shared secret is made once, kept on the engine in /etc/vox-agent.env (root:www-data, 0640) and on this machine in
# ~/.config/photonvox/agent-<host>.secret (0600) for registering the instance in PhotonVox (where it is sealed). It is never printed.
set -euo pipefail
cd "$(dirname "$0")"
DEST=$1 KEY=$2 BIND=${3:-127.0.0.1:8780}
HOST=${DEST#*@}
LOCAL=~/.config/photonvox/agent-$HOST.secret
mkdir -p ~/.config/photonvox && chmod 700 ~/.config/photonvox
[ -f "$LOCAL" ] || (umask 077; python3 -c "import secrets; print(secrets.token_hex(32))" > "$LOCAL")
ssh -i "$KEY" "$DEST" 'mkdir -p /opt/vox-agent'
scp -q -i "$KEY" vox_agent.py "$DEST:/opt/vox-agent/vox_agent.py"
scp -q -i "$KEY" vox-agent.service "$DEST:/etc/systemd/system/vox-agent.service"
{ echo "VOX_AGENT_SECRET=$(cat "$LOCAL")"; echo "VOX_AGENT_BIND=$BIND"; } | ssh -i "$KEY" "$DEST" 'umask 027; cat > /etc/vox-agent.env && chown root:www-data /etc/vox-agent.env'
ssh -i "$KEY" "$DEST" 'chmod 644 /opt/vox-agent/vox_agent.py && systemctl daemon-reload && systemctl enable vox-agent >/dev/null 2>&1 && systemctl restart vox-agent && sleep 1 && systemctl is-active vox-agent'
