"""Binary AndroidManifest.xml (AXML) reader and in-place patcher.

Only in-place edits are made (same byte length), so chunk sizes and string
pools stay untouched. That is enough to lower minSdkVersion /
targetSdkVersion when grafting APKs built for a newer platform (e.g. a
One UI 9.5 / Android 17 donor onto a One UI 8 / Android 16 target).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

RES_STRING_POOL = 0x0001
RES_XML = 0x0003
RES_XML_START_NS = 0x0100
RES_XML_END_NS = 0x0101
RES_XML_START_ELEMENT = 0x0102
RES_XML_END_ELEMENT = 0x0103
RES_XML_RESOURCE_MAP = 0x0180

TYPE_NULL = 0x00
TYPE_REFERENCE = 0x01
TYPE_STRING = 0x03
TYPE_INT_DEC = 0x10
TYPE_INT_HEX = 0x11
TYPE_INT_BOOLEAN = 0x12

ANDROID_NS = "http://schemas.android.com/apk/res/android"
ATTR_IDS = {
    0x01010003: "name",
    0x0101000B: "sharedUserId",
    0x0101000D: "persistent",
    0x0101020C: "minSdkVersion",
    0x01010270: "targetSdkVersion",
    0x01010271: "maxSdkVersion",
    0x0101021B: "versionCode",
    0x0101021C: "versionName",
    0x0101028E: "required",
}


class AxmlError(ValueError):
    pass


@dataclass
class Attr:
    ns: str | None
    name: str
    raw: str | None
    dtype: int
    data: int
    offset: int  # absolute file offset of the attribute record

    @property
    def value(self):
        if self.dtype == TYPE_STRING or (self.raw is not None and self.dtype == TYPE_NULL):
            return self.raw
        if self.dtype == TYPE_INT_BOOLEAN:
            return self.data != 0
        if self.dtype in (TYPE_INT_DEC, TYPE_INT_HEX):
            return self.data - (1 << 32) if self.data & 0x80000000 else self.data
        if self.dtype == TYPE_REFERENCE:
            return "@0x%08x" % self.data
        return self.raw if self.raw is not None else self.data


@dataclass
class Element:
    name: str
    attrs: list[Attr]
    depth: int
    parent: str | None

    def get(self, name: str):
        for a in self.attrs:
            if a.name == name:
                return a
        return None


@dataclass
class Manifest:
    package: str | None = None
    shared_user_id: str | None = None
    version_code: int | None = None
    version_name: str | None = None
    min_sdk: object = None
    target_sdk: object = None
    uses_permissions: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    uses_libraries: list[tuple[str, bool]] = field(default_factory=list)
    persistent: bool = False
    components: dict[str, int] = field(default_factory=dict)
    elements: list[Element] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "package": self.package, "sharedUserId": self.shared_user_id,
            "versionCode": self.version_code, "versionName": self.version_name,
            "minSdk": self.min_sdk, "targetSdk": self.target_sdk,
            "usesPermissions": self.uses_permissions, "permissions": self.permissions,
            "usesLibraries": [{"name": n, "required": r} for n, r in self.uses_libraries],
            "persistent": self.persistent, "components": self.components,
        }


def _read_pool(data: bytes, off: int) -> list[str]:
    _type, header_size, _size = struct.unpack_from("<HHI", data, off)
    count, _styles, flags, strings_start, _styles_start = struct.unpack_from("<IIIII", data, off + 8)
    offsets = struct.unpack_from("<%dI" % count, data, off + header_size) if count else ()
    base = off + strings_start
    utf8 = bool(flags & 0x100)
    out: list[str] = []
    for so in offsets:
        p = base + so
        if utf8:
            n = data[p]
            p += 2 if n & 0x80 else 1           # utf-16 length (ignored)
            n = data[p]
            if n & 0x80:
                n = ((n & 0x7F) << 8) | data[p + 1]
                p += 2
            else:
                p += 1
            out.append(data[p:p + n].decode("utf-8", "replace"))
        else:
            (n,) = struct.unpack_from("<H", data, p)
            p += 2
            if n & 0x8000:
                (lo,) = struct.unpack_from("<H", data, p)
                n = ((n & 0x7FFF) << 16) | lo
                p += 2
            out.append(data[p:p + 2 * n].decode("utf-16-le", "replace"))
    return out


def parse(data: bytes) -> Manifest:
    if len(data) < 8:
        raise AxmlError("too short")
    rtype, _hs, total = struct.unpack_from("<HHI", data, 0)
    if rtype != RES_XML:
        raise AxmlError("not a binary XML document (type 0x%04x)" % rtype)
    strings: list[str] = []
    resmap: list[int] = []
    ns_uri: dict[int, str] = {}
    stack: list[str] = []
    m = Manifest()
    off = 8
    end = min(total, len(data))
    while off + 8 <= end:
        ctype, chs, csize = struct.unpack_from("<HHI", data, off)
        if csize < 8:
            raise AxmlError("bad chunk size at %d" % off)
        if ctype == RES_STRING_POOL:
            strings = _read_pool(data, off)
        elif ctype == RES_XML_RESOURCE_MAP:
            resmap = list(struct.unpack_from("<%dI" % ((csize - chs) // 4), data, off + chs))
        elif ctype == RES_XML_START_NS:
            prefix, uri = struct.unpack_from("<II", data, off + chs)
            if uri < len(strings):
                ns_uri[uri] = strings[uri]
        elif ctype == RES_XML_START_ELEMENT:
            ext = off + chs
            ns_i, name_i, attr_start, attr_size, attr_count = struct.unpack_from("<IIHHH", data, ext)
            ename = strings[name_i]
            attrs: list[Attr] = []
            for k in range(attr_count):
                ao = ext + attr_start + k * attr_size
                a_ns, a_name, a_raw, _vs, _r0, dtype, vdata = struct.unpack_from("<IIIHBBI", data, ao)
                if a_name < len(resmap) and resmap[a_name] in ATTR_IDS:
                    aname = ATTR_IDS[resmap[a_name]]
                else:
                    aname = strings[a_name] if a_name < len(strings) else "?"
                attrs.append(Attr(
                    strings[a_ns] if a_ns != 0xFFFFFFFF and a_ns < len(strings) else None,
                    aname, strings[a_raw] if a_raw != 0xFFFFFFFF and a_raw < len(strings) else None,
                    dtype, vdata, ao))
            el = Element(ename, attrs, len(stack), stack[-1] if stack else None)
            m.elements.append(el)
            stack.append(ename)
            _absorb(m, el)
        elif ctype == RES_XML_END_ELEMENT:
            if stack:
                stack.pop()
        off += csize
    return m


def _absorb(m: Manifest, el: Element) -> None:
    def val(name):
        a = el.get(name)
        return a.value if a else None

    if el.name == "manifest" and el.depth == 0:
        m.package = val("package")
        m.shared_user_id = val("sharedUserId")
        m.version_code = val("versionCode")
        m.version_name = val("versionName")
    elif el.name == "uses-sdk":
        m.min_sdk = val("minSdkVersion")
        m.target_sdk = val("targetSdkVersion")
    elif el.name in ("uses-permission", "uses-permission-sdk-23"):
        if val("name"):
            m.uses_permissions.append(val("name"))
    elif el.name == "permission":
        if val("name"):
            m.permissions.append(val("name"))
    elif el.name == "uses-library":
        req = val("required")
        m.uses_libraries.append((val("name"), True if req is None else bool(req)))
    elif el.name == "application":
        m.persistent = bool(val("persistent"))
    elif el.name in ("activity", "service", "receiver", "provider", "activity-alias"):
        m.components[el.name] = m.components.get(el.name, 0) + 1


def set_int_attr(data: bytes, attr: Attr, value: int) -> bytes:
    """Rewrite one attribute record in place as an INT_DEC value."""
    buf = bytearray(data)
    # rawValue := none, Res_value{size=8, res0=0, dataType=INT_DEC, data=value}
    struct.pack_into("<IHBBI", buf, attr.offset + 8, 0xFFFFFFFF, 8, 0, TYPE_INT_DEC, value & 0xFFFFFFFF)
    return bytes(buf)


def patch_sdk(data: bytes, max_sdk: int, fix_codename_target: bool = True) -> tuple[bytes, list[str]]:
    """Clamp minSdkVersion to `max_sdk`; turn preview codenames into ints.

    Returns the patched bytes and a list of human-readable changes.
    """
    m = parse(data)
    changes: list[str] = []
    for el in m.elements:
        if el.name != "uses-sdk":
            continue
        a = el.get("minSdkVersion")
        if a is not None:
            v = a.value
            if isinstance(v, str) or (isinstance(v, int) and v > max_sdk):
                data = set_int_attr(data, a, max_sdk)
                changes.append("minSdkVersion %r -> %d" % (v, max_sdk))
        t = el.get("targetSdkVersion")
        if t is not None and fix_codename_target and isinstance(t.value, str):
            data = set_int_attr(data, t, max_sdk)
            changes.append("targetSdkVersion %r -> %d" % (t.value, max_sdk))
    return data, changes
