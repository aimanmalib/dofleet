# dofleet

Droplet DigitalOcean pakai-buang yang membersihkan dirinya sendiri.

[English](README.md)

Setiap droplet yang dicipta `dofleet` diberi pemasa tamat. Bila pemasa habis, `dofleet reap` (jalankan dari cron) memadamnya. Anda nampak kos satu kumpulan sebelum mengesahkan, dan berapa yang sudah dibelanjakan setiap droplet semasa ia berjalan. Jika saiz yang anda mahu habis stok di rantau anda, `dofleet` beralih ke saiz atau rantau seterusnya dalam pratetap, bukan gagal.

```console
$ dofleet --lang ms up quick -n kikis -c 3
Pratetap      quick
Lokasi        sgp1  s-4vcpu-8gb-amd  (4 vCPU / 8 GB / 160 GB)
              sgp1 s-4vcpu-8gb habis stok, guna pilihan seterusnya
Nama          kikis-01, kikis-02, kikis-03
Pemasa tamat  8h00m
Kos           kira-kira $2.00 jika hidup sehingga pemasa tamat, $168.00 untuk sebulan penuh
Cipta 3 droplet? [y/N]: y
```

## Kenapa bukan doctl sahaja?

[`doctl`](https://github.com/digitalocean/doctl) ialah CLI rasmi dan meliputi seluruh API. `dofleet` membuat lebih sedikit, untuk satu kerja: mesin jangka pendek yang anda hidupkan untuk satu tugas dan terlupa padam.

- Pemasa tamat + `reap` untuk droplet yang terlupa
- Kos dipapar sebelum cipta, belanja setakat ini dalam `ls`
- Sandaran bila saiz habis stok, merentas saiz dan rantau
- Menunggu sehingga SSH (atau RDP) benar-benar menjawab
- Pratetap dan skrip persediaan dalam satu fail TOML
- Menu bernombor bila dijalankan tanpa hujah
- Paparan Bahasa Melayu dan Inggeris

Jika anda sudah guna doctl, `dofleet` membaca tokennya, jadi tiada apa perlu disediakan.

## Pasang

```bash
pipx install dofleet        # atau: uv tool install dofleet
```

Python 3.11 ke atas. Sebelum keluaran PyPI pertama: `pipx install git+https://github.com/aimanmalib/dofleet`.

## Token

Cipta token di <https://cloud.digitalocean.com/account/api/tokens>, kemudian `export DIGITALOCEAN_TOKEN=dop_v1_...`, atau biar `dofleet` guna log masuk `doctl auth init` sedia ada. `dofleet whoami` menunjukkan akaun dan sumber token yang dipakai.

## Arahan

Senarai penuh ada dalam [README Inggeris](README.md#commands). Ringkasnya: `up`, `ls`, `extend`, `reap`, `down`, `restart`, `ssh`, `cost`, `sizes`, `presets`, `init`, `whoami`. Tambah `--json` untuk output mesin dan `--lang ms` untuk Bahasa Melayu (lalai ikut `LANG`).

Jalankan `reap` dari cron setiap 10 minit:

```cron
*/10 * * * * DIGITALOCEAN_TOKEN=dop_v1_... /home/anda/.local/bin/dofleet reap --yes >> ~/.dofleet-reap.log 2>&1
```

`reap` hanya menyentuh droplet bertag `dofleet` dengan tag `dofleet-exp-<masa unix>` yang sudah lepas. Droplet yang anda cipta dengan tangan atau alat lain tidak akan dipadam.

## Pratetap dan templat

Ubah pratetap atau tambah sendiri dalam `~/.config/dofleet/config.toml` (`dofleet init` menulis fail permulaan berkomen). Templat persediaan ialah skrip shell biasa: `harden` (pengguna sudo, firewall, fail2ban, kemas kini keselamatan automatik), `docker`, dan `desktop` (desktop XFCE melalui RDP; kata laluan dijana dan dipapar sekali).

## Keselamatan dan volume

- Akaun tanpa kunci SSH: `dofleet` menambah kunci awam tempatan anda (`~/.ssh/id_ed25519.pub` dahulu). Tiada kunci langsung: DigitalOcean e-mel kata laluan root, dan `dofleet` kekalkan log masuk root + kata laluan supaya anda tidak terkunci.
- "Sedia" bermaksud cloud-init sudah `done` (disemak melalui SSH), bukan hanya port terbuka.
- `volumes = [100]` atau `--volume 100`: volume diformat ext4, dipasang di `/mnt/<nama volume>`, dan dipadam bersama droplet oleh `down` dan `reap`. Volume yang anda pasang sendiri tidak disentuh.
- Corak dalam `down` (`'web-*'`) hanya padan droplet buatan dofleet, kecuali dengan `--any`.
- `notify_cmd` dalam config: arahan yang dijalankan selepas `reap` memadam sesuatu.

## Lesen

MIT
