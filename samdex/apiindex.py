"""API index: the set of classes/methods/fields a framework (or app) defines.

An index is built from jars/apks/dex files and saved as gzipped JSON so a
device dump can be indexed once in Termux and reused on any machine.
"""

from __future__ import annotations

import gzip
import json
import os
import zipfile
from typing import Iterable

from .dexfile import ACC_STATIC, DexError, DexFile, NO_INDEX, dex_names_in_zip, load_dexes

INDEX_VERSION = 1
SCAN_EXTS = (".jar", ".apk", ".dex", ".zip")


class ClassInfo:
    __slots__ = ("name", "super", "interfaces", "access", "methods", "fields", "src")

    def __init__(self, name: str, super_: str | None, interfaces: list[str], access: int,
                 methods: dict[str, int] | None = None, fields: dict[str, int] | None = None,
                 src: int = -1):
        self.name = name
        self.super = super_
        self.interfaces = interfaces
        self.access = access
        self.methods = methods if methods is not None else {}
        self.fields = fields if fields is not None else {}
        self.src = src

    def is_interface(self) -> bool:
        return bool(self.access & 0x200)

    def to_json(self) -> list:
        return [self.super, self.interfaces, self.access, self.methods, self.fields, self.src]

    @classmethod
    def from_json(cls, name: str, raw: list) -> "ClassInfo":
        return cls(name, raw[0], raw[1], raw[2], raw[3], raw[4], raw[5])


class ApiIndex:
    def __init__(self) -> None:
        self.classes: dict[str, ClassInfo] = {}
        self.sources: list[str] = []
        self.meta: dict = {}
        self.warnings: list[str] = []

    # --- construction -----------------------------------------------------------
    def add_dex(self, dex: DexFile, src: int, override: bool = False) -> int:
        added = 0
        for cd in dex.classes():
            name = dex.type_name(cd.class_idx)
            if name in self.classes and not override:
                continue  # first definition wins (boot classpath order)
            super_ = dex.type_name(cd.super_idx) if cd.super_idx != NO_INDEX else None
            info = ClassInfo(name, super_, [dex.type_name(t) for t in cd.interfaces], cd.access, src=src)
            for midx_list in (cd.direct_methods, cd.virtual_methods):
                for em in midx_list:
                    _cls, mname, proto = dex.method_ref(em.method_idx)
                    info.methods[mname + proto] = em.access
            for fl in (cd.static_fields, cd.instance_fields):
                for fidx, acc in fl:
                    _cls, fname, ftype = dex.field_ref(fidx)
                    info.fields[fname + ":" + ftype] = acc
            self.classes[name] = info
            added += 1
        return added

    def add_file(self, path: str, label: str | None = None) -> int:
        src = len(self.sources)
        self.sources.append(label or path)
        try:
            if path.endswith((".jar", ".apk", ".zip")):
                with zipfile.ZipFile(path) as zf:
                    if not dex_names_in_zip(zf):
                        self.warnings.append(
                            "%s: no classes.dex inside (odex/vdex-only jar; extract the vdex first)" % path)
                        return 0
            dexes = load_dexes(path)
        except (DexError, zipfile.BadZipFile, OSError) as exc:
            self.warnings.append("%s: %s" % (path, exc))
            return 0
        return sum(self.add_dex(d, src) for d in dexes)

    def add_paths(self, paths: Iterable[str]) -> int:
        total = 0
        for p in paths:
            if os.path.isdir(p):
                for root, dirs, files in os.walk(p):
                    dirs.sort()
                    for f in sorted(files):
                        if f.endswith(SCAN_EXTS):
                            total += self.add_file(os.path.join(root, f))
            else:
                total += self.add_file(p)
        return total

    # --- queries ----------------------------------------------------------------
    def get(self, name: str) -> ClassInfo | None:
        return self.classes.get(name)

    def has(self, name: str) -> bool:
        return name in self.classes

    def source_of(self, info: ClassInfo) -> str:
        return self.sources[info.src] if 0 <= info.src < len(self.sources) else "?"

    def stats(self) -> dict:
        return {
            "classes": len(self.classes),
            "methods": sum(len(c.methods) for c in self.classes.values()),
            "fields": sum(len(c.fields) for c in self.classes.values()),
            "sources": len(self.sources),
        }

    # --- persistence ------------------------------------------------------------
    def save(self, path: str) -> None:
        doc = {
            "v": INDEX_VERSION,
            "meta": self.meta,
            "sources": self.sources,
            "warnings": self.warnings,
            "classes": {n: c.to_json() for n, c in self.classes.items()},
        }
        opener = gzip.open if path.endswith(".gz") else open
        with opener(path, "wt", encoding="utf-8") as fh:
            json.dump(doc, fh, separators=(",", ":"))

    @classmethod
    def load(cls, path: str) -> "ApiIndex":
        opener = gzip.open if path.endswith(".gz") else open
        with opener(path, "rt", encoding="utf-8") as fh:
            doc = json.load(fh)
        if doc.get("v") != INDEX_VERSION:
            raise ValueError("%s: unsupported index version %r" % (path, doc.get("v")))
        idx = cls()
        idx.meta = doc.get("meta", {})
        idx.sources = doc.get("sources", [])
        idx.warnings = doc.get("warnings", [])
        idx.classes = {n: ClassInfo.from_json(n, raw) for n, raw in doc["classes"].items()}
        return idx

    @classmethod
    def load_or_build(cls, spec: str) -> "ApiIndex":
        """`spec` is either a saved index (.json/.json.gz) or a dir/jar to index."""
        if spec.endswith((".json", ".json.gz")) and os.path.isfile(spec):
            return cls.load(spec)
        idx = cls()
        idx.add_paths([spec])
        return idx


def is_static(flags: int) -> bool:
    return bool(flags & ACC_STATIC)
