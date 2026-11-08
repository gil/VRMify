# -*- coding: utf-8 -*-
"""pmdio.py - PMD 1.0 reader (old MMD model format, pure standard library).

read_pmd(path) returns a plain dict. Strings are decoded from Shift-JIS (cp932).
Every section after the bones is optional in old files, so a file may end early.
"""
import struct

SJIS = "cp932"


class _Reader:
    def __init__(self, data):
        self.d = data
        self.p = 0

    def left(self):
        return len(self.d) - self.p

    def unpack(self, fmt):
        st = struct.Struct("<" + fmt)
        if self.left() < st.size:
            raise ValueError("PMD ended early at byte %d (needs %d more)" % (self.p, st.size))
        v = st.unpack_from(self.d, self.p)
        self.p += st.size
        return v

    def one(self, fmt):
        return self.unpack(fmt)[0]

    def text(self, n):
        if self.left() < n:
            raise ValueError("PMD ended early at byte %d (text of %d bytes)" % (self.p, n))
        raw = self.d[self.p:self.p + n]
        self.p += n
        return raw.split(b"\0", 1)[0].decode(SJIS, "replace")


def read_pmd(path):
    with open(path, "rb") as f:
        r = _Reader(f.read())
    if r.d[:3] != b"Pmd":
        raise ValueError("Not a PMD file: %s" % path)
    r.p = 3
    m = {"version": r.one("f")}
    m["name"] = r.text(20)
    m["comment"] = r.text(256)

    vert = struct.Struct("<8f2HBB")
    m["vertices"] = []
    count = r.one("I")
    if r.left() < count * vert.size:
        raise ValueError("PMD vertex list is cut off")
    for v in vert.iter_unpack(r.d[r.p:r.p + count * vert.size]):
        m["vertices"].append({"pos": v[0:3], "normal": v[3:6], "uv": v[6:8],
                              "bones": (v[8], v[9]), "weight": v[10], "edge_off": v[11]})
    r.p += count * vert.size

    count = r.one("I")
    m["faces"] = list(r.unpack("%dH" % count))

    m["materials"] = []
    for _ in range(r.one("I")):
        v = r.unpack("4ff3f3fBBI")
        m["materials"].append({
            "diffuse": v[0:4], "shininess": v[4], "specular": v[5:8], "ambient": v[8:11],
            "toon": v[11], "edge": v[12], "index_count": v[13], "texture": r.text(20)})

    m["bones"] = []
    for _ in range(r.one("H")):
        name = r.text(20)
        parent, tail, kind, ik_parent = r.unpack("HHBH")
        m["bones"].append({"name": name, "parent": parent, "tail": tail, "type": kind,
                           "ik_parent": ik_parent, "pos": r.unpack("3f")})

    m["iks"] = []
    for _ in range(r.one("H")):
        bone, target, chain = r.unpack("HHB")
        iterations, weight = r.unpack("Hf")
        m["iks"].append({"bone": bone, "target": target, "iterations": iterations,
                         "weight": weight, "links": list(r.unpack("%dH" % chain))})

    m["morphs"] = []
    for _ in range(r.one("H")):
        name = r.text(20)
        count, kind = r.unpack("IB")
        offsets = []
        for _ in range(count):
            v = r.unpack("I3f")
            offsets.append((v[0], v[1:4]))
        m["morphs"].append({"name": name, "type": kind, "offsets": offsets})

    m["morph_display"] = list(r.unpack("%dH" % r.one("B")))
    m["bone_groups"] = [r.text(50) for _ in range(r.one("B"))]
    m["bone_display"] = [r.unpack("HB") for _ in range(r.one("I"))]

    m["name_en"] = ""
    m["comment_en"] = ""
    m["bone_names_en"] = []
    m["morph_names_en"] = []
    m["rigid_bodies"] = []
    m["joints"] = []
    if r.left() < 1:
        return m

    if r.one("B"):
        m["name_en"] = r.text(20)
        m["comment_en"] = r.text(256)
        m["bone_names_en"] = [r.text(20) for _ in m["bones"]]
        m["morph_names_en"] = [r.text(20) for _ in m["morphs"][1:]]
        for _ in m["bone_groups"]:
            r.text(50)

    if r.left() >= 1000:
        r.p += 1000                       # 10 custom toon texture names, unused here

    if r.left() < 4:
        return m
    for _ in range(r.one("I")):
        name = r.text(20)
        bone, group, mask, shape = r.unpack("HBHB")
        m["rigid_bodies"].append({
            "name": name, "bone": bone, "group": group, "mask": mask, "shape": shape,
            "size": r.unpack("3f"), "pos": r.unpack("3f"), "rot": r.unpack("3f"),
            "mass": r.one("f"), "move_damp": r.one("f"), "rot_damp": r.one("f"),
            "repulsion": r.one("f"), "friction": r.one("f"), "mode": r.one("B")})

    if r.left() < 4:
        return m
    for _ in range(r.one("I")):
        name = r.text(20)
        rb_a, rb_b = r.unpack("II")
        m["joints"].append({
            "name": name, "rb_a": rb_a, "rb_b": rb_b,
            "pos": r.unpack("3f"), "rot": r.unpack("3f"),
            "move_min": r.unpack("3f"), "move_max": r.unpack("3f"),
            "rot_min": r.unpack("3f"), "rot_max": r.unpack("3f"),
            "spring_move": r.unpack("3f"), "spring_rot": r.unpack("3f")})
    return m
