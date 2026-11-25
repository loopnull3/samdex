"""samdex CLI. Pure stdlib -- runs under plain `python3` in Termux,
no pip install needed.

    python3 -m samdex strings SystemUI.apk services.jar --grep 'DEX_MODE|FLIP'
    python3 -m samdex classes  framework.jar --grep DesktopMode
    python3 -m samdex sig      SystemUI.apk
    python3 -m samdex manifest base.apk
    python3 -m samdex scan     --target /pulled/one_ui8 --donor DeXHome.apk
"""

from __future__ import annotations

import argparse
import sys


def cmd_strings(args) -> int:
    from .strconst import render, scan
    hits = scan(args.files, args.grep, ignore_case=not args.case_sensitive)
    print(render(hits))
    return 0


def cmd_classes(args) -> int:
    import re
    from .dexfile import load_dexes

    rx = re.compile(args.grep, re.IGNORECASE) if args.grep else None
    for path in args.files:
        for dex in load_dexes(path):
            for cd in dex.classes():
                name = dex.type_name(cd.class_idx)
                if rx is None or rx.search(name):
                    print(name)
    return 0


def cmd_sig(args) -> int:
    from .apksig import describe
    for path in args.files:
        info = describe(path)
        print(path, "-> unsigned" if info["unsigned"] else "")
        for scheme, fps in info["schemes"].items():
            for fp in fps:
                print("  %-5s %s" % (scheme, fp))
    return 0


def cmd_manifest(args) -> int:
    import json
    import zipfile

    from .axml import parse

    for path in args.files:
        with zipfile.ZipFile(path) as zf:
            data = zf.read("AndroidManifest.xml")
        m = parse(data)
        print("== %s ==" % path)
        print(json.dumps(m.to_dict(), indent=2, ensure_ascii=False))
    return 0


def cmd_scan(args) -> int:
    from .apiindex import ApiIndex
    from .apiscan import Scanner, render_markdown

    target = ApiIndex.load_or_build(args.target)
    donor = ApiIndex.load_or_build(args.donor) if args.donor else None
    report = Scanner(target, donor, assume_core=args.assume_core).scan(args.apks)
    if args.json:
        import json
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(report, args.title))
    if args.save_index:
        target.save(args.save_index)
    return 0


def cmd_index(args) -> int:
    from .apiindex import ApiIndex
    idx = ApiIndex()
    idx.add_paths(args.paths)
    idx.save(args.out)
    print("saved", args.out, idx.stats())
    for w in idx.warnings:
        print("warn:", w, file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="samdex")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("strings", help="find which class/method loads a string constant")
    s.add_argument("files", nargs="+")
    s.add_argument("--grep", required=True, help="regex to match against string values")
    s.add_argument("--case-sensitive", action="store_true")
    s.set_defaults(func=cmd_strings)

    s = sub.add_parser("classes", help="list class names, optionally filtered")
    s.add_argument("files", nargs="+")
    s.add_argument("--grep", default=None)
    s.set_defaults(func=cmd_classes)

    s = sub.add_parser("sig", help="read-only: list signer cert fingerprints")
    s.add_argument("files", nargs="+")
    s.set_defaults(func=cmd_sig)

    s = sub.add_parser("manifest", help="dump a parsed AndroidManifest.xml as JSON")
    s.add_argument("files", nargs="+")
    s.set_defaults(func=cmd_manifest)

    s = sub.add_parser("index", help="build and save a reusable API index (dir/jar/apk -> .json.gz)")
    s.add_argument("paths", nargs="+")
    s.add_argument("--out", required=True)
    s.set_defaults(func=cmd_index)

    s = sub.add_parser("scan", help="API-compatibility scan of APKs against a target framework index")
    s.add_argument("apks", nargs="+")
    s.add_argument("--target", required=True, help="saved index (.json.gz) or dir/jar to index now")
    s.add_argument("--donor", default=None, help="optional: framework the APKs were built against")
    s.add_argument("--assume-core", dest="assume_core", action="store_true", default=None)
    s.add_argument("--no-assume-core", dest="assume_core", action="store_false")
    s.add_argument("--save-index", default=None, help="cache the built target index here for reuse")
    s.add_argument("--json", action="store_true")
    s.add_argument("--title", default="API 호환성 리포트")
    s.set_defaults(func=cmd_scan)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
