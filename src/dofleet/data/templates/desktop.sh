#!/bin/bash
# dofleet template: desktop
# Everything in "harden", plus an XFCE desktop reachable over RDP (Windows "Remote Desktop", macOS "Windows App").
# Vars: user, password (generated when not given), rdp_port
#include harden
apt-get install -yq xfce4 xfce4-goodies xrdp
set +x  # keep the password out of cloud-init-output.log
echo "${user}:${password}" | chpasswd
set -x
echo xfce4-session > /home/${user}/.xsession
chown ${user}:${user} /home/${user}/.xsession
adduser xrdp ssl-cert
sed -i "s/^port=.*/port=${rdp_port}/" /etc/xrdp/xrdp.ini
ufw allow ${rdp_port}/tcp
systemctl enable xrdp
systemctl restart xrdp
