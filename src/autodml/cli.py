"""autodml CLI.

Commands:
  init      scaffold an autodml project (models/ views/ relationships.yml ...)
  validate  lint a manifest (errors + warnings, exit 1 on errors)
  export    convert manifest -> mdl.json
  reflect   generate a manifest from a live database (SQLAlchemy)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .model import Manifest
from .serialize import load, load_dir, to_json, to_yaml, write_dir, write_json


def _cmd_init(args) -> int:
    root = Path(args.path)
    (root / "models").mkdir(parents=True, exist_ok=True)
    (root / "views").mkdir(parents=True, exist_ok=True)
    rel = root / "relationships.yml"
    if not rel.exists():
        rel.write_text(
            "relationships: []\n"
            "# example:\n"
            "# - name: orders_customer_fk\n"
            "#   relationType: manyToOne\n"
            "#   left:\n"
            "#     modelName: orders\n"
            "#     columnName: customer_id\n"
            "#   right:\n"
            "#     modelName: customers\n"
            "#     columnName: id\n",
            encoding="utf-8",
        )
    sample = root / "models" / "example.yml"
    if not sample.exists():
        sample.write_text(
            "name: example\n"
            "refSql: public.example\n"
            "columns:\n"
            "  - name: id\n"
            "    type: integer\n"
            "    notNull: true\n"
            "    isPrimary: true\n"
            "  - name: name\n"
            "    type: string\n"
            "calculations: []\n",
            encoding="utf-8",
        )
    print(f"initialized autodml project at {root}")
    return 0


def _load_any(path: str) -> Manifest:
    p = Path(path)
    if p.is_dir():
        return load_dir(p)
    return load(p)


def _cmd_validate(args) -> int:
    from .validate import validate

    m = _load_any(args.path)
    rep = validate(m)
    print(f"manifest={m.manifest} models={len(m.models)} "
          f"relationships={len(m.relationships)} metrics={len(m.metrics)} views={len(m.views)}")
    for i in rep.issues:
        loc = f" @ {i.path}" if i.path else ""
        print(f"  [{i.severity}] {i.rule}{loc}: {i.message}")
    if not rep.issues:
        print("no issues found")
    if rep.ok:
        print("VALID")
        return 0
    print(f"INVALID ({len(rep.errors)} errors, {len(rep.warnings)} warnings)")
    return 1


def _cmd_export(args) -> int:
    m = _load_any(args.path)
    if args.format == "cubepy":
        from .exporters.cubepy import write_cubepy_yaml
        out, warnings = write_cubepy_yaml(m, args.out)
        for w in warnings:
            print(f"  [warn] {w}", file=sys.stderr)
        print(f"wrote {out} ({len(warnings)} warnings)")
    elif args.format == "yaml-dir":
        out = write_dir(m, args.out)
        print(f"wrote {out}/")
    elif args.format == "yaml":
        Path(args.out).write_text(to_yaml(m), encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        out = write_json(m, args.out)
        print(f"wrote {out}")
    return 0


def _cmd_reflect(args) -> int:
    from .introspect import reflect

    include = args.include.split(",") if args.include else None
    exclude = args.exclude.split(",") if args.exclude else None
    m = reflect(args.url, schema=args.schema or None,
                include=include, exclude=exclude,
                infer_relationships=not args.no_relationships)
    if args.format == "yaml-dir":
        write_dir(m, args.out)
        print(f"wrote {args.out}/")
    else:
        write_json(m, args.out)
        print(f"wrote {args.out}")
    print(f"models={len(m.models)} relationships={len(m.relationships)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="autodml",
                                description="Auto Modeling Definition Language toolkit")
    p.add_argument("--version", action="version", version=f"autodml {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("init", help="scaffold an autodml project")
    sp.add_argument("path", nargs="?", default=".")
    sp.set_defaults(func=_cmd_init)

    sp = sub.add_parser("validate", help="validate a manifest file or directory")
    sp.add_argument("path", help="manifest .yml/.json or project directory")
    sp.set_defaults(func=_cmd_validate)

    sp = sub.add_parser("export", help="convert manifest to mdl.json / yaml")
    sp.add_argument("path", help="source manifest or directory")
    sp.add_argument("-o", "--out", default="mdl.json")
    sp.add_argument("--format", choices=["json", "yaml", "yaml-dir", "cubepy"], default="json")
    sp.set_defaults(func=_cmd_export)

    sp = sub.add_parser("reflect", help="generate manifest from live database")
    sp.add_argument("url", help="SQLAlchemy URL, e.g. postgresql://user:pw@host/db")
    sp.add_argument("-o", "--out", default="mdl.json")
    sp.add_argument("--schema", default="")
    sp.add_argument("--include", help="comma-separated table globs")
    sp.add_argument("--exclude", help="comma-separated table globs")
    sp.add_argument("--no-relationships", action="store_true")
    sp.add_argument("--format", choices=["json", "yaml-dir"], default="json")
    sp.set_defaults(func=_cmd_reflect)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
