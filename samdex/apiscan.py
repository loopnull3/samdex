"""API compatibility scanner.

Given donor APKs (e.g. DeX components from a One UI 9.5 firmware) and an
index of the *target* framework (One UI 8 device), find every reference
the APK code makes that the target framework cannot satisfy:

* missing classes        -> NoClassDefFoundError at load time
* missing methods/fields -> NoSuchMethodError / NoSuchFieldError when hit
* static/instance flips  -> IncompatibleClassChangeError

Resolution follows ART semantics closely enough for porting decisions:
boot classpath first, then the app's own dex; superclass chain first,
then superinterfaces; constructors and invoke-direct are exact-class only.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .apiindex import ApiIndex, ClassInfo
from .dexfile import (ACC_STATIC, INVOKE_KIND, REF_FIELD, REF_METHOD, REF_TYPE,
                      field_op_kind, iter_insn_refs, load_dexes)

CORE_PREFIXES = ("Ljava/", "Ljavax/", "Lsun/", "Ljdk/", "Ldalvik/", "Llibcore/",
                 "Lorg/json/", "Lorg/xml/", "Lorg/w3c/", "Lorg/apache/harmony/", "Lorg/ccil/")
FRAMEWORK_PREFIXES = ("Landroid/", "Lcom/android/", "Lcom/samsung/", "Lcom/sec/",
                      "Lorg/apache/http/") + CORE_PREFIXES
SIG_POLYMORPHIC_OWNERS = ("Ljava/lang/invoke/MethodHandle;", "Ljava/lang/invoke/VarHandle;")
OBJECT_METHODS = {
    "<init>()V", "equals(Ljava/lang/Object;)Z", "hashCode()I", "toString()Ljava/lang/String;",
    "getClass()Ljava/lang/Class;", "notify()V", "notifyAll()V", "wait()V", "wait(J)V",
    "wait(JI)V", "clone()Ljava/lang/Object;", "finalize()V",
}
DEX_HOTSPOTS = ("Lcom/samsung/android/desktopmode/", "Lcom/samsung/android/multiwindow/",
                "Lcom/samsung/android/view/", "Landroid/window/", "Lcom/android/wm/shell/",
                "Landroid/view/", "Landroid/hardware/display/")


def category(cls: str) -> str:
    return "framework" if cls.startswith(FRAMEWORK_PREFIXES) else "external"


def split_params(proto: str) -> list[str]:
    """'(ILjava/lang/String;[J)V' -> ['I', 'Ljava/lang/String;', '[J']"""
    inner = proto[1:proto.index(")")]
    out: list[str] = []
    i = 0
    while i < len(inner):
        j = i
        while inner[j] == "[":
            j += 1
        if inner[j] == "L":
            j = inner.index(";", j)
        out.append(inner[i:j + 1])
        i = j + 1
    return out


def return_type(proto: str) -> str:
    return proto[proto.index(")") + 1:]


def base_class(desc: str) -> str | None:
    d = desc.lstrip("[")
    return d if d.startswith("L") else None


@dataclass
class Ref:
    count: int = 0
    kinds: set = field(default_factory=set)
    sites: list = field(default_factory=list)

    def add(self, kind: str, site: str, max_sites: int) -> None:
        self.count += 1
        self.kinds.add(kind)
        if len(self.sites) < max_sites and site not in self.sites:
            self.sites.append(site)


@dataclass
class Resolution:
    status: str                  # found | missing | missing-class | assumed
    where: str | None = None
    flags: int = 0
    origin: str | None = None
    anchor: str | None = None    # nearest framework class in the superclass chain
    missing_class: str | None = None


class Resolver:
    def __init__(self, primary: ApiIndex, secondary: ApiIndex | None, assume_core: bool):
        self.primary = primary
        self.secondary = secondary
        self.assume_core = assume_core
        self._root_memo: dict[str, str | None] = {}

    def lookup(self, cls: str) -> tuple[ClassInfo | None, str | None]:
        info = self.primary.get(cls)
        if info is not None:
            return info, "framework"
        if self.secondary is not None:
            info = self.secondary.get(cls)
            if info is not None:
                return info, "app"
        return None, None

    def assumed(self, cls: str) -> bool:
        return self.assume_core and cls.startswith(CORE_PREFIXES)

    def missing_root(self, cls: str) -> str | None:
        if cls in self._root_memo:
            return self._root_memo[cls]
        self._root_memo[cls] = None  # cycle guard
        info, _ = self.lookup(cls)
        if info is None:
            res = None if self.assumed(cls) else cls
        else:
            res = None
            for parent in [info.super, *info.interfaces]:
                if parent:
                    r = self.missing_root(parent)
                    if r:
                        res = r
                        break
        self._root_memo[cls] = res
        return res

    def resolve(self, cls: str, sig: str, member: str, exact: bool = False) -> Resolution:
        table_of = (lambda i: i.methods) if member == "m" else (lambda i: i.fields)
        seen: set[str] = set()
        chain: list[ClassInfo] = []
        anchor = None
        cur: str | None = cls
        while cur and cur not in seen:
            seen.add(cur)
            info, origin = self.lookup(cur)
            if info is None:
                if self.assumed(cur):
                    if cur == "Ljava/lang/Object;" and cur != cls:
                        if member == "m" and sig in OBJECT_METHODS:
                            return Resolution("found", cur, 0x1, "core", anchor)
                        break
                    return Resolution("assumed", anchor=anchor or cur)
                return Resolution("missing-class", anchor=anchor, missing_class=cur)
            if anchor is None and origin == "framework":
                anchor = cur
            table = table_of(info)
            if sig in table:
                return Resolution("found", cur, table[sig], origin, anchor)
            if exact:
                return Resolution("missing", anchor=anchor)
            chain.append(info)
            cur = info.super
        queue = [i for ci in chain for i in ci.interfaces]
        while queue:
            it = queue.pop(0)
            if it in seen:
                continue
            seen.add(it)
            info, origin = self.lookup(it)
            if info is None:
                if self.assumed(it):
                    return Resolution("assumed", anchor=anchor)
                continue
            table = table_of(info)
            if sig in table:
                return Resolution("found", it, table[sig], origin, anchor)
            queue.extend(info.interfaces)
        return Resolution("missing", anchor=anchor)

    def members_named(self, cls: str, name: str, member: str, limit: int = 6) -> list[str]:
        out: list[str] = []
        sep = "(" if member == "m" else ":"
        cur: str | None = cls
        seen: set[str] = set()
        while cur and cur not in seen and len(out) < limit:
            seen.add(cur)
            info, _ = self.lookup(cur)
            if info is None:
                break
            table = info.methods if member == "m" else info.fields
            for sig in table:
                if sig.startswith(name + sep) and sig not in out:
                    out.append(sig)
                    if len(out) >= limit:
                        break
            cur = info.super
        return out


class Scanner:
    def __init__(self, target: ApiIndex, donor: ApiIndex | None = None,
                 assume_core: bool | None = None, max_sites: int = 6):
        self.target = target
        self.donor = donor
        if assume_core is None:
            assume_core = not target.has("Ljava/lang/Object;")
        self.assume_core = assume_core
        self.max_sites = max_sites

    # --- collection -------------------------------------------------------------
    def _collect(self, apk_paths: list[str]):
        app = ApiIndex()
        mrefs: dict[tuple, Ref] = {}
        frefs: dict[tuple, Ref] = {}
        trefs: dict[str, Ref] = {}
        implemented: set[str] = set()
        ms = self.max_sites
        for path in apk_paths:
            src = len(app.sources)
            app.sources.append(path)
            for dex in load_dexes(path):
                app.add_dex(dex, src)
                mcache: dict[int, tuple] = {}
                fcache: dict[int, tuple] = {}
                for cd in dex.classes():
                    owner = dex.type_name(cd.class_idx)
                    if cd.super_idx != 0xFFFFFFFF:
                        trefs.setdefault(dex.type_name(cd.super_idx), Ref()).add("extends", owner, ms)
                    for t in cd.interfaces:
                        iname = dex.type_name(t)
                        implemented.add(iname)
                        trefs.setdefault(iname, Ref()).add("implements", owner, ms)
                    for em in cd.direct_methods + cd.virtual_methods:
                        if not em.code_off:
                            continue
                        _c, mname, proto = dex.method_ref(em.method_idx)
                        site = "%s->%s%s" % (owner, mname, proto)
                        for op, kind, idx in iter_insn_refs(dex.code_item(em.code_off).insns):
                            if kind == REF_METHOD:
                                key = mcache.get(idx)
                                if key is None:
                                    key = mcache[idx] = dex.method_ref(idx)
                                mrefs.setdefault(key, Ref()).add(INVOKE_KIND[op], site, ms)
                            elif kind == REF_FIELD:
                                key = fcache.get(idx)
                                if key is None:
                                    key = fcache[idx] = dex.field_ref(idx)
                                frefs.setdefault(key, Ref()).add(field_op_kind(op), site, ms)
                            elif kind == REF_TYPE:
                                bc = base_class(dex.type_name(idx))
                                if bc:
                                    trefs.setdefault(bc, Ref()).add("type", site, ms)
        return app, mrefs, frefs, trefs, implemented

    # --- analysis ---------------------------------------------------------------
    def scan(self, apk_paths: list[str]) -> dict:
        app, mrefs, frefs, trefs, implemented = self._collect(apk_paths)
        res = Resolver(self.target, app, self.assume_core)
        donor_res = Resolver(self.donor, app, self.assume_core) if self.donor else None

        missing_classes: dict[str, dict] = {}
        missing_methods: list[dict] = []
        missing_fields: list[dict] = []
        incompatible: list[dict] = []
        internal: list[dict] = []
        unverified = 0

        def mc_entry(root: str) -> dict:
            e = missing_classes.get(root)
            if e is None:
                e = missing_classes[root] = {
                    "class": root, "category": category(root), "count": 0, "sites": [],
                    "is_interface": root in implemented, "methods": {}, "fields": {},
                }
            return e

        def note_missing_class(root: str, ref: Ref, owner: str) -> dict:
            e = mc_entry(root)
            e["count"] += ref.count
            for s in ref.sites:
                if len(e["sites"]) < self.max_sites and s not in e["sites"]:
                    e["sites"].append(s)
            if owner != root and owner not in e.setdefault("via", []) and len(e["via"]) < self.max_sites:
                e["via"].append(owner)
            return e

        for cls, ref in trefs.items():
            root = res.missing_root(cls)
            if root:
                note_missing_class(root, ref, cls)

        total_m = 0
        for (cls, name, proto), ref in mrefs.items():
            total_m += 1
            if cls.startswith("[") or cls in SIG_POLYMORPHIC_OWNERS:
                continue
            root = res.missing_root(cls)
            if root:
                e = note_missing_class(root, ref, cls)
                if root == cls:
                    kinds = e["methods"].setdefault(name + proto, [])
                    for k in sorted(ref.kinds):
                        if k not in kinds:
                            kinds.append(k)
                    if "interface" in ref.kinds:
                        e["is_interface"] = True
                continue
            sig = name + proto
            exact = name in ("<init>", "<clinit>") or ref.kinds == {"direct"}
            r = res.resolve(cls, sig, "m", exact=exact)
            if r.status == "assumed":
                unverified += 1
                continue
            if r.status == "missing-class":
                note_missing_class(r.missing_class, ref, cls)
                continue
            if r.status == "found":
                if r.origin == "framework":
                    is_static = bool(r.flags & ACC_STATIC)
                    wants_static = "static" in ref.kinds
                    wants_instance = bool(ref.kinds - {"static", "polymorphic"})
                    if (wants_static and not is_static) or (wants_instance and is_static):
                        incompatible.append({
                            "kind": "method", "class": cls, "sig": sig, "declared_in": r.where,
                            "declared_static": is_static, "used_as": sorted(ref.kinds),
                            "sites": ref.sites, "count": ref.count,
                        })
                continue
            entry = {
                "class": cls, "anchor": r.anchor, "name": name, "proto": proto, "sig": sig,
                "kinds": sorted(ref.kinds), "count": ref.count, "sites": ref.sites,
                "category": category(r.anchor or cls),
            }
            if r.anchor is None:
                internal.append(entry)
                continue
            entry["near"] = res.members_named(r.anchor, name, "m")
            if name == "<init>":
                entry["ctor_fallback"] = self._ctor_fallback(r.anchor, proto)
            if donor_res is not None:
                d = donor_res.resolve(cls, sig, "m", exact=exact)
                entry["in_donor"] = d.status == "found"
                if d.status == "found":
                    entry["donor_declared_in"] = d.where
                    entry["static"] = bool(d.flags & ACC_STATIC)
            entry.setdefault("static", "static" in ref.kinds)
            missing_methods.append(entry)

        total_f = 0
        for (cls, name, ftype), ref in frefs.items():
            total_f += 1
            root = res.missing_root(cls)
            if root:
                e = note_missing_class(root, ref, cls)
                if root == cls:
                    kinds = e["fields"].setdefault(name + ":" + ftype, [])
                    for k in sorted(ref.kinds):
                        if k not in kinds:
                            kinds.append(k)
                continue
            sig = name + ":" + ftype
            r = res.resolve(cls, sig, "f")
            if r.status == "assumed":
                unverified += 1
                continue
            if r.status == "missing-class":
                note_missing_class(r.missing_class, ref, cls)
                continue
            if r.status == "found":
                if r.origin == "framework":
                    is_static = bool(r.flags & ACC_STATIC)
                    wants_static = bool(ref.kinds & {"sget", "sput"})
                    if is_static != wants_static:
                        incompatible.append({
                            "kind": "field", "class": cls, "sig": sig, "declared_in": r.where,
                            "declared_static": is_static, "used_as": sorted(ref.kinds),
                            "sites": ref.sites, "count": ref.count,
                        })
                continue
            entry = {
                "class": cls, "anchor": r.anchor, "name": name, "type": ftype, "sig": sig,
                "kinds": sorted(ref.kinds), "count": ref.count, "sites": ref.sites,
                "category": category(r.anchor or cls),
                "static": bool(ref.kinds & {"sget", "sput"}),
            }
            if r.anchor is None:
                internal.append(entry)
                continue
            entry["near"] = res.members_named(r.anchor, name, "f")
            if donor_res is not None:
                entry["in_donor"] = donor_res.resolve(cls, sig, "f").status == "found"
            missing_fields.append(entry)

        if self.donor is not None:
            for e in missing_classes.values():
                d = self.donor.get(e["class"])
                e["in_donor"] = d is not None
                if d is not None:
                    e["donor_super"] = d.super
                    e["donor_interfaces"] = d.interfaces
                    e["is_interface"] = e["is_interface"] or d.is_interface()
                    e["donor_access"] = d.access
            for e in missing_classes.values():
                sup = e.get("donor_super")
                e["stub_super"] = self._stub_super(sup)
        else:
            for e in missing_classes.values():
                e["stub_super"] = "Ljava/lang/Object;"

        report = {
            "apks": apk_paths,
            "app_classes": len(app.classes),
            "assume_core": self.assume_core,
            "target_sources": len(self.target.sources),
            "summary": {},
            "missing_classes": sorted(missing_classes.values(), key=lambda e: (e["category"], e["class"])),
            "missing_methods": sorted(missing_methods, key=lambda e: (e["category"], e["anchor"] or "", e["sig"])),
            "missing_fields": sorted(missing_fields, key=lambda e: (e["category"], e["anchor"] or "", e["sig"])),
            "incompatible": incompatible,
            "internal_unresolved": internal,
        }
        report["summary"] = summarize(report, total_m, total_f, unverified)
        return report

    def _ctor_fallback(self, cls: str, proto: str) -> str | None:
        info = self.target.get(cls)
        if info is None:
            return None
        want = split_params(proto)
        best: tuple[int, str] | None = None
        for sig in info.methods:
            if not sig.startswith("<init>("):
                continue
            have = split_params(sig[len("<init>"):])
            if len(have) < len(want) and want[:len(have)] == have:
                if best is None or len(have) > best[0]:
                    best = (len(have), sig)
        return best[1] if best else None

    def _stub_super(self, sup: str | None) -> str:
        if not sup:
            return "Ljava/lang/Object;"
        info = self.target.get(sup)
        if info is None or info.is_interface() or info.access & 0x10:  # final
            return "Ljava/lang/Object;"
        if "<init>()V" not in info.methods:
            return "Ljava/lang/Object;"
        return sup


def summarize(report: dict, total_m: int, total_f: int, unverified: int) -> dict:
    fw = lambda items: [e for e in items if e["category"] == "framework"]  # noqa: E731
    mc, mm, mf = fw(report["missing_classes"]), fw(report["missing_methods"]), fw(report["missing_fields"])
    hot = sorted({e.get("anchor") or e["class"] for e in mc + mm + mf
                  if (e.get("anchor") or e["class"]).startswith(DEX_HOTSPOTS)})
    unshimmable_ctors = [e for e in mm if e["name"] == "<init>" and not e.get("ctor_fallback")]
    score = len(mc) * 3 + len(mm) + len(mf) + len(report["incompatible"]) * 5 + len(unshimmable_ctors) * 3
    if score == 0:
        verdict = "A: drop-in (target framework satisfies every reference)"
    elif score <= 60 and not report["incompatible"]:
        verdict = "B: shimmable (samdex shim can bridge the gap)"
    else:
        verdict = "C: heavy (framework-side port of services.jar/framework.jar needed for full function)"
    return {
        "method_refs": total_m,
        "field_refs": total_f,
        "unverified_core_refs": unverified,
        "missing_classes": len(mc),
        "missing_methods": len(mm),
        "missing_fields": len(mf),
        "incompatible": len(report["incompatible"]),
        "unshimmable_ctors": len(unshimmable_ctors),
        "external_missing": (len(report["missing_classes"]) - len(mc)
                             + len(report["missing_methods"]) - len(mm)
                             + len(report["missing_fields"]) - len(mf)),
        "hotspot_classes": hot[:40],
        "score": score,
        "verdict": verdict,
    }


def render_markdown(report: dict, title: str = "API 호환성 리포트") -> str:
    s = report["summary"]
    lines = [
        "# %s" % title, "",
        "- APK: %s" % ", ".join("`%s`" % a for a in report["apks"]),
        "- 앱 클래스 수: %d, 메서드 참조 %d, 필드 참조 %d" % (report["app_classes"], s["method_refs"], s["field_refs"]),
        "- core 라이브러리 가정: %s (검증 안 된 core 참조 %d)" % (report["assume_core"], s["unverified_core_refs"]),
        "", "## 판정", "", "**%s** (score %d)" % (s["verdict"], s["score"]), "",
        "| 항목 | 개수 |", "|---|---|",
        "| 누락 클래스 (framework) | %d |" % s["missing_classes"],
        "| 누락 메서드 (framework) | %d |" % s["missing_methods"],
        "| 누락 필드 (framework) | %d |" % s["missing_fields"],
        "| static/instance 불일치 | %d |" % s["incompatible"],
        "| 대체 불가 생성자 | %d |" % s["unshimmable_ctors"],
        "| 외부/선택 라이브러리 누락 | %d |" % s["external_missing"],
        "",
    ]
    if s["hotspot_classes"]:
        lines += ["## DeX 핫스팟 (데스크톱/윈도우 관련 누락)", ""]
        lines += ["- `%s`" % c for c in s["hotspot_classes"]]
        lines.append("")
    if report["missing_classes"]:
        lines += ["## 누락 클래스", "", "| 클래스 | 분류 | 참조 | 인터페이스 | donor |", "|---|---|---|---|---|"]
        for e in report["missing_classes"]:
            lines.append("| `%s` | %s | %d | %s | %s |" % (
                e["class"], e["category"], e["count"], "Y" if e["is_interface"] else "",
                {True: "Y", False: "N"}.get(e.get("in_donor"), "?")))
        lines.append("")
    if report["missing_methods"]:
        lines += ["## 누락 메서드", "", "| anchor | 시그니처 | 호출 종류 | 참조 | 유사 시그니처 |", "|---|---|---|---|---|"]
        for e in report["missing_methods"]:
            near = "<br>".join("`%s`" % n for n in e.get("near", [])[:3])
            if e.get("ctor_fallback"):
                near = "fallback `%s`" % e["ctor_fallback"]
            lines.append("| `%s` | `%s` | %s | %d | %s |" % (
                e["anchor"], e["sig"], ",".join(e["kinds"]), e["count"], near))
        lines.append("")
    if report["missing_fields"]:
        lines += ["## 누락 필드", "", "| anchor | 필드 | 접근 | 참조 |", "|---|---|---|---|"]
        for e in report["missing_fields"]:
            lines.append("| `%s` | `%s` | %s | %d |" % (e["anchor"], e["sig"], ",".join(e["kinds"]), e["count"]))
        lines.append("")
    if report["incompatible"]:
        lines += ["## static/instance 불일치 (shim 불가, 프레임워크 수정 필요)", ""]
        for e in report["incompatible"]:
            lines.append("- `%s->%s` declared_static=%s used_as=%s" % (
                e["class"], e["sig"], e["declared_static"], ",".join(e["used_as"])))
        lines.append("")
    return "\n".join(lines)
