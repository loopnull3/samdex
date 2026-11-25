"""Build a minimal, valid, hand-assembled DEX file (version 035) with no
external toolchain (no d8/dx/javac) -- just struct packing per the DEX
file format spec. Used by tests/test_dexfile.py to validate samdex.dexfile
against ground truth we control byte-for-byte.

Layout modelled: one class `LFoo;` extending `Ljava/lang/Object;` with:
  - static field  `BAR:I`
  - instance method `bar()V` { invoke-static {} LFoo;->baz()V ; return-void }
  - static method    `baz()V` { return-void }
This exercises: string/type/proto/field/method tables, class_def +
class_data_item, code_item + a real invoke-static instruction, and a
static field so apiindex's static/instance bookkeeping has something to
chew on.
"""

from __future__ import annotations

import hashlib
import struct
import zlib


def uleb128(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def sleb128(n: int) -> bytes:
    out = bytearray()
    more = True
    while more:
        b = n & 0x7F
        n >>= 7
        if (n == 0 and not (b & 0x40)) or (n == -1 and (b & 0x40)):
            more = False
        else:
            b |= 0x80
        out.append(b)
    return bytes(out)


def mutf8(s: str) -> bytes:
    out = bytearray()
    for ch in s:
        cp = ord(ch)
        if cp == 0:
            out += b"\xc0\x80"
        elif cp < 0x80:
            out.append(cp)
        elif cp < 0x800:
            out.append(0xC0 | (cp >> 6))
            out.append(0x80 | (cp & 0x3F))
        else:
            out.append(0xE0 | (cp >> 12))
            out.append(0x80 | ((cp >> 6) & 0x3F))
            out.append(0x80 | (cp & 0x3F))
    return bytes(out)


def build() -> bytes:
    strings = [
        "LFoo;", "Ljava/lang/Object;", "BAR", "I", "bar", "baz", "()V",
    ]
    sidx = {s: i for i, s in enumerate(strings)}
    types = ["LFoo;", "Ljava/lang/Object;", "I"]
    tidx = {t: i for i, t in enumerate(types)}
    # proto: shorty, return type idx, params_off(=0, no params)
    protos = [(sidx["()V"], tidx["LFoo;"] if False else None)]  # placeholder, filled below
    # single proto: ()V  shorty string reused from "()V" is wrong (shorty is "V"); add it
    strings.append("V")
    sidx = {s: i for i, s in enumerate(strings)}
    proto_list = [(sidx["V"], tidx["LFoo;"].__class__ and None)]

    # We only need ONE proto: ()V  -> shorty "V", return_type I (void has no type id;
    # use a dedicated "V" type entry since return type must be a type_id).
    types.append("V")
    tidx = {t: i for i, t in enumerate(types)}
    proto_shorty = sidx["V"]
    proto_return = tidx["V"]
    proto_params_off = 0
    protos = [(proto_shorty, proto_return, proto_params_off)]

    # field: LFoo;->BAR:I
    fields = [(tidx["LFoo;"], tidx["I"], sidx["BAR"])]
    # methods: LFoo;->bar()V (proto 0), LFoo;->baz()V (proto 0)
    methods = [
        (tidx["LFoo;"], 0, sidx["bar"]),
        (tidx["LFoo;"], 0, sidx["baz"]),
    ]
    BAR_METHOD, BAZ_METHOD = 0, 1

    # --- code items ---
    # baz()V: just return-void (op 0x0E), 1 code unit.
    baz_insns = struct.pack("<H", 0x000E)
    baz_code = struct.pack("<HHHHII", 0, 0, 0, 0, 0, 1) + baz_insns
    baz_code += b"\x00" * ((4 - len(baz_code) % 4) % 4)

    # bar()V: invoke-static {}, LFoo;->baz()V  (3 units) ; return-void (1 unit)
    # invoke-static: op=0x71, AA=0 (arg count), BBBB=method_idx, then arg regs packed (none)
    bar_insns = struct.pack("<HHH", (0x00 << 8) | 0x71, BAZ_METHOD, 0x0000) + struct.pack("<H", 0x000E)
    bar_code = struct.pack("<HHHHII", 0, 0, 0, 0, 0, 4) + bar_insns
    bar_code += b"\x00" * ((4 - len(bar_code) % 4) % 4)

    # --- class_data_item for LFoo; ---
    # static_fields: 1 entry (diff=field_idx 0, access_flags STATIC|PUBLIC)
    # instance_fields: 0
    # direct_methods: baz (STATIC|PUBLIC), diff = method_idx 1 (baz is index 1)
    # virtual_methods: bar (PUBLIC), diff = method_idx 0 (bar is index 0)
    ACC_PUBLIC, ACC_STATIC = 0x1, 0x8

    def encoded_field(field_idx_diff, access):
        return uleb128(field_idx_diff) + uleb128(access)

    def encoded_method(method_idx_diff, access, code_off):
        return uleb128(method_idx_diff) + uleb128(access) + uleb128(code_off)

    # we will fill code_off placeholders after layout is known; build class_data
    # in two passes: first compute sizes, then patch.

    class_data_prefix = uleb128(1) + uleb128(0) + uleb128(1) + uleb128(1)  # sf,if,dm,vm counts

    # --- layout the file ---
    HEADER_SIZE = 0x70
    ENDIAN = 0x12345678

    string_ids_off = HEADER_SIZE
    n_strings = len(strings)
    type_ids_off = string_ids_off + 4 * n_strings
    n_types = len(types)
    proto_ids_off = type_ids_off + 4 * n_types
    n_protos = len(protos)
    field_ids_off = proto_ids_off + 12 * n_protos
    n_fields = len(fields)
    method_ids_off = field_ids_off + 8 * n_fields
    n_methods = len(methods)
    class_defs_off = method_ids_off + 8 * n_methods
    n_classes = 1
    data_off = class_defs_off + 32 * n_classes

    # data section: string_data for each string, then code items, then class_data_item
    cursor = data_off
    string_data_offs = []
    string_data_blob = bytearray()
    for s in strings:
        string_data_offs.append(cursor)
        enc = mutf8(s)
        chunk = uleb128(len(s)) + enc + b"\x00"
        string_data_blob += chunk
        cursor += len(chunk)
    # align to 4 for code items
    pad = (4 - cursor % 4) % 4
    string_data_blob += b"\x00" * pad
    cursor += pad

    baz_code_off = cursor
    cursor += len(baz_code)
    bar_code_off = cursor
    cursor += len(bar_code)

    class_data = (class_data_prefix
                  + encoded_field(0, ACC_STATIC | ACC_PUBLIC)
                  + encoded_method(1, ACC_STATIC | ACC_PUBLIC, baz_code_off)   # direct: baz (idx 1, diff 1)
                  + encoded_method(0, ACC_PUBLIC, bar_code_off))                # virtual: bar (idx 0, diff 0)
    class_data_off = cursor
    cursor += len(class_data)

    file_size = cursor

    out = bytearray(file_size)

    def put(off, fmt, *vals):
        struct.pack_into(fmt, out, off, *vals)

    # string_ids
    for i, off in enumerate(string_data_offs):
        put(string_ids_off + 4 * i, "<I", off)
    # type_ids (type_id -> descriptor string idx)
    for i, t in enumerate(types):
        put(type_ids_off + 4 * i, "<I", sidx[t])
    # proto_ids
    for i, (shorty, ret, params) in enumerate(protos):
        put(proto_ids_off + 12 * i, "<III", shorty, ret, params)
    # field_ids
    for i, (cls, typ, name) in enumerate(fields):
        put(field_ids_off + 8 * i, "<HHI", cls, typ, name)
    # method_ids
    for i, (cls, proto, name) in enumerate(methods):
        put(method_ids_off + 8 * i, "<HHI", cls, proto, name)
    # class_defs: class_idx, access, super_idx, iface_off, src_off, ann_off, cd_off, static_values_off
    put(class_defs_off, "<8I", tidx["LFoo;"], ACC_PUBLIC, tidx["Ljava/lang/Object;"],
        0, 0xFFFFFFFF, 0, class_data_off, 0)

    out[data_off:data_off + len(string_data_blob)] = string_data_blob
    out[baz_code_off:baz_code_off + len(baz_code)] = baz_code
    out[bar_code_off:bar_code_off + len(bar_code)] = bar_code
    out[class_data_off:class_data_off + len(class_data)] = class_data

    # header: magic+version
    out[0:8] = b"dex\n035\x00"
    put(0x20, "<III", file_size, HEADER_SIZE, ENDIAN)  # checksum patched below, map_off=0 (fine for our parser)
    put(0x2C, "<17I",
        0, 0,                                    # link_size, link_off
        0,                                       # map_off (unused by our parser)
        n_strings, string_ids_off,
        n_types, type_ids_off,
        n_protos, proto_ids_off,
        n_fields, field_ids_off,
        n_methods, method_ids_off,
        n_classes, class_defs_off,
        0, data_off)

    # signature = sha1(bytes[32:]), checksum = adler32(bytes[12:])
    sig = hashlib.sha1(bytes(out[32:])).digest()
    out[0x0C:0x0C + 20] = sig
    checksum = zlib.adler32(bytes(out[12:])) & 0xFFFFFFFF
    put(0x08, "<I", checksum)

    return bytes(out)


if __name__ == "__main__":
    import sys
    data = build()
    path = sys.argv[1] if len(sys.argv) > 1 else "min.dex"
    with open(path, "wb") as fh:
        fh.write(data)
    print("wrote", path, len(data), "bytes")
