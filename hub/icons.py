"""App icons drawn in code (standard library only), so the repository holds no binary files."""
import math
import struct
import zlib

BG = (17, 19, 23)
ACCENT = (79, 140, 255)
WHITE = (255, 255, 255)


def _png(w, h, rows):
    raw = b"".join(b"\x00" + bytes(r) for r in rows)

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def _seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def draw(size, pad=0.0):
    """A rounded square with a hub: one centre node joined to three outer nodes."""
    m, r = size * pad, size * 0.22
    c, orbit, dot, centre, line = size / 2, size * (0.5 - pad) * 0.55, size * 0.075, size * 0.12, size * 0.015
    nodes = [(c + orbit * math.cos(math.radians(a)), c - orbit * math.sin(math.radians(a))) for a in (90, 210, 330)]
    rows = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            px, py = x + 0.5, y + 0.5
            qx, qy = max(m + r - px, 0, px - (size - m - r)), max(m + r - py, 0, py - (size - m - r))
            inside = m <= px <= size - m and m <= py <= size - m and math.hypot(qx, qy) <= r
            col = ACCENT if inside else BG
            if inside:
                if math.hypot(px - c, py - c) <= centre or any(math.hypot(px - nx, py - ny) <= dot for nx, ny in nodes):
                    col = WHITE
                elif any(_seg_dist(px, py, c, c, nx, ny) <= line for nx, ny in nodes):
                    col = WHITE
            row += bytes(col)
        rows.append(row)
    return _png(size, size, rows)


_CACHE = {}
SIZES = {"icon-192.png": (192, 0.0), "icon-512.png": (512, 0.0), "icon-maskable-512.png": (512, 0.12)}


def get(name):
    if name not in SIZES:
        return None
    if name not in _CACHE:
        _CACHE[name] = draw(*SIZES[name])
    return _CACHE[name]
