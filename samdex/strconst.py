"""Find which class/method loads a given string constant.

`strings SystemUI.apk` tells you a keyword like "DEX_MODE" appears
somewhere in the file. It does not tell you which class checks it, or in
which method -- and on a stripped/obfuscated-name release build that's
the only way to find the actual gating code to patch. This module walks
every method's bytecode looking for const-string / const-string/jumbo
loads and reports the owning class+method for each match.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .dexfile import DexError, REF_STRING, iter_insn_refs, load_dexes


@dataclass
class Hit:
    source: str
    cls: str
    method: str
    value: str


def scan(paths: list[str], pattern: str, ignore_case: bool = True) -> list[Hit]:
    rx = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
    hits: list[Hit] = []
    for path in paths:
        try:
            dexes = load_dexes(path)
        except (DexError, OSError) as exc:
            hits.append(Hit(path, "<error>", "<error>", str(exc)))
            continue
        for dex in dexes:
            for cd in dex.classes():
                owner = dex.type_name(cd.class_idx)
                for em in cd.direct_methods + cd.virtual_methods:
                    if not em.code_off:
                        continue
                    _c, mname, proto = dex.method_ref(em.method_idx)
                    seen_in_method: set[int] = set()
                    for _op, kind, idx in iter_insn_refs(dex.code_item(em.code_off).insns):
                        if kind != REF_STRING or idx in seen_in_method:
                            continue
                        val = dex.string(idx)
                        if rx.search(val):
                            seen_in_method.add(idx)
                            hits.append(Hit(path, owner, mname + proto, val))
    return hits


def render(hits: list[Hit]) -> str:
    if not hits:
        return "(no matches)"
    width_cls = max(len(h.cls) for h in hits)
    width_m = max(len(h.method) for h in hits)
    lines = []
    for h in hits:
        lines.append("%-*s  %-*s  %r" % (width_cls, h.cls, width_m, h.method, h.value))
    return "\n".join(lines)
