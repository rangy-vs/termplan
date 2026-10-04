"""python -m termplan examples/sample_catalog.yaml [--max-terms 16] [--json]"""
from __future__ import annotations

import argparse
import json
import sys

from .catalog import CatalogError, load
from .planner import make_plan


def render(plan, cat) -> str:
    lines = []
    for t in plan.terms:
        lines.append(f"{t.label:<12} {t.units:>2} units")
        lines += [f"    {c:<12}{cat.courses[c].units:>2}u  {cat.courses[c].title}" for c in t.courses]
    done = len(plan.terms)
    lines.append(f"\n{done} terms for {len(plan.required)} required courses "
                 f"(theoretical minimum from prerequisite chains: {plan.lower_bound}).")
    if plan.skipped_completed:
        lines.append(f"Already completed: {', '.join(plan.skipped_completed)}")
    for code, why in plan.unscheduled.items():
        lines.append(f"UNSCHEDULED {code}: {why}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="termplan", description="Prerequisite-aware term-by-term course planner")
    ap.add_argument("catalog")
    ap.add_argument("--max-terms", type=int, default=16)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        cat = load(a.catalog)
    except (CatalogError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    plan = make_plan(cat, a.max_terms)
    if a.json:
        print(json.dumps({"ok": plan.ok, "lower_bound": plan.lower_bound, "unscheduled": plan.unscheduled,
                          "terms": [{"term": t.label, "units": t.units, "courses": t.courses} for t in plan.terms]}, indent=2))
    else:
        print(render(plan, cat))
    return 0 if plan.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
