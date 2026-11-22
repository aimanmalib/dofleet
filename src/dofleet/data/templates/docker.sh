#!/bin/bash
# dofleet template: docker
# Everything in "harden", plus Docker Engine and the compose plugin from Ubuntu's archive.
#include harden
apt-get install -yq docker.io docker-compose-v2
usermod -aG docker ${user}
systemctl enable --now docker
