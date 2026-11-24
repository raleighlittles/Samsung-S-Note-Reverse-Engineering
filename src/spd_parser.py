#!/usr/bin/env python3
"""
spd_parser.py - parser/renderer for Samsung S Note ".spd" files (2013-2014 era,
S Pen SDK).  Reverse-engineered from sample files; see SPD_FORMAT_NOTES.md.

Usage:
    python spd_parser.py note.spd                 # print structure summary
    python spd_parser.py note.spd --render outdir # also render each page to PNG

Requires Pillow only for --render.
"""

import pathlib
import struct
import zipfile
import os
import argparse
import re

from PIL import Image, ImageDraw

SCALE = 32.0          # stroke deltas are in 1/32 px units


def sm16(v):
    """16-bit sign-magnitude -> int (bit15 = sign)."""
    return -(v & 0x7FFF) if v & 0x8000 else v


def read_pageids(data):
    """pageIdInfo.dat: u16 count, then count x (u16 nchars, UTF-16LE chars)."""
    n = struct.unpack_from('<H', data, 0)[0]
    pos, ids = 2, []
    for _ in range(n):
        L = struct.unpack_from('<H', data, pos)[0]
        pos += 2
        ids.append(data[pos:pos + 2 * L].decode('utf-16le'))
        pos += 2 * L
    return ids


def read_kv_map(d, pos):
    """Small string->string map block: u32 size, u8 type, u16 count, then
    entries of (u16 keylen incl NUL, ASCII key + NUL, u16 nchars, UTF-16LE val)."""
    size = struct.unpack_from('<I', d, pos)[0]
    cnt = struct.unpack_from('<H', d, pos + 5)[0]
    p = pos + 7
    out = {}
    for _ in range(cnt):
        kl = struct.unpack_from('<H', d, p)[0]; p += 2
        key = d[p:p + kl].rstrip(b'\0').decode('ascii'); p += kl
        vl = struct.unpack_from('<H', d, p)[0]; p += 2
        out[key] = d[p:p + 2 * vl].decode('utf-16le'); p += 2 * vl
    return out, pos + 4 + size


def parse_stroke(body):
    A, B = struct.unpack_from('<II', body, 0)
    flags5 = body[8:13]
    rect = struct.unpack_from('<4f', body, 13)           # l, t, r, b
    pre5 = body[29:34]
    plen = struct.unpack_from('<I', body, 34)[0]
    pay = body[38:]
    hdr = pay[:4]                                        # 01 01 01 0b|0f
    n = struct.unpack_from('<H', pay, 4)[0]
    x0, y0 = struct.unpack_from('<2f', pay, 6)
    p = 14
    deltas = [(sm16(a), sm16(b)) for a, b in struct.iter_unpack('<HH', pay[p:p + 4 * (n - 1)])]
    p += 4 * (n - 1)
    f1 = struct.unpack_from('<f', pay, p)[0]; p += 4
    sec2 = [sm16(v) for v in struct.unpack_from('<%dH' % (n - 1), pay, p)]; p += 2 * (n - 1)
    sec3 = list(struct.unpack_from('<%dH' % n, pay, p)); p += 2 * n
    tail = pay[p:]
    pts = [(x0, y0)]
    x, y = x0, y0
    for dx, dy in deltas:
        x += dx / SCALE
        y += dy / SCALE
        pts.append((x, y))
    return dict(kind='stroke', A=A, B=B, flags5=flags5.hex(), rect=rect, pre5=pre5.hex(),
                plen=plen, hdr=hdr.hex(), n=n, points=pts, deltas=deltas,
                float1=f1, sec2=sec2, sec3=sec3, tail=tail.hex())


def parse_page(d):
    u0 = struct.unpack_from('<I', d, 0)[0]
    hdr_len = struct.unpack_from('<I', d, 4)[0]
    ver, fa, fb = struct.unpack_from('<HHH', d, 8)
    width = struct.unpack_from('<I', d, 0x0E)[0]
    nl = struct.unpack_from('<H', d, 0x12)[0]
    uuid = d[0x14:0x14 + 2 * nl].decode('utf-16le')
    ts_us = struct.unpack_from('<q', d, 0x14 + 2 * nl)[0]
    # PAGE metadata map (Density, PAGE_LAST_EDITED_TIME)
    meta = {}
    m = re.search(rb'.\x00\x00\x00\x01\x02\x00\x08\x00Density\x00', d, re.S)
    if m:
        meta, _ = read_kv_map(d, m.start())
    count, blk = struct.unpack_from('<II', d, u0)
    nobj = struct.unpack_from('<I', d, u0 + 8 + blk - 4)[0]
    pos = u0 + 8 + blk
    objs = []
    while pos < len(d):
        kind = d[pos]
        size = struct.unpack_from('<I', d, pos + 3)[0]
        body = d[pos + 7:pos + 7 + size]
        if kind == 1:
            objs.append(parse_stroke(body))
        else:
            strs = [s.decode('utf-16le') for s in re.findall(rb'(?:[\x20-\x7e]\x00){3,}', body)]
            objs.append(dict(kind='kind%d' % kind, raw=body, strings=strs))
        pos += 7 + size
    assert pos == len(d), "object chain does not end at EOF"
    assert len(objs) == nobj, "object count mismatch"
    return dict(uuid=uuid, width=width, flags=(ver, fa, fb), timestamp_us=ts_us,
                meta=meta, objects=objs)


def open_spd(path):
    z = zipfile.ZipFile(path)
    ids = read_pageids(z.read('pageIdInfo.dat'))
    pages = [parse_page(z.read(i + '.page')) for i in ids]
    return z, ids, pages


def render(filename, pages, outdir, scale=0.6):
    os.makedirs(outdir, exist_ok=True)
    for i, pg in enumerate(pages, 1):
        S = [o['points'] for o in pg['objects'] if o['kind'] == 'stroke']
        if not S:
            continue
        xs = [x for s in S for x, _ in s]; ys = [y for s in S for _, y in s]
        W, H = int(max(xs) + 40), int(max(ys) + 40)
        im = Image.new('RGB', (int(W * scale), int(H * scale)), 'white')
        dr = ImageDraw.Draw(im)
        for s in S:
            pts = [(x * scale, y * scale) for x, y in s]
            if len(pts) > 1:
                dr.line(pts, fill='black', width=2)
            else:
                dr.point(pts[0], fill='black')
        im.save(os.path.join(outdir, f"{filename}_page_{i:02d}.png"))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Parse SPD files')
    parser.add_argument('file', help='SPD file to parse')
    parser.add_argument('--render', help='Directory to render pages to')
    args = parser.parse_args()

    z, ids, pages = open_spd(args.file)
    print("files:", [i.filename for i in z.infolist() if not i.filename.endswith('.page')])
    for i, pg in enumerate(pages, 1):
        st = [o for o in pg['objects'] if o['kind'] == 'stroke']
        other = [o for o in pg['objects'] if o['kind'] != 'stroke']
        print("page %2d %s width=%d strokes=%d other=%d points=%d meta=%s" %
              (i, pg['uuid'][:8], pg['width'], len(st), len(other),
               sum(o['n'] for o in st), pg['meta']))
    if args.render:
        render(pathlib.Path(args.file).stem, pages, args.render)
        print("rendered to", args.render)