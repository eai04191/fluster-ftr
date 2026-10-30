#!/usr/bin/env python3
"""List public symbols of an MSF 7.00 PDB as "RVA name" lines, corrected through OMAP.

Usage: pdb_publics.py shell32.pdb [substring] | sort

Vista's system DLLs were rearranged by BBT after linking, so the section offsets stored in
their PDBs point at pre-optimization addresses. This script maps them through the
OMAP_FROM_SRC stream to RVAs that match the shipped DLL, which any disassembler can then use.
Standard library only.
"""
import bisect
import struct
import sys

S_PUB32 = 0x110E


def streams(data):
    bs, _, _, dirsz, _, dirmap = struct.unpack_from('<6I', data, 32)
    dirblocks = struct.unpack_from('<%dI' % ((dirsz + bs - 1) // bs), data, dirmap * bs)
    d = b''.join(data[b * bs:(b + 1) * bs] for b in dirblocks)[:dirsz]
    n = struct.unpack_from('<I', d, 0)[0]
    sizes = struct.unpack_from('<%dI' % n, d, 4)
    off, out = 4 + 4 * n, []
    for sz in sizes:
        if sz == 0xFFFFFFFF:
            out.append(b'')
            continue
        nb = (sz + bs - 1) // bs
        blocks = struct.unpack_from('<%dI' % nb, d, off)
        off += 4 * nb
        out.append(b''.join(data[b * bs:(b + 1) * bs] for b in blocks)[:sz])
    return out


def publics(path):
    s = streams(open(path, 'rb').read())
    dbi = s[3]
    symrec = struct.unpack_from('<H', dbi, 20)[0]
    modinfo, seccontrib, secmap, srcinfo, tsmap = struct.unpack_from('<5I', dbi, 24)
    optsz, ecsz = struct.unpack_from('<II', dbi, 48)
    opt = 64 + modinfo + seccontrib + secmap + srcinfo + tsmap + ecsz
    dbg = struct.unpack_from('<%dH' % (optsz // 2), dbi, opt)
    omap_from, sec_hdr, sec_hdr_orig = dbg[4], dbg[5], dbg[10] if len(dbg) > 10 else 0xFFFF
    hdrs = s[sec_hdr_orig if sec_hdr_orig != 0xFFFF else sec_hdr]
    sec_va = [struct.unpack_from('<I', hdrs, i + 12)[0] for i in range(0, len(hdrs), 40)]
    om = s[omap_from] if omap_from != 0xFFFF else b''
    pairs = [struct.unpack_from('<II', om, i) for i in range(0, len(om), 8)]
    keys = [p[0] for p in pairs]

    def mapped(rva):
        if not pairs:
            return rva
        i = bisect.bisect_right(keys, rva) - 1
        if i < 0 or pairs[i][1] == 0:
            return None
        return pairs[i][1] + rva - pairs[i][0]

    rec, o = s[symrec], 0
    while o + 4 <= len(rec):
        ln, typ = struct.unpack_from('<HH', rec, o)
        if typ == S_PUB32:
            _, off, seg = struct.unpack_from('<IIH', rec, o + 4)
            name = rec[o + 14:rec.index(b'\0', o + 14)].decode('latin1')
            if 1 <= seg <= len(sec_va):
                rva = mapped(sec_va[seg - 1] + off)
                if rva is not None:
                    yield rva, name
        o += ln + 2


if __name__ == '__main__':
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    needle = sys.argv[2] if len(sys.argv) == 3 else ''
    for rva, name in publics(sys.argv[1]):
        if needle in name:
            print('%08x %s' % (rva, name))
