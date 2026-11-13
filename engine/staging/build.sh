#!/bin/sh
# Build the PhotonVox staging engine (docs/ENGINE.md). Run as root on the staging container, once, on a fresh Debian 12 (about 12 minutes):
#   scp engine/staging/build.sh staging:/root/ && ssh staging 'setsid sh /root/build.sh > /root/vox-build.log 2>&1 < /dev/null &'
#
# It is the FusionPBX install script as it stood when production was installed, with every version pinned to production's
# (ARCHITECTURE §17a) and the changes docs/ENGINE.md lists. It configures no gateway: staging never reaches a carrier (Connor, 2026-11-13).
# The install prints the web admin's password; it goes to /root/vox-staging-admin.txt (mode 600), never into the log.
set -eu

INSTALL_REV=1d4100b95f90dfbb2206f681b0774a1925cf906f    # fusionpbx-install.sh, 2026-05-18: the script in use from then until 2026-07-30
FUSIONPBX_REV=0d7a9866f98cf63b9e1d6f5e8db52fc72f1b6049  # branch 5.5, 2026-07-30: the last commit at version 5.5.12
FREESWITCH_TAG=v1.11.1                                  # commit c2c59645f6, the build production reports
PIN_DATE=2026-07-31                                     # libks, spandsp and the optional FusionPBX apps: as they stood before 5.5.13

export DEBIAN_FRONTEND=noninteractive
log() { echo "== $(date -u +%H:%M:%S) $*"; }

# Only on a fresh container: the install script is not safe to run twice.
[ ! -e /var/www/fusionpbx ] && [ ! -e /etc/freeswitch ] || { echo "not a fresh container (FusionPBX or FreeSWITCH already present)"; exit 1; }
guard_before=$(nft -s list table inet vox_guard)

# Never install recommended packages (Connor's rule for the engines), for the script's own installs and for everything they pull in.
echo 'APT::Install-Recommends "0";' > /etc/apt/apt.conf.d/99-no-recommends

log "fetching the install script at $INSTALL_REV"
apt-get update
apt-get install -y --no-install-recommends git ca-certificates
cd /usr/src
[ -d fusionpbx-install.sh ] || git clone -q https://github.com/fusionpbx/fusionpbx-install.sh.git
cd fusionpbx-install.sh
git checkout -q -f "$INSTALL_REV"
r=debian/resources

log "pinning versions"
find debian -name '*.sh' -exec sed -i -E 's/\b(apt(-get)?) +(-y +)?install +(-y +)?/\1 install -y --no-install-recommends /' {} +
sed -i "s/git checkout v\$switch_version/git checkout $FREESWITCH_TAG/" $r/switch/source-release.sh
sed -i -E "s/^(\s*)cd (libks|spandsp)$/\1cd \2 \&\& git checkout -q \$(git rev-list -1 --before=$PIN_DATE HEAD)/" $r/switch/source-release.sh
sed -i "s|^git clone \$branch https://github.com/fusionpbx/fusionpbx.git /var/www/fusionpbx$|& \&\& git -C /var/www/fusionpbx checkout -q $FUSIONPBX_REV|" $r/fusionpbx.sh
sed -i -E "s|^(\s*git clone https://github.com/fusionpbx/fusionpbx-app-[a-z_]+\.git ([a-z_]+))$|\1 \&\& git -C \2 checkout -q \$(git -C \2 rev-list -1 --before=$PIN_DATE HEAD)|" $r/applications.sh
# The later script's fix for unprivileged containers (upstream 6794bc1): no realtime scheduling, which an unprivileged LXC refuses.
sed -i 's/^if \[ -e \/proc\/user_beancounters \]$/if [ -e \/proc\/user_beancounters ] || systemd-detect-virt --container --quiet/' $r/switch/package-systemd.sh
sed -i 's/s\/CPUSchedulingPolicy=rr\/;CPUSchedulingPolicy=rr\/g/s\/^\\(IOSchedulingClass\\|IOSchedulingPriority\\|CPUSchedulingPolicy\\|CPUSchedulingPriority\\)=\/;\\1=\//' $r/switch/package-systemd.sh
# The sound tarballs are not needed once unpacked (the disk is 10 GB).
echo 'rm -f /usr/share/freeswitch/sounds/*.tar.gz' >> $r/switch/source-sounds.sh

grep -q "checkout $FREESWITCH_TAG" $r/switch/source-release.sh
grep -q "checkout -q $FUSIONPBX_REV" $r/fusionpbx.sh
[ "$(grep -c 'rev-list -1 --before' $r/switch/source-release.sh)" = 2 ]
grep -q 'systemd-detect-virt' $r/switch/package-systemd.sh
git diff --stat

log "running the install"
# The install prints the admin's password: it goes to a root-only file, never into this log. (Only that file is made private: a umask around
# the install would leave everything it creates unreadable to FreeSWITCH and the web server, as the first build found.)
install -m 600 /dev/null /root/vox-staging-admin.txt
sh debian/install.sh 2>&1 | awk '/^[ \t]+password:/ { print >> "/root/vox-staging-admin.txt"; print "      password: (in /root/vox-staging-admin.txt)"; fflush(); next }
                                 { print; fflush() }'

log "after the install"
# Free the build objects; the sources stay for a rebuild.
make -C /usr/src/freeswitch-1.11 clean > /dev/null
apt-get clean
# fail2ban was started in the same step that installed rsyslog, before /var/log/auth.log existed, so its sshd jail failed; the install's advice
# is a reboot, which would also clear it.
systemctl restart fail2ban

[ "$(nft -s list table inet vox_guard)" = "$guard_before" ] && log "vox_guard unchanged" || log "WARNING: vox_guard changed"
freeswitch -version
for s in freeswitch postgresql nginx php8.2-fpm fail2ban event_guard; do echo "$s: $(systemctl is-active $s)"; done
fs_cli -x 'sofia status' | grep -E 'profile|gateway'
psql --version
df -h /
log "done"
