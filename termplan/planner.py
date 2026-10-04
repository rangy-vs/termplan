"""Schedule required courses into terms.

1. Close the target set under prerequisites. For an OR group, prefer an alternative you've already
   completed, then one that's already required, then the cheapest chain.
2. List-schedule term by term: a course is eligible if it is offered that term and every
   prerequisite group is satisfied by courses completed in EARLIER terms. Among eligible courses,
   prioritise the longest dependency chain (critical path), then scarcer offerings, then name.
3. Report a lower bound (longest chain, in terms) so you can see how close the plan is to ideal."""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from .catalog import Catalog, Course


class PlanError(Exception):
    pass


@dataclass
class TermPlan:
    label: str
    season: str
    year: int
    courses: list[str] = field(default_factory=list)
    units: int = 0


@dataclass
class Plan:
    terms: list[TermPlan]
    required: list[str]
    lower_bound: int
    skipped_completed: list[str]
    unscheduled: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.unscheduled


def required_closure(cat: Catalog) -> tuple[set[str], list[str]]:
    need: set[str] = set()
    done = cat.completed

    @lru_cache(maxsize=None)
    def chain_cost(code: str) -> int:
        """Rough cost (units) of satisfying a course from scratch, used to pick OR alternatives."""
        if code in done:
            return 0
        c = cat.courses[code]
        return c.units + sum(min(chain_cost(p) for p in g if p in cat.courses or p in done) for g in c.prereq)

    stack = [t for t in cat.targets if t not in done]
    while stack:
        code = stack.pop()
        if code in need or code in done:
            continue
        need.add(code)
        for grp in cat.courses[code].prereq:
            if any(p in done for p in grp):
                continue
            already = [p for p in grp if p in need]
            pick = already[0] if already else min((p for p in grp if p in cat.courses), key=lambda p: (chain_cost(p), p))
            stack.append(pick)
    return need, sorted(t for t in cat.targets if t in done)


def _chain_lengths(cat: Catalog, need: set[str]) -> dict[str, int]:
    """Longest chain (in terms) from each required course to the end of any path that depends on it."""
    dependents: dict[str, set[str]] = {c: set() for c in need}
    for c in need:
        for grp in cat.courses[c].prereq:
            for p in grp:
                if p in need:
                    dependents[p].add(c)

    @lru_cache(maxsize=None)
    def depth(code: str) -> int:
        return 1 + max((depth(d) for d in dependents[code]), default=0)

    return {c: depth(c) for c in need}


def _lower_bound(cat: Catalog, need: set[str]) -> int:
    """Fewest terms any schedule could possibly take, ignoring offering patterns and unit caps.
    earliest(c) = 1 + max over prerequisite groups of (min over that group's alternatives):
    an OR group only costs its CHEAPEST member, so the bound never overstates (unlike dependent-chain
    depth, which counts every alternative and is used only as a scheduling priority)."""
    @lru_cache(maxsize=None)
    def earliest(code: str) -> int:
        if code in cat.completed:
            return 0
        groups = [min((earliest(p) for p in g if p in need or p in cat.completed), default=0)
                  for g in cat.courses[code].prereq]
        return 1 + max(groups, default=0)

    return max((earliest(c) for c in need), default=0)


def next_term(season: str, year: int, cycle: list[str], rolls_after: str = "Fall") -> tuple[str, int]:
    """Advance one term. The calendar year ticks over after `rolls_after` (Fall -> Winter crosses
    New Year), NOT at the end of the cycle: Fall 2026, Winter 2027, Spring 2027, Fall 2027."""
    nxt = cycle[(cycle.index(season) + 1) % len(cycle)]
    return nxt, year + (1 if season == rolls_after else 0)


def make_plan(cat: Catalog, max_terms: int = 16) -> Plan:
    need, skipped = required_closure(cat)
    chain = _chain_lengths(cat, need)
    scarcity = {c: len(cat.courses[c].offered) if cat.courses[c].offered else len(cat.term_cycle) for c in need}
    done = set(cat.completed)
    remaining = set(need)
    terms: list[TermPlan] = []
    season, year = cat.start

    def satisfied(course: Course) -> bool:
        return all(any(p in done for p in grp) for grp in course.prereq)

    for _ in range(max_terms):
        if not remaining:
            break
        tp = TermPlan(f"{season} {year}", season, year)
        eligible = [c for c in remaining
                    if (cat.courses[c].offered is None or season in cat.courses[c].offered) and satisfied(cat.courses[c])]
        for code in sorted(eligible, key=lambda c: (-chain[c], scarcity[c], c)):
            u = cat.courses[code].units
            if tp.units + u <= cat.max_units:
                tp.courses.append(code)
                tp.units += u
        terms.append(tp)
        for code in tp.courses:
            remaining.discard(code)
        done.update(tp.courses)            # only usable as prerequisites from the NEXT term on
        season, year = next_term(season, year, cat.term_cycle, cat.year_rolls_after)

    plan = Plan(terms, sorted(need), _lower_bound(cat, need), skipped)
    for code in sorted(remaining):
        plan.unscheduled[code] = _why_not(cat, code, done, max_terms)
    while plan.terms and not plan.terms[-1].courses:
        plan.terms.pop()
    return plan


def _why_not(cat: Catalog, code: str, done: set[str], max_terms: int) -> str:
    c = cat.courses[code]
    missing = [" or ".join(g) for g in c.prereq if not any(p in done for p in g)]
    if missing:
        return f"prerequisites never completed: {', '.join(missing)}"
    return f"not scheduled within {max_terms} terms (offered {sorted(c.offered) if c.offered else 'every term'})"
