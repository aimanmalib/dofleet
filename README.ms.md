<p align="center"><picture><source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark-512.png"><img src="assets/logo-512.png" width="112" height="112" alt="dofleet"></picture></p>

<h1 align="center">dofleet</h1>

<p align="center"><a href="https://pypi.org/project/dofleet/"><img src="https://img.shields.io/pypi/v/dofleet" alt="PyPI"></a> <a href="https://github.com/aimanmalib/dofleet/blob/main/LICENSE"><img src="https://img.shields.io/badge/lesen-MIT-blue" alt="Lesen: MIT"></a></p>

<p align="center"><b>Droplet DigitalOcean pakai-buang yang memadam dirinya sendiri.</b><br>
<a href="README.md">English</a> · Dibina di Malaysia oleh <a href="https://aimanmalib.com">Aiman Malib</a> · <a href="https://sasateguh.com">Sasa Teguh</a></p>

Setiap droplet yang dicipta `dofleet` membawa pemasa tamat, dan reaper memadamnya bila masa tamat, sama ada anda ingat atau tidak. Anda nampak kos sebelum mengesahkan, bajet bulanan menghalang anda daripada melepasinya, dan saiz yang habis stok beralih ke pilihan seterusnya dalam pratetap.

<p align="center"><img alt="demo dofleet run" src="assets/demo.gif" width="760"></p>

Contoh dalam Bahasa Melayu:

```console
$ dofleet --lang ms run scratch --sync ./data --pull laporan.csv -- python3 proses.py
Pratetap      scratch
Lokasi        sgp1  s-4vcpu-8gb  (4 vCPU / 8 GB / 160 GB)
Volume        100 GB, dipadam bersama droplet
Pemasa tamat  6h00m
Bajet         baki $41.20 bulan ini
Hasil disalin ke dofleet-out/run
Kod keluar 0, 7.4 minit, kira-kira $0.01.
```

## Apa yang ia buat

- **Pemasa + reaper.** `dofleet reap` dari cron, atau `dofleet install-reaper` menjalankannya dalam akaun DigitalOcean anda sebagai Function berjadual, jadi tiada mesin anda perlu hidup.
- **Kerja satu arahan.** `dofleet run` hidupkan droplet, salin folder, jalankan arahan (output dipapar terus), salin hasil balik, padam semua.
- **Duit.** Kos sebelum cipta, belanja setakat ini dalam `ls`, dan siling `budget_usd`: `up` ditolak bila melepasi bajet, dan reaper boleh memadam semua droplet dofleet bila penggunaan bulan ini mencapainya. Saiz GPU wajib ada pemasa.
- **Untuk ejen AI.** `dofleet mcp` ialah pelayan MCP: Claude atau ejen lain boleh meminjam droplet, menjalankan arahan dan memulangkannya, dalam had yang anda tetapkan (`[mcp]` dalam config). Ejen tidak pernah nampak token anda.
- **Boot pantas.** `dofleet bake` mengambil snapshot persediaan yang siap; `up --baked` boot dalam kira-kira 40 saat, bukan 2 hingga 3 minit.
- **CI dan pratonton.** GitHub Action (`action.yml`) mencipta droplet untuk setiap kerja atau pull request dan memadamnya selepas itu.
- **Persediaan kemas.** Ubuntu dikeraskan, Docker, desktop jauh melalui RDP, atau skrip sendiri. "Sedia" bermaksud cloud-init sudah siap.

## Pasang dan token

```bash
pipx install dofleet
export DIGITALOCEAN_TOKEN=dop_v1_...
dofleet whoami
```

Jika anda sudah guna `doctl`, tokennya dibaca terus.

## Arahan utama

| Arahan | Fungsi |
| --- | --- |
| `dofleet up [pratetap]` | Cipta droplet (`--ttl`, `--volume`, `--baked`, `--dry-run`) |
| `dofleet run PRATETAP -- ARAHAN` | Satu kerja atas droplet baharu (`--sync`, `--pull`, `--env`) |
| `dofleet ls`, `cost` | Senarai dengan belanja dan masa tinggal; penggunaan bulan ini dan baki bajet |
| `dofleet extend`, `down`, `reap` | Lanjut pemasa, padam, padam yang tamat |
| `dofleet bake`, `install-reaper`, `mcp` | Snapshot, reaper dalam DigitalOcean Functions, pelayan MCP |

Senarai penuh, contoh config, GitHub Action dan butiran keselamatan ada dalam [README Inggeris](README.md). Tambah `--lang ms` untuk paparan Bahasa Melayu (lalai ikut `LANG`).

## Keselamatan

- `reap` dan reaper Function hanya menyentuh droplet bertag `dofleet`, dan membaca semula setiap droplet sebelum memadam. Tag pemasa kosong (`dofleet-exp-*`, `dofleet-detached-*`) yang ditinggalkan droplet dan volume yang sudah dipadam turut dibuang selepas masanya lewat sejam; tag lain tidak disentuh. Corak dalam `down` (`'web-*'`) hanya padan droplet dofleet kecuali dengan `--any`; `extend` menolak droplet bukan dofleet.
- `notify_cmd` dalam config boleh membawa `{message}` dan `{level}` dalam mana-mana argumen, cth `["/usr/local/bin/notify.sh", "{message}", "{level}"]`. Tahapnya `info` bila droplet dipadam kerana pemasanya tamat (dijangka, tiada tindakan), `warn` bila bajet bulanan menyebabkan reaper memadamnya, dan `critical` bila padam gagal dan droplet masih berjalan. Tanpa `{message}`, mesej ditambah sebagai argumen terakhir seperti dahulu.
- Ejen AI melalui MCP hanya nampak droplet yang ia cipta sendiri (tag `dofleet-mcp`), bukan droplet anda.
- Fail yang dibawa balik oleh `run` dibuka dengan penapis `data` tarfile: tiada laluan mutlak, `..` atau pautan keluar.
- Akaun tanpa kunci SSH: kunci awam tempatan anda ditambah. Tiada kunci langsung: log masuk root + kata laluan kekal supaya anda tidak terkunci.
- Arahan cipta tidak diulang selepas ralat pelayan, kerana DigitalOcean mungkin sudah mencipta droplet.

## Lesen

MIT
