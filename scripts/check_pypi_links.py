"""Fail when the PyPI description (wheel METADATA) still has relative links or images: they 404 on pypi.org."""

import re
import sys
import zipfile

wheel = zipfile.ZipFile(sys.argv[1])
meta = wheel.read(next(n for n in wheel.namelist() if n.endswith(".dist-info/METADATA"))).decode()
body = meta.split("\n\n", 1)[1]  # headers first, then the long description
html = re.findall(r'(?:href|src|srcset)="(?!https?://|#|mailto:)([^"]+)"', body)
md = re.findall(r'\]\((?!https?://|#|mailto:)([^)\s]+)\)', body)
if html or md:
    sys.exit(f"relative links in the PyPI description: {sorted(set(html + md))}")
print("pypi links ok")
