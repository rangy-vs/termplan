"""Load + validate a course catalog from YAML.

prereq format: a list that is an AND of items; an item that is itself a list is an OR group.
    prereq: ["CS 101", ["MATH 19A", "MATH 20A"]]   # CS 101 AND (MATH 19A OR MATH 20A)"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


class CatalogError(Exception):
    pass


@dataclass(frozen=True)
class Course:
    code: str
    units: int
    prereq: tuple[tuple[str, ...], ...] = ()      # AND of OR-groups
    offered: frozenset[str] | None = None          # None = every term
    title: str = ""


@dataclass
class Catalog:
    courses: dict[str, Course]
    term_cycle: list[str]
    start: tuple[str, int]                         # ("Fall", 2026)
    max_units: int
    completed: set[str] = field(default_factory=set)
    targets: list[str] = field(default_factory=list)
    year_rolls_after: str = "Fall"      # the calendar year increments after this term (Fall -> Winter crosses New Year)


def _norm(code: str) -> str:
    return " ".join(str(code).split()).upper()


def parse_prereq(raw) -> tuple[tuple[str, ...], ...]:
    if raw in (None, [], ""):
        return ()
    if isinstance(raw, str):
        raw = [raw]
    groups = []
    for item in raw:
        group = [item] if isinstance(item, str) else list(item)
        if not group:
            raise CatalogError("empty OR group in prerequisites")
        groups.append(tuple(_norm(c) for c in group))
    return tuple(groups)


def parse_term(text: str, cycle: list[str]) -> tuple[str, int]:
    m = re.fullmatch(r"\s*([A-Za-z]+)\s+(\d{4})\s*", str(text))
    if not m or m.group(1).capitalize() not in cycle:
        raise CatalogError(f"bad start term {text!r}; expected '<{'|'.join(cycle)}> <year>'")
    return m.group(1).capitalize(), int(m.group(2))


def load(path: str | Path) -> Catalog:
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise CatalogError(f"invalid YAML: {e}") from None
    return from_dict(data)


def from_dict(data: dict) -> Catalog:
    if not isinstance(data, dict) or "courses" not in data:
        raise CatalogError("catalog must be a mapping with a 'courses' section")
    cycle = [str(t).capitalize() for t in data.get("terms", ["Fall", "Winter", "Spring"])]
    if len(set(cycle)) != len(cycle) or not cycle:
        raise CatalogError("terms must be a non-empty list of unique names")
    courses = {}
    for raw_code, spec in data["courses"].items():
        code, spec = _norm(raw_code), spec or {}
        units = spec.get("units")
        if not isinstance(units, int) or units <= 0:
            raise CatalogError(f"{code}: units must be a positive integer")
        off = spec.get("offered")
        offered = None if off in (None, "any") else frozenset(str(t).capitalize() for t in off)
        if offered is not None and not offered <= set(cycle):
            raise CatalogError(f"{code}: offered in unknown term(s) {sorted(offered - set(cycle))}")
        if offered is not None and not offered:
            raise CatalogError(f"{code}: offered list is empty")
        courses[code] = Course(code, units, parse_prereq(spec.get("prereq")), offered, str(spec.get("title", "")))
    rolls = str(data.get("year_rolls_after", "Fall" if "Fall" in cycle else cycle[-1])).capitalize()
    if rolls not in cycle:
        raise CatalogError(f"year_rolls_after must be one of {cycle}")
    cat = Catalog(courses, cycle, parse_term(data.get("start", f"{cycle[0]} 2026"), cycle),
                  int(data.get("max_units", 20)),
                  {_norm(c) for c in data.get("completed", [])}, [_norm(c) for c in data.get("targets", [])], rolls)
    validate(cat)
    return cat


def validate(cat: Catalog) -> None:
    known = set(cat.courses)
    for c in cat.courses.values():
        for grp in c.prereq:
            for p in grp:
                if p not in known and p not in cat.completed:
                    raise CatalogError(f"{c.code}: prerequisite {p!r} is not in the catalog")
        if c.units > cat.max_units:
            raise CatalogError(f"{c.code}: {c.units} units exceeds max_units={cat.max_units}")
    for t in cat.targets:
        if t not in known:
            raise CatalogError(f"target {t!r} is not in the catalog")
    if not cat.targets:
        raise CatalogError("no targets: list the courses you need under 'targets'")
    find_cycle(cat)


def find_cycle(cat: Catalog) -> None:
    """Detect prerequisite cycles (DFS with colors) over every possible dependency edge."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {c: WHITE for c in cat.courses}
    stack: list[str] = []

    def visit(code: str) -> None:
        color[code] = GRAY
        stack.append(code)
        for grp in cat.courses[code].prereq:
            for p in grp:
                if p not in cat.courses:
                    continue
                if color[p] == GRAY:
                    cyc = stack[stack.index(p):] + [p]
                    raise CatalogError("prerequisite cycle: " + " -> ".join(cyc))
                if color[p] == WHITE:
                    visit(p)
        stack.pop()
        color[code] = BLACK

    for c in cat.courses:
        if color[c] == WHITE:
            visit(c)
