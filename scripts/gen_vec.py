#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from string import Template


REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = REPO_ROOT / "std" / "vec_impl" / "vec_T.nif.template"
OUTPUT_DIR = REPO_ROOT / "std" / "vec_impl"


@dataclass(frozen=True)
class VecSpec:
    class_name: str
    element_type: str
    output_name: str


VEC_SPECS: tuple[VecSpec, ...] = (
    VecSpec(class_name="VecU8", element_type="u8", output_name="vec_u8.nif"),
    VecSpec(class_name="VecI64", element_type="i64", output_name="vec_i64.nif"),
    VecSpec(class_name="VecU64", element_type="u64", output_name="vec_u64.nif"),
    VecSpec(class_name="VecDouble", element_type="double", output_name="vec_double.nif"),
)


def _render(template: Template, spec: VecSpec) -> str:
    rendered = template.substitute(
        CLASS_NAME=spec.class_name,
        ELEMENT_TYPE=spec.element_type,
    )
    return rendered.rstrip() + "\n"


def _check_or_write(*, check_only: bool) -> int:
    template = Template(TEMPLATE_PATH.read_text(encoding="utf-8"))
    dirty = False

    for spec in VEC_SPECS:
        output_path = OUTPUT_DIR / spec.output_name
        rendered = _render(template, spec)
        current = output_path.read_text(encoding="utf-8") if output_path.exists() else None
        if current == rendered:
            continue

        dirty = True
        if check_only:
            print(f"out of date: {output_path.relative_to(REPO_ROOT)}")
            continue

        output_path.write_text(rendered, encoding="utf-8")
        print(f"updated {output_path.relative_to(REPO_ROOT)}")

    if check_only and dirty:
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate specialized primitive vector modules.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if generated files differ from the template output.",
    )
    args = parser.parse_args()

    if not TEMPLATE_PATH.exists():
        print(f"template not found: {TEMPLATE_PATH}", file=sys.stderr)
        return 2

    return _check_or_write(check_only=args.check)


if __name__ == "__main__":
    raise SystemExit(main())