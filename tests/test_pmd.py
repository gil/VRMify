# -*- coding: utf-8 -*-
"""PMD to PMX: a tiny hand-built PMD goes through pmd2pmx and comes back as a valid PMX."""
import os
import shutil
import struct
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (os.path.join(ROOT, "convert"), os.path.join(ROOT, "formats")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import pmd2pmx  # noqa: E402
import pmdio  # noqa: E402
import pmxio  # noqa: E402


def fixed(text, size):
    return text.encode("cp932").ljust(size, b"\0")


def build_pmd():
    b = bytearray(b"Pmd" + struct.pack("<f", 1.0) + fixed("テスト", 20) + fixed("comment", 256))
    verts = [((0, 0, 0), 100, (0, 0)), ((1, 0, 0), 60, (0, 1)), ((0, 1, 0), 0, (0, 1))]
    b += struct.pack("<I", len(verts))
    for pos, weight, bones in verts:
        b += struct.pack("<8f2HBB", *pos, 0, 0, 1, 0, 0, bones[0], bones[1], weight, 0)
    b += struct.pack("<I3H", 3, 0, 1, 2)
    b += struct.pack("<I", 1)
    b += struct.pack("<4ff3f3fBBI", 1, 1, 1, 1, 5, 0, 0, 0, 0.5, 0.5, 0.5, 0, 0, 3) + fixed("Tex.BMP*s.spa", 20)
    bones = [("センター", 0xFFFF, 1, 1), ("左ひざ", 0, 2, 0), ("左足首", 1, 0xFFFF, 0)]
    b += struct.pack("<H", len(bones))
    for name, parent, tail, kind in bones:
        b += fixed(name, 20) + struct.pack("<HHBH3f", parent, tail, kind, 0, 0, kind, 0)
    b += struct.pack("<H", 1) + struct.pack("<HHBHf", 2, 2, 1, 40, 0.5) + struct.pack("<H", 1)
    b += struct.pack("<H", 2)
    b += fixed("base", 20) + struct.pack("<IB", 2, 0) + struct.pack("<I3f", 1, 0, 0, 0) + struct.pack("<I3f", 2, 0, 0, 0)
    b += fixed("あ", 20) + struct.pack("<IB", 1, 3) + struct.pack("<I3f", 1, 0, 0.5, 0)
    b += struct.pack("<B", 0) + struct.pack("<B", 0) + struct.pack("<I", 0)
    return bytes(b)


class PmdTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="m2v_pmd_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.src = os.path.join(self.tmp, "in")
        os.makedirs(self.src)
        with open(os.path.join(self.src, "model.pmd"), "wb") as f:
            f.write(build_pmd())
        with open(os.path.join(self.src, "tex.bmp"), "wb") as f:
            f.write(b"BM")

    def convert(self):
        out = os.path.join(self.tmp, "out", "model.pmx")
        logs = []
        pmd2pmx.convert(os.path.join(self.src, "model.pmd"), out, log=lambda m, t=None: logs.append((t, m)))
        return pmxio.read_pmx(out), logs

    def test_reader(self):
        m = pmdio.read_pmd(os.path.join(self.src, "model.pmd"))
        self.assertEqual((m["name"], len(m["vertices"]), len(m["faces"])), ("テスト", 3, 3))
        self.assertEqual([x["name"] for x in m["bones"]], ["センター", "左ひざ", "左足首"])

    def test_not_pmd(self):
        with open(os.path.join(self.src, "bad.pmd"), "wb") as f:
            f.write(b"PMX " + bytes(64))
        with self.assertRaises(ValueError):
            pmdio.read_pmd(os.path.join(self.src, "bad.pmd"))

    def test_converts_to_valid_pmx(self):
        m, logs = self.convert()
        self.assertEqual(m["consumed"], m["filesize"])
        self.assertEqual([v["wtype"] for v in m["vertices"]], [0, 1, 0])
        self.assertEqual(m["vertices"][2]["wbones"], [1])
        self.assertAlmostEqual(m["vertices"][1]["wweights"][0], 0.6)
        self.assertEqual([b["parent"] for b in m["bones"]], [-1, 0, 1])
        self.assertEqual(m["bones"][2]["tail_kind"], 0)
        self.assertEqual(m["bones"][0]["tail"], 1)

    def test_ik_morph_and_textures(self):
        m, logs = self.convert()
        ik = m["bones"][2]["ik"]
        self.assertEqual((ik["target"], ik["iterations"], ik["limit_angle"]), (2, 40, 2.0))
        self.assertIsNotNone(ik["links"][0]["min"])
        self.assertEqual([x["name"] for x in m["morphs"]], ["あ"])
        self.assertEqual(m["morphs"][0]["offsets"], [(2, (0.0, 0.5, 0.0))])
        self.assertEqual(m["textures"], ["textures/tex.bmp"])
        mat = m["materials"][0]
        self.assertEqual((mat["tex"], mat["sph"], mat["toon_flag"], mat["toon"]), (0, -1, 1, 0))
        self.assertTrue(any("s.spa" in msg for tag, msg in logs if tag == "warn"))
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "out", "textures", "tex.bmp")))


if __name__ == "__main__":
    unittest.main()
