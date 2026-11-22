#!/bin/bash
# dofleet template: harden
# Sudo user with your SSH keys, firewall, fail2ban, automatic security updates.
# Vars: user, password_auth (yes|no)
set -eux
export DEBIAN_FRONTEND=noninteractive
id -u ${user} >/dev/null 2>&1 || adduser --disabled-password --gecos "" ${user}
usermod -aG sudo ${user}
echo "${user} ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/90-dofleet-${user}
chmod 440 /etc/sudoers.d/90-dofleet-${user}
if [ -f /root/.ssh/authorized_keys ]; then
  install -d -m 700 -o ${user} -g ${user} /home/${user}/.ssh
  install -m 600 -o ${user} -g ${user} /root/.ssh/authorized_keys /home/${user}/.ssh/authorized_keys
fi
mkdir -p /etc/ssh/sshd_config.d
cat > /etc/ssh/sshd_config.d/10-dofleet.conf <<CONF
PasswordAuthentication ${password_auth}
PermitRootLogin prohibit-password
CONF
systemctl reload ssh || systemctl reload sshd || true
apt-get update -q
apt-get install -yq ufw fail2ban unattended-upgrades
ufw allow OpenSSH
ufw --force enable
systemctl enable --now fail2ban
