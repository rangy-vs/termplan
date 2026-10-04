import random
from pathlib import Path

import pytest

from termplan.catalog import CatalogError, from_dict, load
from termplan.planner import make_plan, next_term, required_closure

SAMPLE = Path("examples/sample_catalog.yaml")


def cat(courses, targets, **kw):
    return from_dict({"courses": courses, "targets": targets, **kw})


def course_term(plan):
    return {c: i for i, t in enumerate(plan.terms) for c in t.courses}


def check_plan_is_valid(c, plan):
    """The invariants every plan must satisfy, whatever the input."""
    where = course_term(plan)
    for i, t in enumerate(plan.terms):
        assert t.units == sum(c.courses[x].units for x in t.courses) <= c.max_units
        for code in t.courses:
            spec = c.courses[code]
            assert spec.offered is None or t.season in spec.offered, f"{code} not offered {t.season}"
            for grp in spec.prereq:   # each prereq group satisfied strictly BEFORE this term
                assert any(p in c.completed or where.get(p, 10**9) < i for p in grp), f"{code} prereq {grp}"
    assert len(where) == sum(len(t.courses) for t in plan.terms)          # nothing scheduled twice


# ---------- sample catalog ----------
def test_sample_plan_valid_and_complete():
    c = load(SAMPLE)
    p = make_plan(c)
    assert p.ok and "MATH 1A" not in p.required                            # completed course is skipped
    check_plan_is_valid(c, p)
    assert len(p.terms) >= p.lower_bound


def test_calendar_years_roll_over_at_new_year_not_end_of_cycle():
    labels = [t.label for t in make_plan(load(SAMPLE)).terms]
    assert labels[:4] == ["Fall 2026", "Winter 2027", "Spring 2027", "Fall 2027"]


@pytest.mark.parametrize("cycle,rolls,seq", [
    (["Fall", "Winter", "Spring"], "Fall", [("Fall", 2026), ("Winter", 2027), ("Spring", 2027), ("Fall", 2027)]),
    (["Fall", "Spring"], "Fall", [("Fall", 2026), ("Spring", 2027), ("Fall", 2027)]),
    (["Fall", "Winter", "Spring", "Summer"], "Fall", [("Spring", 2027), ("Summer", 2027), ("Fall", 2027)]),
])
def test_next_term(cycle, rolls, seq):
    s, y = seq[0]
    for expect in seq[1:]:
        s, y = next_term(s, y, cycle, rolls)
        assert (s, y) == expect


# ---------- scheduling behaviour ----------
def test_chain_needs_one_term_per_link():
    c = cat({"A": {"units": 4}, "B": {"units": 4, "prereq": ["A"]}, "C": {"units": 4, "prereq": ["B"]},
             "D": {"units": 4, "prereq": ["C"]}}, ["D"])
    p = make_plan(c)
    assert [t.courses for t in p.terms] == [["A"], ["B"], ["C"], ["D"]] and p.lower_bound == 4


def test_prereq_not_usable_in_same_term():
    c = cat({"A": {"units": 4}, "B": {"units": 4, "prereq": ["A"]}}, ["B"])
    assert [t.courses for t in make_plan(c).terms] == [["A"], ["B"]]


def test_unit_cap_spills_to_next_term():
    c = cat({f"X{i}": {"units": 5} for i in range(4)}, [f"X{i}" for i in range(4)], max_units=10)
    p = make_plan(c)
    assert [len(t.courses) for t in p.terms] == [2, 2]


def test_critical_path_courses_go_first_when_capacity_is_tight():
    # LONG starts a 3-deep chain; filler courses are independent. With room for one course per term,
    # LONG must start immediately or the plan gets longer.
    c = cat({"LONG": {"units": 5}, "L2": {"units": 5, "prereq": ["LONG"]}, "L3": {"units": 5, "prereq": ["L2"]},
             "F1": {"units": 5}, "F2": {"units": 5}}, ["L3", "F1", "F2"], max_units=5)
    p = make_plan(c)
    assert p.terms[0].courses == ["LONG"] and len(p.terms) == 5


def test_scarce_offering_wins_ties():
    c = cat({"RARE": {"units": 5, "offered": ["Fall"]}, "COMMON": {"units": 5}}, ["RARE", "COMMON"], max_units=5)
    assert make_plan(c).terms[0].courses == ["RARE"]


def test_offered_terms_respected_and_gaps_allowed():
    c = cat({"A": {"units": 4}, "B": {"units": 4, "prereq": ["A"], "offered": ["Spring"]}}, ["B"], start="Fall 2026")
    p = make_plan(c)
    assert [t.label for t in p.terms if t.courses] == ["Fall 2026", "Spring 2027"]
    check_plan_is_valid(c, p)


def test_or_group_prefers_completed_alternative():
    c = cat({"X": {"units": 4}, "Y": {"units": 4}, "T": {"units": 4, "prereq": [["X", "Y"]]}}, ["T"], completed=["Y"])
    need, _ = required_closure(c)
    assert need == {"T"}                         # Y already satisfies the OR, so X is not pulled in


def test_or_group_prefers_already_required_alternative():
    c = cat({"X": {"units": 4}, "Y": {"units": 4}, "T": {"units": 4, "prereq": [["X", "Y"]]}, "U": {"units": 4, "prereq": ["Y"]}},
            ["T", "U"])
    need, _ = required_closure(c)
    assert need == {"T", "U", "Y"}               # Y is needed anyway, so reuse it rather than adding X


def test_or_group_picks_cheapest_chain():
    c = cat({"CHEAP": {"units": 3}, "BIG": {"units": 5, "prereq": ["BASE"]}, "BASE": {"units": 5},
             "T": {"units": 4, "prereq": [["BIG", "CHEAP"]]}}, ["T"])
    assert required_closure(c)[0] == {"T", "CHEAP"}


def test_completed_target_skipped():
    c = cat({"A": {"units": 4}, "B": {"units": 4}}, ["A", "B"], completed=["A"])
    p = make_plan(c)
    assert p.skipped_completed == ["A"] and p.required == ["B"]


def test_unscheduled_reported_when_out_of_terms():
    c = cat({"A": {"units": 4}, "B": {"units": 4, "prereq": ["A"]}, "C": {"units": 4, "prereq": ["B"]}}, ["C"])
    p = make_plan(c, max_terms=2)
    assert not p.ok and "not scheduled within 2 terms" in p.unscheduled["C"]
    assert len(p.terms) == 2                                      # A and B did get scheduled


# ---------- catalog validation ----------
def test_cycle_detected_with_path():
    with pytest.raises(CatalogError, match=r"cycle: A -> B -> A|cycle: B -> A -> B"):
        cat({"A": {"units": 4, "prereq": ["B"]}, "B": {"units": 4, "prereq": ["A"]}}, ["A"])


def test_self_prereq_is_a_cycle():
    with pytest.raises(CatalogError, match="cycle"):
        cat({"A": {"units": 4, "prereq": ["A"]}}, ["A"])


@pytest.mark.parametrize("courses,targets,match", [
    ({"A": {"units": 4, "prereq": ["GHOST"]}}, ["A"], "not in the catalog"),
    ({"A": {"units": 0}}, ["A"], "positive"),
    ({"A": {"units": 25}}, ["A"], "exceeds max_units"),
    ({"A": {"units": 4}}, ["NOPE"], "target"),
    ({"A": {"units": 4}}, [], "no targets"),
    ({"A": {"units": 4, "offered": ["Monsoon"]}}, ["A"], "unknown term"),
])
def test_validation_errors(courses, targets, match):
    with pytest.raises(CatalogError, match=match):
        cat(courses, targets)


def test_code_normalisation():
    c = cat({"cs  101": {"units": 4}, "CS 102": {"units": 4, "prereq": ["Cs 101"]}}, ["cs 102"])
    assert make_plan(c).ok


# ---------- property test: random catalogs always yield valid plans ----------
def random_catalog(rng):
    n = rng.randint(3, 14)
    names = [f"C{i}" for i in range(n)]
    courses = {}
    for i, name in enumerate(names):
        prereq = []
        for _ in range(rng.randint(0, 2)):
            pool = names[:i]                                  # edges only point backwards => acyclic
            if pool:
                prereq.append(rng.sample(pool, 1)[0] if rng.random() < 0.7 else rng.sample(pool, min(2, len(pool))))
        offered = None if rng.random() < 0.5 else rng.sample(["Fall", "Winter", "Spring"], rng.randint(1, 3))
        courses[name] = {"units": rng.choice([2, 4, 5]), "prereq": prereq, **({"offered": offered} if offered else {})}
    return cat(courses, rng.sample(names, rng.randint(1, min(4, n))), max_units=rng.choice([5, 10, 15]))


def test_random_catalogs_always_produce_valid_plans():
    rng = random.Random(2026)
    for _ in range(400):
        c = random_catalog(rng)
        p = make_plan(c, max_terms=60)
        check_plan_is_valid(c, p)
        assert p.ok, p.unscheduled                            # acyclic + every course offered some term => solvable
        assert len(p.terms) >= p.lower_bound
        assert set(c.targets) <= set(p.required) | set(p.skipped_completed)


# ---------- CLI ----------
def test_cli_exit_codes(tmp_path, capsys):
    from termplan.__main__ import main
    assert main([str(SAMPLE)]) == 0
    assert "Capstone" in capsys.readouterr().out
    assert main([str(SAMPLE), "--max-terms", "2"]) == 1                    # can't finish in 2 terms
    bad = tmp_path / "bad.yaml"
    bad.write_text("courses: {A: {units: 4, prereq: [A]}}\ntargets: [A]\n")
    assert main([str(bad)]) == 2
    assert main(["missing.yaml"]) == 2


def test_cli_json(capsys):
    import json
    from termplan.__main__ import main
    assert main([str(SAMPLE), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] and data["terms"][0]["term"] == "Fall 2026"


def test_lower_bound_counts_or_group_as_cheapest_alternative():
    """Regression for a bug the random-catalog test found: when BOTH alternatives of an OR group are
    required for other reasons, summing dependent-chain depth overstates the minimum. T needs only
    one of {C, SHORT}; the long A->B->C chain is required anyway (by Z) and SHORT is required anyway
    (by S2), so T can start right after SHORT and the long chain doesn't delay it."""
    from termplan.planner import _chain_lengths, required_closure
    c = cat({"A": {"units": 2}, "B": {"units": 2, "prereq": ["A"]}, "C": {"units": 2, "prereq": ["B"]},
             "SHORT": {"units": 2}, "T": {"units": 2, "prereq": [["C", "SHORT"]]},
             "V": {"units": 2, "prereq": ["T"]}, "W": {"units": 2, "prereq": ["V"]},
             "Z": {"units": 2, "prereq": ["C"]}, "S2": {"units": 2, "prereq": ["SHORT"]}}, ["W", "Z", "S2"], max_units=20)
    need, _ = required_closure(c)
    assert {"C", "SHORT"} <= need                               # both alternatives are in play
    assert max(_chain_lengths(c, need).values()) == 6           # naive chain depth: A->B->C->T->V->W
    p = make_plan(c)
    assert p.lower_bound == 4 and len(p.terms) == 4             # true optimum: SHORT lets T start in term 2
    check_plan_is_valid(c, p)
