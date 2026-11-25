import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from make_min_axml import build  # noqa: E402

from samdex.axml import parse, patch_sdk  # noqa: E402


def test_parse_manifest_basics():
    data = build()
    m = parse(data)
    assert m.package == "com.example.test"
    assert m.min_sdk == 36
    assert m.target_sdk == "Baklava"
    assert [e.name for e in m.elements] == ["manifest", "uses-sdk"]


def test_patch_sdk_clamps_int_and_fixes_codename():
    data = build()
    patched, changes = patch_sdk(data, max_sdk=34)
    assert len(changes) == 2
    m2 = parse(patched)
    assert m2.min_sdk == 34
    assert m2.target_sdk == 34
    # byte length must be unchanged (in-place patch only)
    assert len(patched) == len(data)


def test_patch_sdk_noop_when_already_within_range():
    data = build()
    patched, changes = patch_sdk(build().replace(b"Baklava", b"Baklava"), max_sdk=40)
    # min_sdk(36) <= 40 and target is a codename string -> codename still gets fixed
    m2 = parse(patched)
    assert m2.min_sdk == 36  # untouched, already <= max_sdk
    assert m2.target_sdk == 40  # codename always resolved to an int


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
