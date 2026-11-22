"""Build assets/banner-{light,dark}.svg and assets/social.png from assets/logo.svg.

Text is converted to outlines (Space Grotesk, SIL Open Font License) so it renders the same everywhere, including
GitHub, which does not load fonts inside SVG images. Usage:
    curl -sL -o /tmp/sg.ttf "<Space Grotesk 600 .ttf from fonts.google.com>"
    python scripts/make-assets.py /tmp/sg.ttf        (needs fonttools; cairosvg for social.png)
"""
import re, sys
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen

font = TTFont(sys.argv[1])
gs, cmap, hmtx = font.getGlyphSet(), font.getBestCmap(), font["hmtx"]
upm = font["head"].unitsPerEm

def text_path(text, size, x0, baseline, tracking=0.0):
    scale = size / upm
    pen = SVGPathPen(gs)
    x = 0
    for ch in text:
        g = cmap[ord(ch)]
        tp = TransformPen(pen, (scale, 0, 0, -scale, x0 + x * scale, baseline))
        gs[g].draw(tp)
        x += hmtx[g][0] + tracking * upm
    return pen.getCommands(), x * scale

mark = open("assets/logo.svg").read()
inner = re.search(r"<title>dofleet</title>(.*)</svg>", mark, re.S).group(1)
inner = re.sub(r"<!--.*?-->", "", inner)
word, ww = text_path("dofleet", 64, 120, 70, -0.01)
tag, tw = text_path("disposable droplets that clean up after themselves", 19, 122, 104)
W = int(max(120 + ww, 122 + tw)) + 12
themes = {
    "light": {"word": "#0E2A3D", "tag": "#4B6475", "swap": {}},
    "dark": {"word": "#E6F1F7", "tag": "#9DB6C6",
             "swap": {"#0E2A3D": "#E6F1F7", "#1F4A66": "#B9D4E3", "#F8FAFC": "#0E2A3D", "#2DD4BF": "#0F9F8F"}},
}
for name, th in themes.items():
    m = inner
    for a, b in th["swap"].items():
        m = m.replace(a, "§" + b)
    m = m.replace("§", "")
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} 120" width="{W}" height="120" role="img" '
           f'aria-label="dofleet: disposable droplets that clean up after themselves">'
           f'<title>dofleet</title><g transform="translate(4 8) scale(1.05)">{m}</g>'
           f'<path d="{word}" fill="{th["word"]}"/><path d="{tag}" fill="{th["tag"]}"/></svg>\n')
    open(f"assets/banner-{name}.svg", "w").write(svg)
print("width", W)

# social preview 1280x640 (GitHub "Social preview", link cards)
t1, w1 = text_path("dofleet", 150, 470, 280, -0.01)
t2, w2 = text_path("Disposable DigitalOcean droplets", 40, 476, 356)
t3, w3 = text_path("that clean up after themselves", 40, 476, 408)
chips = ["expiry timers", "month budget", "one-command jobs", "MCP for AI agents"]
x, y, chip_svg = 476, 482, ""
for c in chips:
    _, w = text_path(c, 24, 0, 0)
    if x + w + 36 > 1216:  # wrap to the next row instead of running off the card
        x, y = 476, y + 58
    p, _ = text_path(c, 24, x + 18, y + 30)
    chip_svg += (f'<rect x="{x}" y="{y}" width="{w + 36:.0f}" height="44" rx="22" fill="#163A52"/>'
                 f'<path d="{p}" fill="#CFE3EE"/>')
    x += w + 52
mark_big = re.sub(r"<!--.*?-->", "", inner)
social = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 640" width="1280" height="640">'
          f'<rect width="1280" height="640" fill="#0B1E2C"/>'
          f'<circle cx="1180" cy="80" r="260" fill="#0F2A3D"/>'
          f'<g transform="translate(96 140) scale(3.2)">{mark_big.replace("#0E2A3D", "#E6F1F7").replace("#1F4A66", "#B9D4E3").replace("#F8FAFC", "#0E2A3D").replace("#2DD4BF", "#0F9F8F")}</g>'
          f'<path d="{t1}" fill="#F1F7FA"/><path d="{t2}" fill="#9DB6C6"/><path d="{t3}" fill="#9DB6C6"/>{chip_svg}</svg>')
try:
    import cairosvg
    cairosvg.svg2png(bytestring=social.encode(), write_to="assets/social.png", output_width=1280, output_height=640)
    print("social.png written")
except ImportError:
    open("assets/social.svg", "w").write(social)
