#!/usr/bin/env python3
"""Extract and parse Fluster FTR animations from Windows Vista DLLs.

Usage:
  ftr.py info    <shell32.dll | shellstyle.dll | file.ftr> ...
  ftr.py extract <dll> <output-dir>
  ftr.py json    <file.ftr | dll> [resource-id]

Standard library only. The layout mirrors SWF::SWF::read in Vista's shell32.dll; see FORMAT.md.
"""
import json
import os
import struct
import sys
from collections import Counter


# ---- PE resources ----------------------------------------------------------

def pe_resources(data):
    """Return [(type, name, lang, bytes)] for every resource, or None if data is not a PE image."""
    if data[:2] != b'MZ':
        return None
    pe = struct.unpack_from('<I', data, 0x3C)[0]
    if data[pe:pe + 4] != b'PE\0\0':
        return None
    nsec, optsz = struct.unpack_from('<H', data, pe + 6)[0], struct.unpack_from('<H', data, pe + 20)[0]
    opt = pe + 24
    magic = struct.unpack_from('<H', data, opt)[0]
    rsrc_rva = struct.unpack_from('<I', data, opt + (96 if magic == 0x10B else 112) + 16)[0]
    secs = [struct.unpack_from('<IIII', data, opt + optsz + i * 40 + 8) for i in range(nsec)]

    def rva2off(rva):
        for vsz, va, rsz, ptr in secs:
            if va <= rva < va + max(vsz, rsz):
                return rva - va + ptr
        raise ValueError('RVA 0x%x is outside every section' % rva)

    base = rva2off(rsrc_rva)

    def name_of(v):
        if not v & 0x80000000:
            return v
        o = base + (v & 0x7FFFFFFF)
        n = struct.unpack_from('<H', data, o)[0]
        return data[o + 2:o + 2 + n * 2].decode('utf-16le')

    out = []

    def walk(off, path):
        named, ids = struct.unpack_from('<HH', data, base + off + 12)
        for i in range(named + ids):
            nm, tgt = struct.unpack_from('<II', data, base + off + 16 + i * 8)
            key = name_of(nm)
            if tgt & 0x80000000:
                walk(tgt & 0x7FFFFFFF, path + [key])
            else:
                rva, size = struct.unpack_from('<II', data, base + tgt)
                o = rva2off(rva)
                out.append((path[0], path[1], key, data[o:o + size]))

    walk(0, [])
    return out


def ftr_resources(path):
    """Return [(resource_id, bytes)] from a DLL, or [(file stem, bytes)] for a loose .ftr file."""
    data = open(path, 'rb').read()
    res = pe_resources(data)
    if res is None:
        return [(os.path.splitext(os.path.basename(path))[0], data)]
    return [(name, blob) for typ, name, _, blob in res if typ == 'FTR']


# ---- FTR -------------------------------------------------------------------

class Reader:
    def __init__(self, b):
        self.b, self.o = b, 0

    def take(self, fmt):
        v = struct.unpack_from('<' + fmt, self.b, self.o)
        self.o += struct.calcsize('<' + fmt)
        return v if len(v) > 1 else v[0]

    def color(self):
        return list(self.take('4B'))  # R, G, B, A

    def matrix(self):
        return list(self.take('6f'))  # m11, m12, m21, m22, dx, dy

    def list(self, fn):
        return [fn() for _ in range(self.take('I'))]


BRUSH_SOLID, BRUSH_PATH_GRADIENT, BRUSH_LINEAR_GRADIENT = 0, 3, 4


def read_brush(r):
    t = r.take('I')
    if t == BRUSH_SOLID:
        return {'type': 'solid', 'color': r.color()}
    if t in (BRUSH_PATH_GRADIENT, BRUSH_LINEAR_GRADIENT):
        stops = r.list(lambda: {'color': r.color(), 'position': r.take('f')})
        return {'type': 'path_gradient' if t == BRUSH_PATH_GRADIENT else 'linear_gradient',
                'stops': stops, 'matrix': r.matrix()}
    raise ValueError('unsupported brush type %d at offset 0x%x' % (t, r.o - 4))


def read_shape(r):
    return {
        'pens': r.list(lambda: {'color': r.color(), 'width': r.take('f')}),
        'brushes': r.list(lambda: read_brush(r)),
        'paths': r.list(lambda: r.list(lambda: list(r.take('ffB')))),
        'actions': r.list(lambda: list(r.take('Ii'))),
    }


def read_tag(r):
    at, tid = r.o, r.take('I')
    if tid == 1:
        return {'tag': 'ShowFrame'}
    if tid == 9:
        return {'tag': 'SetBackgroundColor', 'color': r.color()}
    if tid in (2, 22, 32):
        return {'tag': 'DefineShape', 'id': r.take('H'), 'shape': read_shape(r)}
    if tid == 39:
        return {'tag': 'DefineSprite', 'id': r.take('H'), 'tags': r.list(lambda: read_tag(r))}
    if tid == 26:
        t = {'tag': 'PlaceObject2'}
        for k in ('hasClipDepth', 'hasColorTransform', 'hasMatrix', 'hasCharacter', 'unused'):
            t[k] = r.take('B')
        t['depth'], t['characterId'], t['clipDepth'] = r.take('3H')
        if t['hasMatrix']:
            t['matrix'] = r.matrix()
        if t['hasColorTransform']:
            t['colorTransform'] = list(r.take('8f'))  # mulR, addR, mulG, addG, mulB, addB, mulA, addA
        return t
    if tid == 28:
        return {'tag': 'RemoveObject2', 'depth': r.take('H')}
    if tid == 12:
        return {'tag': 'DoAction', 'action': r.take('I'), 'frame': r.take('H')}
    raise ValueError('unsupported tag %d at offset 0x%x' % (tid, at))


def parse(b):
    r = Reader(b)
    movie = {'rect': list(r.take('4i')), 'fps': r.take('d')}
    movie['tags'] = r.list(lambda: read_tag(r))
    if r.o != len(b):
        raise ValueError('%d trailing bytes' % (len(b) - r.o))
    return movie


def summary(movie):
    c = Counter()

    def walk(tags):
        for t in tags:
            c[t['tag']] += 1
            if t['tag'] == 'DefineSprite':
                walk(t['tags'])
    walk(movie['tags'])
    frames = sum(1 for t in movie['tags'] if t['tag'] == 'ShowFrame')
    x, y, w, h = movie['rect']
    return '%g x %g px, %g fps, %d root frames; %s' % (
        w / 20, h / 20, movie['fps'], frames, ', '.join('%s %d' % kv for kv in sorted(c.items())))


def main(argv):
    if len(argv) < 3 or argv[1] not in ('info', 'extract', 'json'):
        sys.exit(__doc__)
    cmd = argv[1]
    if cmd == 'info':
        for path in argv[2:]:
            res = ftr_resources(path)
            if not res:
                print('%s: no FTR resources' % os.path.basename(path), file=sys.stderr)
            for rid, blob in res:
                print('%s FTR %s: %s' % (os.path.basename(path), rid, summary(parse(blob))))
    elif cmd == 'extract':
        if len(argv) != 4:
            sys.exit(__doc__)
        os.makedirs(argv[3], exist_ok=True)
        stem = os.path.splitext(os.path.basename(argv[2]))[0]
        for rid, blob in ftr_resources(argv[2]):
            parse(blob)  # refuse to write anything that does not parse
            out = os.path.join(argv[3], '%s_%s.ftr' % (stem, rid))
            open(out, 'wb').write(blob)
            print(out)
    else:
        res = ftr_resources(argv[2])
        if len(argv) > 3:
            res = [(rid, b) for rid, b in res if str(rid) == argv[3]]
        if len(res) != 1:
            sys.exit('pick one resource id: %s' % ', '.join(str(rid) for rid, _ in ftr_resources(argv[2])))
        json.dump(parse(res[0][1]), sys.stdout, indent=1)
        print()


if __name__ == '__main__':
    main(sys.argv)
