import os
import tempfile
import unittest

from scenedb import diskset


class Order(unittest.TestCase):
    def test_sides_in_natural_order(self):
        names = ["Mojo_Side10.D64", "Mojo_Side2.D64", "Mojo_Side1.D64"]
        self.assertEqual(diskset.order(names),
                         ["Mojo_Side1.D64", "Mojo_Side2.D64", "Mojo_Side10.D64"])

    def test_letter_markers(self):
        names = ["EdgeOfDisgrace_1b.d64", "EdgeOfDisgrace_0.d64",
                 "EdgeOfDisgrace_1a.d64"]
        self.assertEqual([n[15:-4] for n in diskset.order(names)],
                         ["0", "1a", "1b"])

    def test_one_file_per_disk_prefers_d64(self):
        got = diskset.order(["d1.g64", "d1.d64", "d2.g64"])
        self.assertEqual(got, ["d1.d64", "d2.g64"])

    def test_ignores_other_files(self):
        self.assertEqual(diskset.order(["readme.txt", "a.sid", "a.d64"]),
                         ["a.d64"])

    def test_ignores_macos_archive_junk(self):
        names = ["__MACOSX/demo/._a.d64", "demo/._b.d64", "demo/a.d64"]
        self.assertEqual(diskset.order(names), ["demo/a.d64"])

    def test_first_disk_sorts_before_numbered_ones(self):
        got = diskset.order(["portal2.d64", "portal.d64"])
        self.assertEqual(got, ["portal.d64", "portal2.d64"])


def _d64(files, label="x", spare=0, raw_tracks=0):
    """A 35-track d64 holding ``files`` ({name: bytes}), data from track 1."""
    img = bytearray(174848)
    zones = ((17, 21), (7, 19), (6, 18), (5, 17))

    def off(t, s_):
        o = 0
        for tracks, sectors in zones:
            if t <= tracks:
                return (o + (t - 1) * sectors + s_) * 256
            o += tracks * sectors
            t -= tracks
    img[off(18, 0) + 0x90:off(18, 0) + 0x90 + len(label)] = label.encode()
    free = [21] * 17 + [19] * 7 + [18] * 6 + [17] * 5
    free[17] = 0
    nxt = [(1, spare)]
    entries = []
    for name, body in files.items():
        chunks = [body[i:i + 254] for i in range(0, len(body), 254)] or [b""]
        first = nxt[0]
        for n, chunk in enumerate(chunks):
            t, s_ = nxt.pop(0)
            nxt.append((t, s_ + 1) if s_ < 20 else (t + 1, 0))
            at = off(t, s_)
            free[t - 1] -= 1
            if n + 1 < len(chunks):
                img[at], img[at + 1] = nxt[0]
            else:
                img[at], img[at + 1] = 0, len(chunk) + 1
            img[at + 2:at + 2 + len(chunk)] = chunk
        entries.append((name, first))
    for t in range(raw_tracks):          # data the directory does not list
        free[t + 19] = 0
    for t, n in enumerate(free):
        img[off(18, 0) + 4 + 4 * t] = n
    for i, (name, (t, s_)) in enumerate(entries):
        e = off(18, 1) + i * 32
        img[e + 2], img[e + 3], img[e + 4] = 0x82, t, s_
        img[e + 5:e + 5 + len(name)] = name.encode()
    img[off(18, 1)], img[off(18, 1) + 1] = 0, 255
    return bytes(img)


class Distinct(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def image(self, name, data):
        p = os.path.join(self.tmp.name, name)
        with open(p, "wb") as f:
            f.write(data)
        return p

    def test_byte_identical_copy_dropped(self):
        a = self.image("a.d64", _d64({"demo": b"1" * 600}))
        b = self.image("b.d64", _d64({"demo": b"1" * 600}))
        self.assertEqual(diskset.distinct([a, b]), [a])

    def test_same_files_in_another_wrapper_dropped(self):
        a = self.image("a.d64", _d64({"demo": b"1" * 600, "part": b"2" * 300}, "side 1"))
        b = self.image("b.d64", _d64({"part2": b"2" * 300, "demo2": b"1" * 600}, "tdd"))
        self.assertEqual(diskset.distinct([a, b]), [a])

    def test_different_files_kept(self):
        a = self.image("a.d64", _d64({"demo": b"1" * 600}))
        b = self.image("b.d64", _d64({"demo": b"1" * 600, "more": b"3" * 50}))
        self.assertEqual(diskset.distinct([a, b]), [a, b])

    def test_empty_disks_are_not_copies_of_each_other(self):
        a = self.image("a.d64", _d64({}))
        b = self.image("b.d64", _d64({}, "save"))
        self.assertEqual(diskset.distinct([a, b]), [a, b])

    def test_fake_directory_disks_are_not_copies(self):
        """Raw-track disks list one token file each; the data is elsewhere."""
        a = self.image("a.d64", _d64({"x": b"1"}, "side1", raw_tracks=4))
        b = self.image("b.d64", _d64({"x": b"1"}, "side2", raw_tracks=4))
        c = self.image("c.d64", _d64({"x": b"1"}, "side3"))
        self.assertEqual(diskset.distinct([a, b, c]), [a, b, c])

    def test_non_d64_compared_by_bytes_only(self):
        a = self.image("a.g64", b"G64" * 100)
        b = self.image("b.g64", b"G64" * 100 + b"x")
        self.assertEqual(diskset.distinct([a, b]), [a, b])


if __name__ == "__main__":
    unittest.main()
