#!/usr/bin/env bash
# Install or update vox-agent on an engine:   agent/install.sh <user@host> <ssh key> [bind address:port] [operations]
#   e.g. agent/install.sh root@10.10.0.60 ~/.ssh/vox_staging 127.0.0.1:8780
#        agent/install.sh root@10.10.0.60 ~/.ssh/vox_staging 10.10.0.60:8780 status,cache/delete,check
# A first install makes the shared secret, kept on the engine in /etc/vox-agent.env (root:www-data, 0640) and on this machine in
# ~/.config/photonvox/agent-<host>.secret (0600) for registering the instance in PhotonVox (where it is sealed). It is never printed.
# An update (the engine already has /etc/vox-agent.env) keeps that file as it is: its secret, bind address, operations list
# (VOX_AGENT_OPERATIONS) and domains (VOX_AGENT_DOMAINS) all stay, and no local secret is needed. A bind address or operations list given
# on the command line replaces only that line, and is said so. (Audit VOX-B-7: an update once rewrote the file with the secret and bind
# only, which switched every operation back on.) The live engine's settings are tracked in engine/live/vox-agent-live.env.
set -euo pipefail
cd "$(dirname "$0")"
DEST=$1 KEY=$2 BIND=${3:-} OPS=${4:-}
HOST=${DEST#*@}
LOCAL=~/.config/photonvox/agent-$HOST.secret
[[ -z "$BIND" || "$BIND" =~ ^[0-9.]+:[0-9]+$ ]] || { echo "bind must be address:port" >&2; exit 2; }
[[ -z "$OPS" || "$OPS" =~ ^[a-z/,-]+$ ]] || { echo "operations: a comma-separated list such as status,cache/delete,check" >&2; exit 2; }
python3 -c "import sys, vox_agent as v; v.Config({'VOX_AGENT_SECRET': 'x' * 32, 'VOX_AGENT_ESL_PASSWORD': 'x', **({'VOX_AGENT_OPERATIONS': sys.argv[1]} if sys.argv[1] else {})})" "$OPS"

if ssh -i "$KEY" "$DEST" 'test -f /etc/vox-agent.env'; then
  echo "updating: /etc/vox-agent.env on $HOST is kept${BIND:+, bind set to $BIND}${OPS:+, operations set to $OPS}"
  # Only the lines named on the command line change; every other line (the secret among them) stays. BIND and OPS were checked above.
  ssh -i "$KEY" "$DEST" "set -e; umask 077; f=/etc/vox-agent.env
    grep -q '^VOX_AGENT_SECRET=' \$f || { echo 'the engine has /etc/vox-agent.env without a secret: fix it by hand' >&2; exit 1; }
    awk -v b='$BIND' -v o='$OPS' '(b != \"\" && /^VOX_AGENT_BIND=/) || (o != \"\" && /^VOX_AGENT_OPERATIONS=/) { next } { print }
      END { if (b != \"\") print \"VOX_AGENT_BIND=\" b; if (o != \"\") print \"VOX_AGENT_OPERATIONS=\" o }' \$f > \$f.new
    cat \$f.new > \$f; rm -f \$f.new
    grep '^VOX_AGENT_OPERATIONS=' \$f || echo '(no VOX_AGENT_OPERATIONS line: this engine allows every operation)'"
else
  mkdir -p ~/.config/photonvox && chmod 700 ~/.config/photonvox
  [ -f "$LOCAL" ] || (umask 077; python3 -c "import secrets; print(secrets.token_hex(32))" > "$LOCAL")
  { echo "VOX_AGENT_SECRET=$(cat "$LOCAL")"; echo "VOX_AGENT_BIND=${BIND:-127.0.0.1:8780}"; [ -z "$OPS" ] || echo "VOX_AGENT_OPERATIONS=$OPS"; } \
    | ssh -i "$KEY" "$DEST" 'umask 027; cat > /etc/vox-agent.env && chown root:www-data /etc/vox-agent.env'
fi
ssh -i "$KEY" "$DEST" 'mkdir -p /opt/vox-agent'
scp -q -i "$KEY" vox_agent.py "$DEST:/opt/vox-agent/vox_agent.py"
scp -q -i "$KEY" vox-agent.service "$DEST:/etc/systemd/system/vox-agent.service"
ssh -i "$KEY" "$DEST" 'chmod 644 /opt/vox-agent/vox_agent.py && systemctl daemon-reload && systemctl enable vox-agent >/dev/null 2>&1 && systemctl restart vox-agent && sleep 1 && systemctl is-active vox-agent'
