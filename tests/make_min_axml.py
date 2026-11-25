"""Hand-assemble a minimal, valid binary AndroidManifest.xml (AXML) with
no aapt/aapt2 -- just struct packing per frameworks/base's
ResourceTypes.h chunk layout. Used by tests/test_axml.py to check
samdex.axml against ground truth we control byte-for-byte.

Builds:
    <manifest xmlns:android="http://schemas.android.com/apk/res/android"
              package="com.example.test">
        <uses-sdk android:minSdkVersion="36"
                  android:targetSdkVersion="Baklava" />
    </manifest>

minSdkVersion is a real TYPE_INT_DEC value (36) and targetSdkVersion is a
raw TYPE_STRING codename ("Baklava") -- on purpose, so the test exercises
both patch_sdk() branches (clamp an over-high int, and turn a codename
string into an int).
"""

from __future__ import annotations

import struct

RES_STRING_POOL = 0x0001
RES_XML = 0x0003
RES_XML_START_NS = 0x0100
RES_XML_END_NS = 0x0101
RES_XML_START_ELEMENT = 0x0102
RES_XML_END_ELEMENT = 0x0103
RES_XML_RESOURCE_MAP = 0x0180

TYPE_STRING = 0x03
TYPE_INT_DEC = 0x10

ATTR_MIN_SDK = 0x0101020C
ATTR_TARGET_SDK = 0x01010270

NO_INDEX = 0xFFFFFFFF


def _utf16_string_pool(strings: list[str]) -> bytes:
    offsets = []
    blob = bytearray()
    for s in strings:
        offsets.append(len(blob))
        units = s.encode("utf-16-le")
        n = len(units) // 2
        blob += struct.pack("<H", n) + units + b"\x00\x00"
    header_size = 28
    strings_start = header_size + 4 * len(strings)
    size = strings_start + len(blob)
    out = bytearray()
    out += struct.pack("<HHI", RES_STRING_POOL, header_size, size)
    out += struct.pack("<IIIII", len(strings), 0, 0, strings_start, 0)  # flags=0 -> UTF-16
    for off in offsets:
        out += struct.pack("<I", off)
    out += blob
    assert len(out) == size
    return bytes(out)


def _resource_map(ids: list[int]) -> bytes:
    header_size = 8
    size = header_size + 4 * len(ids)
    out = struct.pack("<HHI", RES_XML_RESOURCE_MAP, header_size, size)
    out += struct.pack("<%dI" % len(ids), *ids)
    return out


def _node_chunk(ctype: int, ext: bytes) -> bytes:
    header_size = 16  # common chunk hdr(8) + line/comment(8)
    size = header_size + len(ext)
    return struct.pack("<HHI", ctype, header_size, size) + b"\x00" * 8 + ext


def _start_ns(prefix_i: int, uri_i: int) -> bytes:
    return _node_chunk(RES_XML_START_NS, struct.pack("<II", prefix_i, uri_i))


def _end_ns(prefix_i: int, uri_i: int) -> bytes:
    return _node_chunk(RES_XML_END_NS, struct.pack("<II", prefix_i, uri_i))


def _end_element(ns_i: int, name_i: int) -> bytes:
    return _node_chunk(RES_XML_END_ELEMENT, struct.pack("<II", ns_i, name_i))


def _attr(ns_i: int, name_i: int, raw_i: int, dtype: int, data: int) -> bytes:
    return struct.pack("<IIIHBBI", ns_i, name_i, raw_i, 8, 0, dtype, data & 0xFFFFFFFF)


def _start_element(ns_i: int, name_i: int, attrs: list[bytes]) -> bytes:
    attr_start = 20
    attr_size = 20
    ext = struct.pack("<IIHHH", ns_i, name_i, attr_start, attr_size, len(attrs))
    ext += b"\x00" * 6  # idIndex, classIndex, styleIndex (unused by our parser)
    for a in attrs:
        ext += a
    return _node_chunk(RES_XML_START_ELEMENT, ext)


def build() -> bytes:
    strings = [
        "http://schemas.android.com/apk/res/android",  # 0
        "android",                                      # 1
        "manifest",                                      # 2
        "package",                                        # 3
        "com.example.test",                                # 4
        "uses-sdk",                                          # 5
        "minSdkVersion",                                      # 6
        "targetSdkVersion",                                    # 7
        "Baklava",                                               # 8
    ]
    URI, PFX, MANIFEST, PKG_ATTR, PKG_VAL, USES_SDK, MINSDK, TARGETSDK, BAKLAVA = range(9)

    resmap = [0] * 8  # covers string indices 0..7; index 8 ("Baklava") is a value, not an attr name
    resmap[MINSDK] = ATTR_MIN_SDK
    resmap[TARGETSDK] = ATTR_TARGET_SDK

    pkg_attr = _attr(NO_INDEX, PKG_ATTR, PKG_VAL, TYPE_STRING, PKG_VAL)
    manifest_start = _start_element(NO_INDEX, MANIFEST, [pkg_attr])

    min_attr = _attr(URI, MINSDK, NO_INDEX, TYPE_INT_DEC, 36)
    target_attr = _attr(URI, TARGETSDK, BAKLAVA, TYPE_STRING, BAKLAVA)
    uses_sdk_start = _start_element(NO_INDEX, USES_SDK, [min_attr, target_attr])
    uses_sdk_end = _end_element(NO_INDEX, USES_SDK)
    manifest_end = _end_element(NO_INDEX, MANIFEST)

    body = (
        _utf16_string_pool(strings)
        + _resource_map(resmap)
        + _start_ns(PFX, URI)
        + manifest_start
        + uses_sdk_start
        + uses_sdk_end
        + manifest_end
        + _end_ns(PFX, URI)
    )
    total = 8 + len(body)
    header = struct.pack("<HHI", RES_XML, 8, total)
    return header + body


if __name__ == "__main__":
    import sys
    data = build()
    path = sys.argv[1] if len(sys.argv) > 1 else "min_manifest.xml"
    with open(path, "wb") as fh:
        fh.write(data)
    print("wrote", path, len(data), "bytes")
