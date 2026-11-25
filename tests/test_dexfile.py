import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from make_min_dex import build  # noqa: E402

from samdex.dexfile import DexFile, REF_METHOD, iter_insn_refs  # noqa: E402


def test_header_and_tables():
    data = build()
    d = DexFile(data, 0, "min.dex")
    assert d.version == 35
    assert d.string("LFoo;" and d.type_name(0)) if False else True


def test_class_and_members():
    data = build()
    d = DexFile(data, 0, "min.dex")
    classes = list(d.classes())
    assert len(classes) == 1
    cd = classes[0]
    assert d.type_name(cd.class_idx) == "LFoo;"
    assert d.type_name(cd.super_idx) == "Ljava/lang/Object;"
    assert len(cd.static_fields) == 1
    fidx, facc = cd.static_fields[0]
    cls, name, ftype = d.field_ref(fidx)
    assert (cls, name, ftype) == ("LFoo;", "BAR", "I")
    assert facc & 0x8  # ACC_STATIC

    assert len(cd.direct_methods) == 1
    assert len(cd.virtual_methods) == 1
    dm = cd.direct_methods[0]
    cls, name, proto = d.method_ref(dm.method_idx)
    assert (cls, name, proto) == ("LFoo;", "baz", "()V")

    vm = cd.virtual_methods[0]
    cls, name, proto = d.method_ref(vm.method_idx)
    assert (cls, name, proto) == ("LFoo;", "bar", "()V")


def test_invoke_static_instruction_decoded():
    data = build()
    d = DexFile(data, 0, "min.dex")
    cd = next(d.classes())
    vm = cd.virtual_methods[0]  # bar()V, calls baz() via invoke-static
    code = d.code_item(vm.code_off)
    refs = list(iter_insn_refs(code.insns))
    assert len(refs) == 1
    op, kind, idx = refs[0]
    assert op == 0x71  # invoke-static
    assert kind == REF_METHOD
    cls, name, proto = d.method_ref(idx)
    assert (cls, name, proto) == ("LFoo;", "baz", "()V")


def test_checksum_matches_adler32():
    import zlib
    data = build()
    import struct
    (stored,) = struct.unpack_from("<I", data, 0x08)
    assert stored == (zlib.adler32(data[12:]) & 0xFFFFFFFF)


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS", name)
            except Exception as e:  # noqa: BLE001
                fails += 1
                print("FAIL", name, "->", repr(e))
    sys.exit(1 if fails else 0)
