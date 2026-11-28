"""Execute the actual 68000 helper, fault-injecting the OS call boundary."""

import struct
import unittest
from scenemeta.amiga import workbench

try:
    import unicorn as cpu
    from unicorn import m68k_const as reg
except ImportError:
    cpu = None

# Optional: install unicorn to exercise machine code without ROMs or Amiberry.
CODE = workbench._ASSIGN_CODE
EXEC, DOS, ROOT, INFO = 0x8000, 0xa000, 0xb000, 0xc000
ENTRY, RETURN, ARGS, STACK = 0x10000, 0x18000, 0x20000, 0x1f0000
HANDLER, SAVED_REGS = 0x123400, 0x90000


class Dos:
    """Minimal DOS/Exec calls around the real helper, with leak accounting."""

    def __init__(self, version=34, alloc_fail=0, nodos=False, assign_fail=False):
        self.uc = cpu.Uc(cpu.UC_ARCH_M68K, cpu.UC_MODE_BIG_ENDIAN)
        self.uc.ctl_set_cpu_model(reg.UC_CPU_M68K_M68000)
        self.uc.mem_map(0, 0x200000)
        self.uc.mem_write(ENTRY, CODE)
        self.put(4, EXEC)
        self.put(DOS + 34, ROOT)
        self.put(ROOT + 24, INFO // 4)
        self.uc.mem_write(DOS + 20, struct.pack('>H', version))
        self.allocs = {}
        self.locks = {}
        self.next_alloc = 0x60000
        self.next_lock = 0x50000
        self.forbidden = 0
        self.alloc_fail = alloc_fail
        self.alloc_count = 0
        self.nodos = nodos
        self.assign_fail = assign_fail
        self.modern = {}
        self.closes = 0
        self.vectors = {
            EXEC - 552: self.open, EXEC - 414: self.close,
            EXEC - 198: self.alloc, EXEC - 210: self.free,
            EXEC - 132: self.forbid, EXEC - 138: self.permit,
            DOS - 84: self.lock, DOS - 90: self.unlock,
            DOS - 612: self.assign,
        }
        for addr in self.vectors:
            self.uc.mem_write(addr, bytes.fromhex('4e75'))  # RTS from a library vector
        self.uc.hook_add(cpu.UC_HOOK_CODE, self.hook)

    def put(self, addr, n):
        self.uc.mem_write(addr, struct.pack('>I', n))

    def get(self, addr):
        return struct.unpack('>I', self.uc.mem_read(addr, 4))[0]

    def r(self, reg):
        return self.uc.reg_read(reg)

    def ret(self, n):
        self.uc.reg_write(reg.UC_M68K_REG_D0, n)

    def text(self, addr):
        b = bytes(self.uc.mem_read(addr, 512))
        return b.split(b'\x00')[0].decode('latin-1')

    def hook(self, uc, addr, size, data):
        if addr == RETURN:
            uc.emu_stop()
        elif addr in self.vectors:
            self.vectors[addr]()

    def open(self):
        assert self.r(reg.UC_M68K_REG_D0) == 0
        self.ret(0 if self.nodos else DOS)

    def close(self):
        assert self.r(reg.UC_M68K_REG_A1) == DOS
        self.closes += 1

    def alloc(self):
        assert not self.forbidden
        self.alloc_count += 1
        if self.alloc_count == self.alloc_fail:
            self.ret(0)
            return
        size = self.r(reg.UC_M68K_REG_D0)
        p = self.next_alloc
        self.next_alloc += (size + 7) & ~7
        self.allocs[p] = size
        self.uc.mem_write(p, b'\x00' * size)
        self.ret(p)

    def free(self):
        assert not self.forbidden
        p = self.r(reg.UC_M68K_REG_A1)
        size = self.r(reg.UC_M68K_REG_D0)
        assert self.allocs.pop(p) == size, (p, size)
        self.ret(0)

    def forbid(self):
        assert self.forbidden == 0
        self.forbidden = 1

    def permit(self):
        assert self.forbidden == 1
        self.forbidden = 0

    def lock(self):
        assert not self.forbidden
        path = self.text(self.r(reg.UC_M68K_REG_D1))
        if path.startswith('missing'):
            self.ret(0)
            return
        p = self.next_lock
        self.next_lock += 32
        self.put(p + 12, HANDLER)
        self.locks[p // 4] = path
        self.ret(p // 4)

    def unlock(self):
        assert not self.forbidden
        self.locks.pop(self.r(reg.UC_M68K_REG_D1))
        self.ret(0)

    def assign(self):
        if self.assign_fail:
            self.ret(0)
            return
        name = self.text(self.r(reg.UC_M68K_REG_D1))
        lock = self.r(reg.UC_M68K_REG_D2)
        old = self.modern.get(name.lower())
        if old:
            self.locks.pop(old)
        self.modern[name.lower()] = lock
        self.ret(1)

    def call(self, args):
        args = args.encode() + b'\n\x00'
        self.uc.mem_write(ARGS, args)
        regs = [getattr(reg, f"UC_M68K_REG_{name}")
                for name in ("D2", "D3", "D4", "D5", "D6", "D7",
                             "A2", "A3", "A4", "A5", "A6")]
        self.uc.reg_write(reg.UC_M68K_REG_SR, 0)
        for i, r in enumerate(regs):
            self.uc.reg_write(r, SAVED_REGS + 4 * i)
        self.uc.reg_write(reg.UC_M68K_REG_A7, STACK)
        self.put(STACK, RETURN)
        self.uc.reg_write(reg.UC_M68K_REG_A0, ARGS)
        self.uc.reg_write(reg.UC_M68K_REG_D0, len(args) - 1)
        self.uc.emu_start(ENTRY, RETURN + 2, count=20000)
        assert self.r(reg.UC_M68K_REG_PC) == RETURN
        assert [self.r(r) for r in regs] == [SAVED_REGS + 4 * i for i in range(len(regs))]
        assert self.forbidden == 0
        return self.r(reg.UC_M68K_REG_D0)

    def nodes(self):
        p = self.get(INFO + 4) * 4
        out = {}
        while p:
            n = self.get(p + 40) * 4
            l = self.uc.mem_read(n, 1)[0]
            name = bytes(self.uc.mem_read(n + 1, l)).decode()
            out[name.lower()] = (self.get(p + 4),
                                 self.locks.get(self.get(p + 12)),
                                 self.get(p + 8))
            p = self.get(p) * 4
        return out


@unittest.skipIf(cpu is None, 'optional unicorn package executes the 68000 helper')
class AssignCpuTest(unittest.TestCase):

    def test_create_replace_case_and_spaces(self):
        d = Dos()
        self.assertEqual(d.call('WILD: Demo:first'), 0)
        self.assertEqual(d.call('wild: "Demo:second"'), 0)
        self.assertEqual(d.nodes(), {'wild': (1, 'Demo:second', HANDLER)})
        self.assertEqual(len(d.allocs), 2)
        self.assertEqual(len(d.locks), 1)
        self.assertEqual(d.call('"Space Name:" "Demo:has spaces"'), 0)
        self.assertEqual(d.nodes()['space name'][1], 'Demo:has spaces')
        self.assertEqual(d.call('HERE: ""'), 0)
        self.assertEqual(d.nodes()['here'][1], '')

    def test_lookup_walks_past_other_names_and_updates_without_leaks(self):
        d = Dos()
        for name in ("WILD", "other", "third"):
            self.assertEqual(d.call(f"{name}: first"), 0)
        self.assertEqual(d.call("wild: second"), 0)
        self.assertEqual(d.nodes()["wild"][1], "second")
        self.assertEqual(len(d.allocs), 6)
        self.assertEqual(len(d.locks), 3)

    def test_maximum_bcpl_name_and_distinct_punctuation(self):
        d = Dos()
        self.assertEqual(d.call("x" * 255 + ": first"), 0)
        self.assertEqual(d.call("A-: dash"), 0)
        self.assertEqual(d.call("AM: letter"), 0)
        self.assertEqual(d.nodes()["a-"][1], "dash")
        self.assertEqual(d.nodes()["am"][1], "letter")

    def test_failed_lock_retains_old_assign(self):
        d = Dos()
        d.call('WILD: first')
        self.assertEqual(d.call('WILD: missing:path'), 20)
        self.assertEqual(d.nodes()['wild'][1], 'first')
        self.assertEqual(len(d.allocs), 2)
        self.assertEqual(len(d.locks), 1)

    def test_each_allocation_failure_releases_every_resource(self):
        for failure in [1, 2]:
            with self.subTest(failure=failure):
                d = Dos(alloc_fail=failure)
                self.assertEqual(d.call('WILD: Demo:'), 20)
                self.assertEqual(d.allocs, {})
                self.assertEqual(d.locks, {})
                self.assertEqual(d.nodes(), {})
                self.assertEqual(d.closes, 1)

    def test_device_collision_frees_new_resources(self):
        d = Dos()
        d.call('DH0: first')
        node = d.get(INFO + 4) * 4
        d.put(node + 4, 0)
        self.assertEqual(d.call('dh0: second'), 20)
        self.assertEqual(len(d.allocs), 2)
        self.assertEqual(len(d.locks), 1)
        self.assertEqual(d.nodes()['dh0'][0:2], (0, 'first'))

    def test_no_dos_returns_failure_and_no_close(self):
        d = Dos(nodos=True)
        self.assertEqual(d.call('X: Demo:'), 20)
        self.assertEqual(d.closes, 0)

    def test_modern_dos_delegates_and_transfers_lock(self):
        d = Dos(version=39)
        self.assertEqual(d.call('WILD: Demo:'), 0)
        self.assertEqual(d.allocs, {})
        self.assertEqual(d.modern, {'wild': next(iter(d.locks))})
        self.assertEqual(d.closes, 1)

    def test_modern_failure_unlocks(self):
        d = Dos(version=40, assign_fail=True)
        self.assertEqual(d.call('X: Demo:'), 20)
        self.assertEqual(d.allocs, {})
        self.assertEqual(d.locks, {})

    def test_invalid_arguments_never_lock_or_allocate(self):
        for args in ['', 'no-colon', ': path', '"unclosed: x',
                     'X: "unclosed', 'x' * 256 + ': Demo:']:
            with self.subTest(args=args):
                d = Dos()
                self.assertEqual(d.call(args), 20)
                self.assertEqual(d.allocs, {})
                self.assertEqual(d.locks, {})


if __name__ == '__main__':
    unittest.main()
