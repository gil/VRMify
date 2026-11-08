# -*- coding: utf-8 -*-
"""pmd2pmx.py - convert an old MMD .pmd model to .pmx.

PMD and PMX share coordinates and units, so nothing is scaled or mirrored.
Textures are copied next to the PMX under `textures/`.

    python pmd2pmx.py model.pmd -o model.pmx
"""
import math
import os
import shutil
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_FORMATS = os.path.join(os.path.dirname(_HERE), "formats")
for _p in (_HERE, _FORMATS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pmdio  # noqa: E402
import pmxio  # noqa: E402

NO_INDEX = 0xFFFF
TEX_EXT = (".png", ".bmp", ".tga", ".jpg", ".jpeg", ".dds", ".sph", ".spa")
SPHERE_MODE = {".sph": 1, ".spa": 2}

ROTATE, MOVE, VISIBLE, OPERABLE, IK = 0x0002, 0x0004, 0x0008, 0x0010, 0x0020
INHERIT_ROTATE, FIXED_AXIS, TAIL_IS_BONE = 0x0100, 0x0400, 0x0001
BONE_FLAGS = {
    0: ROTATE | VISIBLE | OPERABLE,
    1: ROTATE | MOVE | VISIBLE | OPERABLE,
    2: ROTATE | MOVE | VISIBLE | OPERABLE | IK,
    3: ROTATE | VISIBLE | OPERABLE,
    4: ROTATE | VISIBLE | OPERABLE,
    5: ROTATE | VISIBLE | INHERIT_ROTATE,
    6: ROTATE,
    7: ROTATE,
    8: ROTATE | VISIBLE | OPERABLE | FIXED_AXIS,
    9: ROTATE | INHERIT_ROTATE,
}
IK_ANGLE_SCALE = 4.0
KNEE_LIMIT = ((-math.pi, 0.0, 0.0), (-math.radians(0.5), 0.0, 0.0))


def _log_default(msg, tag=None):
    print(msg)


def _bone_index(i, count):
    return i if i < count else -1


def _find_texture(folder, filename):
    """Case-insensitive lookup in the model folder and its direct subfolders."""
    base = os.path.basename(filename.replace("\\", "/")).lower()
    if not base:
        return None
    dirs = [folder] + [os.path.join(folder, d) for d in sorted(os.listdir(folder))
                       if os.path.isdir(os.path.join(folder, d))]
    for d in dirs:
        for f in os.listdir(d):
            if f.lower() == base and os.path.isfile(os.path.join(d, f)):
                return os.path.join(d, f)
    return None


def _vertices(src):
    out = []
    for v in src["vertices"]:
        b0, b1 = v["bones"]
        if v["weight"] >= 100 or b0 == b1:
            weights = {"wtype": 0, "wbones": [b0], "wweights": []}
        elif v["weight"] <= 0:
            weights = {"wtype": 0, "wbones": [b1], "wweights": []}
        else:
            weights = {"wtype": 1, "wbones": [b0, b1], "wweights": [v["weight"] / 100.0]}
        out.append({"pos": v["pos"], "normal": v["normal"], "uv": v["uv"], "add_uv": [],
                    "sdef": None, "edge": 0.0 if v["edge_off"] else 1.0, **weights})
    return out


def _bones(src):
    count = len(src["bones"])
    names_en = src["bone_names_en"]
    bones = []
    for i, b in enumerate(src["bones"]):
        kind = b["type"]
        flag = BONE_FLAGS.get(kind, BONE_FLAGS[0])
        has_tail = kind != 9 and 0 < b["tail"] < count
        bone = {"name": b["name"], "name_en": names_en[i] if i < len(names_en) and names_en[i] else b["name"],
                "pos": b["pos"], "parent": _bone_index(b["parent"], count), "layer": 0,
                "tail_kind": 1 if has_tail else 0, "tail": b["tail"] if has_tail else (0.0, 0.0, 0.0),
                "inherit_rot": None, "inherit_mov": None, "fixed_axis": None,
                "local_axis": None, "external": None, "ik": None}
        if has_tail:
            flag |= TAIL_IS_BONE
        if flag & INHERIT_ROTATE:
            ratio = b["tail"] / 100.0 if kind == 9 else 1.0
            bone["inherit_rot"] = (_bone_index(b["ik_parent"], count), ratio)
        if flag & FIXED_AXIS:
            axis = _unit_vector(b["pos"], src["bones"][b["tail"]]["pos"]) if has_tail else None
            if axis:
                bone["fixed_axis"] = axis
            else:
                flag &= ~FIXED_AXIS
        bone["flag"] = flag
        bones.append(bone)

    for ik in src["iks"]:
        links = []
        for link in ik["links"]:
            is_knee = "ひざ" in src["bones"][link]["name"]
            links.append({"bone": link, "min": KNEE_LIMIT[0] if is_knee else None,
                          "max": KNEE_LIMIT[1] if is_knee else None})
        bones[ik["bone"]]["ik"] = {"target": ik["target"], "iterations": ik["iterations"],
                                   "limit_angle": ik["weight"] * IK_ANGLE_SCALE, "links": links}
        bones[ik["bone"]]["flag"] |= IK
    return bones


def _unit_vector(a, b):
    d = [b[k] - a[k] for k in range(3)]
    length = math.sqrt(sum(x * x for x in d))
    return tuple(x / length for x in d) if length > 1e-9 else None


def _morphs(src):
    morphs = src["morphs"]
    if not morphs or morphs[0]["type"] != 0:
        return []
    base = [index for index, _ in morphs[0]["offsets"]]
    names_en = src["morph_names_en"]
    out = []
    for i, m in enumerate(morphs[1:]):
        offsets = [(base[index], pos) for index, pos in m["offsets"] if index < len(base)]
        en = names_en[i] if i < len(names_en) and names_en[i] else m["name"]
        out.append({"name": m["name"], "name_en": en, "panel": m["type"], "kind": 1,
                    "offsets": offsets})
    return out


def _frames(src, bone_count, morph_count):
    frames = [{"name": "Root", "name_en": "Root", "special": 1, "items": [(0, 0)]},
              {"name": "表情", "name_en": "Exp", "special": 1,
               "items": [(1, i) for i in range(morph_count)]}]
    for g, group in enumerate(src["bone_groups"], start=1):
        items = [(0, bone) for bone, frame in src["bone_display"] if frame == g and bone < bone_count]
        if items:
            frames.append({"name": group, "name_en": group, "special": 0, "items": items})
    return frames


def _physics(src, bone_count):
    bodies = [dict(rb, bone=_bone_index(rb["bone"], bone_count), name_en=rb["name"])
              for rb in src["rigid_bodies"]]
    joints = [dict(j, name_en=j["name"], type=0) for j in src["joints"]]
    return bodies, joints


class _Textures:
    def __init__(self, folder, out_dir):
        self.folder = folder
        self.dir = os.path.join(out_dir, "textures")
        self.paths = []
        self.slots = {}
        self.missing = []

    def slot(self, filename):
        key = os.path.basename(filename.replace("\\", "/")).lower()
        if key not in self.slots:
            self.slots[key] = self._add(filename)
        return self.slots[key]

    def _add(self, filename):
        real = _find_texture(self.folder, filename)
        if real is None or os.path.splitext(real)[1].lower() not in TEX_EXT:
            self.missing.append(os.path.basename(filename))
            return -1
        os.makedirs(self.dir, exist_ok=True)
        name = os.path.basename(real)
        shutil.copyfile(real, os.path.join(self.dir, name))
        self.paths.append("textures/" + name)
        return len(self.paths) - 1


def _materials(src, textures, enable_edge, force_double_sided):
    out = []
    for i, m in enumerate(src["materials"]):
        tex, sph, sph_mode = -1, -1, 0
        for part in (p for p in m["texture"].split("*") if p):
            ext = os.path.splitext(part)[1].lower()
            if ext in SPHERE_MODE:
                sph, sph_mode = textures.slot(part), SPHERE_MODE[ext]
            else:
                tex = textures.slot(part)
        alpha = m["diffuse"][3]
        flag = 0x0E
        if force_double_sided or alpha < 0.999:
            flag |= 0x01
        if enable_edge and m["edge"]:
            flag |= 0x10
        shared_toon = m["toon"] < 10
        name = "mat%d" % i
        out.append({"name": name, "name_en": name, "diffuse": m["diffuse"], "specular": m["specular"],
                    "shininess": m["shininess"], "ambient": m["ambient"], "flag": flag,
                    "edge_color": (0.0, 0.0, 0.0, 1.0), "edge_size": 1.0 if m["edge"] else 0.0,
                    "tex": tex, "sph": sph, "sph_mode": sph_mode,
                    "toon_flag": 1 if shared_toon else 0, "toon": m["toon"] if shared_toon else -1,
                    "memo": "", "faces": m["index_count"]})
    return out


def convert(path, out_path, log=None, name=None, enable_edge=False, force_double_sided=False):
    log = log or _log_default
    src = pmdio.read_pmd(path)
    out_dir = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(out_dir, exist_ok=True)
    textures = _Textures(os.path.dirname(os.path.abspath(path)), out_dir)

    stem = os.path.splitext(os.path.basename(path))[0]
    model = pmxio.new_model(name or stem)
    model["name_en"] = src["name_en"] or src["name"] or stem
    model["comment"] = src["comment"]
    model["comment_en"] = src["comment_en"]
    model["vertices"] = _vertices(src)
    model["faces"] = src["faces"]
    model["bones"] = _bones(src)
    model["materials"] = _materials(src, textures, enable_edge, force_double_sided)
    model["textures"] = textures.paths
    model["morphs"] = _morphs(src)
    model["frames"] = _frames(src, len(model["bones"]), len(model["morphs"]))
    model["rigid_bodies"], model["joints"] = _physics(src, len(model["bones"]))
    if not enable_edge:
        pmxio.strip_edges(model, force_double_sided=False)

    size = pmxio.write_pmx(model, out_path)
    if textures.missing:
        log("Textures not found next to the model: %s" % " / ".join(textures.missing[:8]), "warn")
    log("Wrote %s (%.2f MB): %d vertices, %d bones, %d materials, %d morphs"
        % (os.path.basename(out_path), size / 1048576.0, len(model["vertices"]),
           len(model["bones"]), len(model["materials"]), len(model["morphs"])), "ok")
    return {"bytes": size, "vertices": len(model["vertices"]), "bones": len(model["bones"]),
            "materials": len(model["materials"]), "morphs": len(model["morphs"]),
            "textures": len(textures.paths)}


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="PMD to PMX")
    ap.add_argument("src")
    ap.add_argument("-o", "--out")
    ap.add_argument("--edge", action="store_true", help="keep the outline")
    a = ap.parse_args()
    convert(a.src, a.out or os.path.splitext(a.src)[0] + ".pmx", enable_edge=a.edge)
