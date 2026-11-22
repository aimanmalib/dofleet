# dofleet: format (first use only) and mount every attached DigitalOcean volume under /mnt/<volume name>
for dev in /dev/disk/by-id/scsi-0DO_Volume_*; do
  [ -e "$dev" ] || continue
  dfvol=${dev##*/scsi-0DO_Volume_}
  blkid "$dev" >/dev/null 2>&1 || mkfs.ext4 -q "$dev"
  mkdir -p "/mnt/$dfvol"
  grep -q "$dev" /etc/fstab || echo "$dev /mnt/$dfvol ext4 defaults,nofail,discard,noatime 0 2" >> /etc/fstab
  mount "/mnt/$dfvol" || true
done
