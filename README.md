# termplan

![ci](https://github.com/rangy-vs/termplan/actions/workflows/ci.yml/badge.svg)

A prerequisite-aware **term-by-term course planner**. Describe your program's courses, prerequisites, and when each is offered; it produces a schedule that respects all of it and tells you the theoretical minimum number of terms.

```bash
pip install -r requirements.txt
python -m termplan examples/sample_catalog.yaml            # add --json for machine-readable output
```
```
Fall 2026    10 units    CS 101, MATH 1B
Winter 2027  10 units    CE 210, CS 102
Spring 2027  10 units    CS 201, CS 250
Fall 2027     5 units    CE 301
Winter 2028   0 units
Spring 2028   5 units    CE 350
Fall 2028     5 units    CE 400
7 terms for 9 required courses (theoretical minimum from prerequisite chains: 5).
```
The gap between 7 and 5 is real information: offering patterns (e.g. CE 301 only in Fall/Winter, the capstone only in Fall) force extra terms.

## Catalog format (YAML)
```yaml
terms: [Fall, Winter, Spring]      # works for semesters or quarters
start: Fall 2026
max_units: 15
completed: [MATH 1A]
targets: [CE 400]
courses:
  CS 201: {units: 5, prereq: [CS 102, [MATH 1B, MATH 2]], offered: [Winter, Spring]}   # CS 102 AND (MATH 1B OR MATH 2)
```

## Algorithm
1. **Closure:** expand targets into every required course. For an OR-group it prefers an alternative you've completed, then one already required, then the cheapest chain.
2. **List scheduling:** each term, take eligible courses (offered that term, prerequisites finished in *earlier* terms) by priority: longest dependency chain first (critical path), then scarcest offering, then name, until the unit cap.
3. **Lower bound:** earliest-possible-term analysis where an OR-group costs only its cheapest member.
4. **Validation:** unknown prerequisites, impossible unit loads, and prerequisite cycles (reported with the cycle path: `A -> B -> A`) are rejected before planning.

## Testing
29 tests, including a **property test on 400 random catalogs** asserting every plan respects prerequisites, offerings and unit caps. That test caught a real bug in my first lower-bound calculation (it counted every OR alternative, overstating the minimum); the regression test is confirmed to fail on the old code.

## Limits
- The scheduler is a greedy heuristic: valid plans, not guaranteed minimal ones (optimal scheduling with prerequisites, offerings and unit caps is NP-hard). The lower bound shows how close it is.
- **The sample catalog is fictional.** The tool knows nothing about any school's real rules (co-requisites, grade minimums, GE requirements): confirm any plan with your advisor.
- Next: co-requisites, minimum units per term, "avoid these terms" constraints, and an exact solver (ILP/CP-SAT) to compare against the heuristic.
