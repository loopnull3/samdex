"""Minimal dependency-free DEX parser.

Supports DEX versions 035-041 (041 = container format, several dex
sections in one file). Only what the API scanner needs is decoded:
strings, types, protos, field/method ids, class defs, class data and
code items, plus an instruction walker that yields referenced
method/field/type/string indices.
"""

from __future__ import annotations

import array
import struct
import sys
import zipfile
from dataclasses import dataclass, field
from typing import Iterator

NO_INDEX = 0xFFFFFFFF

ACC_PUBLIC = 0x1
ACC_PRIVATE = 0x2
ACC_PROTECTED = 0x4
ACC_STATIC = 0x8
ACC_FINAL = 0x10
ACC_INTERFACE = 0x200
ACC_ABSTRACT = 0x400
ACC_CONSTRUCTOR = 0x10000

REF_METHOD = 1
REF_FIELD = 2
REF_TYPE = 3
REF_STRING = 4


class DexError(ValueError):
    pass


def read_uleb128(buf: bytes, off: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        b = buf[off]
        off += 1
        result |= (b & 0x7F) << shift
        if b < 0x80:
            return result, off
        shift += 7
        if shift > 35:
            raise DexError("malformed uleb128")


def decode_mutf8(raw: bytes) -> str:
    """Decode Modified UTF-8 (CESU-8 style surrogates, 0xC0 0x80 for NUL)."""
    try:
        return raw.decode("ascii")
    except UnicodeDecodeError:
        pass
    units: list[int] = []
    i = 0
    n = len(raw)
    while i < n:
        a = raw[i]
        if a < 0x80:
            units.append(a)
            i += 1
        elif (a & 0xE0) == 0xC0 and i + 1 < n:
            units.append(((a & 0x1F) << 6) | (raw[i + 1] & 0x3F))
            i += 2
        elif (a & 0xF0) == 0xE0 and i + 2 < n:
            units.append(((a & 0x0F) << 12) | ((raw[i + 1] & 0x3F) << 6) | (raw[i + 2] & 0x3F))
            i += 3
        else:
            raise DexError("malformed MUTF-8 string")
    return struct.pack("<%dH" % len(units), *units).decode("utf-16-le", "surrogatepass")


# --- Dalvik instruction tables -------------------------------------------

def _build_tables() -> tuple[list[int], list[int]]:
    units = [1] * 256
    kinds = [0] * 256

    def put(lo: int, hi: int, size: int, kind: int = 0) -> None:
        for op in range(lo, hi + 1):
            units[op] = size
            kinds[op] = kind

    put(0x00, 0x01, 1)
    put(0x02, 0x02, 2)
    put(0x03, 0x03, 3)
    put(0x04, 0x04, 1)
    put(0x05, 0x05, 2)
    put(0x06, 0x06, 3)
    put(0x07, 0x07, 1)
    put(0x08, 0x08, 2)
    put(0x09, 0x09, 3)
    put(0x0A, 0x12, 1)          # move-result*, return*, const/4
    put(0x13, 0x13, 2)          # const/16
    put(0x14, 0x14, 3)          # const
    put(0x15, 0x16, 2)          # const/high16, const-wide/16
    put(0x17, 0x17, 3)          # const-wide/32
    put(0x18, 0x18, 5)          # const-wide
    put(0x19, 0x19, 2)          # const-wide/high16
    put(0x1A, 0x1A, 2, REF_STRING)
    put(0x1B, 0x1B, 3, REF_STRING)
    put(0x1C, 0x1C, 2, REF_TYPE)
    put(0x1D, 0x1E, 1)
    put(0x1F, 0x20, 2, REF_TYPE)  # check-cast, instance-of
    put(0x21, 0x21, 1)
    put(0x22, 0x23, 2, REF_TYPE)  # new-instance, new-array
    put(0x24, 0x25, 3, REF_TYPE)  # filled-new-array(/range)
    put(0x26, 0x26, 3)
    put(0x27, 0x28, 1)
    put(0x29, 0x29, 2)
    put(0x2A, 0x2C, 3)
    put(0x2D, 0x3D, 2)          # cmp*, if-*
    put(0x3E, 0x43, 1)
    put(0x44, 0x51, 2)          # aget/aput
    put(0x52, 0x6D, 2, REF_FIELD)  # iget/iput/sget/sput
    put(0x6E, 0x72, 3, REF_METHOD)
    put(0x73, 0x73, 1)
    put(0x74, 0x78, 3, REF_METHOD)
    put(0x79, 0x7A, 1)
    put(0x7B, 0x8F, 1)
    put(0x90, 0xAF, 2)
    put(0xB0, 0xCF, 1)
    put(0xD0, 0xE2, 2)
    put(0xE3, 0xF9, 1)
    put(0xFA, 0xFB, 4, REF_METHOD)  # invoke-polymorphic(/range)
    put(0xFC, 0xFD, 3)              # invoke-custom (call site, ignored)
    put(0xFE, 0xFF, 2)              # const-method-handle/type
    return units, kinds


OP_UNITS, OP_REF_KIND = _build_tables()

INVOKE_KIND = {
    0x6E: "virtual", 0x74: "virtual",
    0x6F: "super", 0x75: "super",
    0x70: "direct", 0x76: "direct",
    0x71: "static", 0x77: "static",
    0x72: "interface", 0x78: "interface",
    0xFA: "polymorphic", 0xFB: "polymorphic",
}


def field_op_kind(op: int) -> str:
    if 0x52 <= op <= 0x58:
        return "iget"
    if 0x59 <= op <= 0x5F:
        return "iput"
    if 0x60 <= op <= 0x66:
        return "sget"
    return "sput"


def iter_insn_refs(insns) -> Iterator[tuple[int, int, int]]:
    """Yield (opcode, ref_kind, index) for every referencing instruction."""
    pc = 0
    n = len(insns)
    try:
        while pc < n:
            unit = insns[pc]
            op = unit & 0xFF
            if op == 0:
                if unit == 0x0100:          # packed-switch-payload
                    pc += 4 + insns[pc + 1] * 2
                    continue
                if unit == 0x0200:          # sparse-switch-payload
                    pc += 2 + insns[pc + 1] * 4
                    continue
                if unit == 0x0300:          # fill-array-data-payload
                    width = insns[pc + 1]
                    size = insns[pc + 2] | (insns[pc + 3] << 16)
                    pc += 4 + (size * width + 1) // 2
                    continue
                pc += 1
                continue
            kind = OP_REF_KIND[op]
            if kind:
                if op == 0x1B:
                    idx = insns[pc + 1] | (insns[pc + 2] << 16)
                else:
                    idx = insns[pc + 1]
                yield op, kind, idx
            pc += OP_UNITS[op]
    except IndexError as exc:
        raise DexError("truncated instruction stream at pc=%d" % pc) from exc


# --- data model --------------------------------------------------------------

@dataclass
class EncodedMethod:
    method_idx: int
    access: int
    code_off: int


@dataclass
class ClassDef:
    class_idx: int
    access: int
    super_idx: int
    interfaces: list[int]
    static_fields: list[tuple[int, int]] = field(default_factory=list)
    instance_fields: list[tuple[int, int]] = field(default_factory=list)
    direct_methods: list[EncodedMethod] = field(default_factory=list)
    virtual_methods: list[EncodedMethod] = field(default_factory=list)


@dataclass
class CodeItem:
    registers: int
    ins: int
    outs: int
    insns: array.array


class DexFile:
    def __init__(self, data: bytes, base: int = 0, name: str = ""):
        self.data = data
        self.base = base
        self.name = name
        magic = data[base:base + 8]
        if len(magic) < 8 or magic[:4] != b"dex\n" or magic[7] != 0:
            raise DexError("%s: not a dex file" % (name or "<buffer>"))
        try:
            self.version = int(magic[4:7])
        except ValueError as exc:
            raise DexError("bad dex version %r" % magic[4:7]) from exc
        (self.file_size, self.header_size, endian) = struct.unpack_from("<III", data, base + 0x20)
        if endian != 0x12345678:
            raise DexError("unsupported endian tag 0x%08x" % endian)
        (_link_size, _link_off, self.map_off,
         n_str, off_str, n_type, off_type, n_proto, off_proto,
         n_field, off_field, n_method, off_method,
         n_class, off_class, _data_size, _data_off) = struct.unpack_from("<17I", data, base + 0x2C)
        if self.version >= 41 and self.header_size >= 0x78:
            self.container_size, self.header_offset = struct.unpack_from("<II", data, base + 0x70)
        else:
            self.container_size, self.header_offset = len(data), base
        # In 035-040 offsets are relative to the file start (base is 0).
        # In 041 containers offsets are relative to the container start.
        self.string_ids = struct.unpack_from("<%dI" % n_str, data, off_str) if n_str else ()
        self.type_ids = struct.unpack_from("<%dI" % n_type, data, off_type) if n_type else ()
        self.protos = [struct.unpack_from("<III", data, off_proto + 12 * i) for i in range(n_proto)]
        self.field_ids = [struct.unpack_from("<HHI", data, off_field + 8 * i) for i in range(n_field)]
        self.method_ids = [struct.unpack_from("<HHI", data, off_method + 8 * i) for i in range(n_method)]
        self._class_defs_off = off_class
        self._n_class = n_class
        self._strings: list[str | None] = [None] * n_str
        self._proto_cache: dict[int, str] = {}

    # --- containers ---------------------------------------------------------
    @classmethod
    def load_all(cls, data: bytes, name: str = "") -> list["DexFile"]:
        first = cls(data, 0, name)
        out = [first]
        if first.version >= 41:
            off = first.header_offset + first.file_size
            while off + 0x70 <= first.container_size and data[off:off + 4] == b"dex\n":
                d = cls(data, off, "%s@%d" % (name, off))
                out.append(d)
                if d.file_size == 0:
                    break
                off = d.header_offset + d.file_size
        return out

    # --- id accessors -----------------------------------------------------------
    def string(self, idx: int) -> str:
        s = self._strings[idx]
        if s is None:
            off = self.string_ids[idx]
            _, off = read_uleb128(self.data, off)
            end = self.data.index(b"\x00", off)
            s = decode_mutf8(self.data[off:end])
            self._strings[idx] = s
        return s

    def type_name(self, idx: int) -> str:
        return self.string(self.type_ids[idx])

    def type_list(self, off: int) -> list[int]:
        if off == 0:
            return []
        (size,) = struct.unpack_from("<I", self.data, off)
        return list(struct.unpack_from("<%dH" % size, self.data, off + 4)) if size else []

    def proto_desc(self, idx: int) -> str:
        cached = self._proto_cache.get(idx)
        if cached is None:
            _shorty, ret_idx, params_off = self.protos[idx]
            params = "".join(self.type_name(t) for t in self.type_list(params_off))
            cached = "(%s)%s" % (params, self.type_name(ret_idx))
            self._proto_cache[idx] = cached
        return cached

    def method_ref(self, idx: int) -> tuple[str, str, str]:
        class_idx, proto_idx, name_idx = self.method_ids[idx]
        return self.type_name(class_idx), self.string(name_idx), self.proto_desc(proto_idx)

    def field_ref(self, idx: int) -> tuple[str, str, str]:
        class_idx, type_idx, name_idx = self.field_ids[idx]
        return self.type_name(class_idx), self.string(name_idx), self.type_name(type_idx)

    # --- class defs -----------------------------------------------------------
    def classes(self) -> Iterator[ClassDef]:
        data = self.data
        for i in range(self._n_class):
            (class_idx, access, super_idx, ifaces_off, _src, _ann,
             class_data_off, _static_values) = struct.unpack_from("<8I", data, self._class_defs_off + 32 * i)
            cd = ClassDef(class_idx, access, super_idx, self.type_list(ifaces_off))
            if class_data_off:
                off = class_data_off
                n_sf, off = read_uleb128(data, off)
                n_if, off = read_uleb128(data, off)
                n_dm, off = read_uleb128(data, off)
                n_vm, off = read_uleb128(data, off)
                for count, target in ((n_sf, cd.static_fields), (n_if, cd.instance_fields)):
                    idx = 0
                    for _ in range(count):
                        diff, off = read_uleb128(data, off)
                        acc, off = read_uleb128(data, off)
                        idx += diff
                        target.append((idx, acc))
                for count, mtarget in ((n_dm, cd.direct_methods), (n_vm, cd.virtual_methods)):
                    idx = 0
                    for _ in range(count):
                        diff, off = read_uleb128(data, off)
                        acc, off = read_uleb128(data, off)
                        code_off, off = read_uleb128(data, off)
                        idx += diff
                        mtarget.append(EncodedMethod(idx, acc, code_off))
            yield cd

    def code_item(self, off: int) -> CodeItem:
        registers, ins, outs, _tries, _debug, n_insns = struct.unpack_from("<HHHHII", self.data, off)
        insns = array.array("H")
        insns.frombytes(self.data[off + 16:off + 16 + 2 * n_insns])
        if sys.byteorder == "big":
            insns.byteswap()
        return CodeItem(registers, ins, outs, insns)


# --- loading helpers ---------------------------------------------------------

def _dex_entry_order(name: str) -> int:
    # classes.dex, classes2.dex, classes3.dex ...
    stem = name[len("classes"):-len(".dex")]
    return int(stem) if stem.isdigit() else 1


def dex_names_in_zip(zf: zipfile.ZipFile) -> list[str]:
    names = [n for n in zf.namelist()
             if n.startswith("classes") and n.endswith(".dex") and "/" not in n]
    return sorted(names, key=_dex_entry_order)


def load_dexes(path: str) -> list[DexFile]:
    """Load every dex section from a .dex, .jar, .apk or .zip path."""
    with open(path, "rb") as fh:
        head = fh.read(4)
    if head == b"dex\n":
        with open(path, "rb") as fh:
            return DexFile.load_all(fh.read(), path)
    if head[:2] != b"PK":
        raise DexError("%s: neither dex nor zip" % path)
    out: list[DexFile] = []
    with zipfile.ZipFile(path) as zf:
        for name in dex_names_in_zip(zf):
            out.extend(DexFile.load_all(zf.read(name), "%s!%s" % (path, name)))
    return out
