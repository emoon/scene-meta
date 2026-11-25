import pathlib
import tempfile
import unittest

from scenemeta.amiga import catalog, machines

DATA = """\
[demozoo.1]
title = "runs on the default"

[demozoo.2]
title = "runs on another"
machine = "a1200"

[demozoo.3]
title = "runs, then crashes"
machine = "a500_1mb"
result = "crashes-later"

[demozoo.4]
title = "nobody knows"
result = "unknown"

[demozoo.5]
title = "does not run"
result = "broken"
"""


class KnownMachinesTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = pathlib.Path(tmp.name)
        (self.data / "machines.toml").write_text(
            'default = "a500"\n[a500]\ncpu = "68000"\n[a1200]\ncpu = "68ec020"\n'
            '[a500_1mb]\ncpu = "68000"\n')
        (self.data / "a.toml").write_text(DATA)

    def test_an_entry_that_runs_names_its_machine_or_the_default(self):
        known = catalog.known_machines(self.data)
        self.assertEqual(known, {1: "a500", 2: "a1200", 3: "a500_1mb"})

    def test_an_aga_only_production_nobody_knows_keeps_its_aga_rungs(self):
        # Read as known on the default, its ladder began at a500, past
        # every A1200 (30467, The Black).
        start = catalog.known_machines(self.data).get(4)
        rungs = machines.ladder_for(True, self.data, start=start)
        self.assertEqual(rungs[0].name, "a1200")


if __name__ == "__main__":
    unittest.main()
