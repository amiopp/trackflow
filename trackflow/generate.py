"""Synthetic source data for a fictional tram & bus operator ("Metrolink City").

The generator mimics three real-world source systems and deliberately injects the
kind of mess you meet in production exports, so the Silver layer has real work to do:

* HR system export      -> hr_employees.csv, hr_absences.csv
* CMMS (maintenance)    -> maint_work_orders.csv
* Ops availability xlsx -> fleet_availability.csv

Injected issues: duplicate rows, untrimmed/inconsistent casing, mixed date formats,
blank values, and a few orphan foreign keys.
"""

from __future__ import annotations

import argparse
import csv
import random
from datetime import date, timedelta
from pathlib import Path

DEPARTMENTS = ["Operations", "Maintenance", "Customer Service", "Security", "Support Functions"]
DEPT_WEIGHTS = [0.45, 0.25, 0.12, 0.10, 0.08]
LINES = {"T1": 38, "T2": 30, "T3": 18, "T4": 20, "BW1": 14, "BW2": 12}  # vehicles required
FIRST = ["Yassine", "Salma", "Omar", "Imane", "Hamza", "Nora", "Karim", "Sara", "Mehdi", "Aya",
         "Anas", "Lina", "Reda", "Hiba", "Ilyas", "Zineb", "Adam", "Rania", "Bilal", "Meryem"]
LAST = ["Alaoui", "Bennani", "Chraibi", "Idrissi", "El Fassi", "Tazi", "Berrada", "Lahlou",
        "Ziani", "Amrani", "Kettani", "Sefrioui", "Naciri", "Hajji", "Ouazzani"]
ABSENCE_REASONS = ["sick", "Sick ", "family", "unpaid", "work_accident", "SICK"]


def _fmt(d: date | None, rng: random.Random) -> str:
    """Return a date in one of the formats seen in real exports (or blank)."""
    if d is None:
        return ""
    r = rng.random()
    if r < 0.80:
        return d.isoformat()
    if r < 0.95:
        return d.strftime("%d/%m/%Y")
    return d.strftime("%Y%m%d")


def _messy(text: str, rng: random.Random) -> str:
    r = rng.random()
    if r < 0.05:
        return f"  {text} "
    if r < 0.08:
        return text.upper()
    if r < 0.10:
        return text.lower()
    return text


def _write(path: Path, header: list[str], rows: list[list]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def generate(out_dir: str | Path, start: date = date(2023, 1, 1), end: date = date(2025, 12, 31),
             employees: int = 950, seed: int = 42) -> dict[str, int]:
    """Write the four source files to ``out_dir`` and return row counts."""
    rng = random.Random(seed)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    span = (end - start).days

    # --- HR: employees -------------------------------------------------------
    emp_rows, emp_meta = [], []
    for i in range(1, employees + 1):
        dept = rng.choices(DEPARTMENTS, DEPT_WEIGHTS)[0]
        if rng.random() < 0.8:  # already employed at start of window
            hire = start - timedelta(days=rng.randint(30, 4000))
        else:
            hire = start + timedelta(days=rng.randint(0, span - 30))
        exit_d, exit_type = None, ""
        if rng.random() < 0.13:
            exit_d = hire + timedelta(days=rng.randint(120, 3000))
            if not (start <= exit_d <= end):
                exit_d = None
            else:
                exit_type = rng.choices(["voluntary", "involuntary", "retirement"], [0.6, 0.25, 0.15])[0]
        emp_id = f"E{i:05d}"
        emp_meta.append((emp_id, dept, hire, exit_d))
        emp_rows.append([
            emp_id, f"{rng.choice(FIRST)} {rng.choice(LAST)}", _messy(dept, rng),
            rng.choice(["CDI", "CDI", "CDI", "CDD", "Interim"]),
            _fmt(hire, rng), _fmt(exit_d, rng), exit_type,
        ])
    emp_rows += rng.sample(emp_rows, 12)  # duplicates from a double export
    _write(out / "hr_employees.csv",
           ["employee_id", "full_name", "department", "contract_type", "hire_date", "exit_date", "exit_type"],
           emp_rows)

    # --- HR: absences --------------------------------------------------------
    abs_rows, n = [], 0
    dept_rate = {"Operations": 1.3, "Maintenance": 1.1, "Customer Service": 0.9, "Security": 1.0,
                 "Support Functions": 0.6}
    for emp_id, dept, hire, exit_d in emp_meta:
        lo, hi = max(hire, start), min(exit_d or end, end)
        if lo >= hi:
            continue
        expected = dept_rate[dept] * (hi - lo).days / 120
        for _ in range(int(expected + rng.random())):
            s = lo + timedelta(days=rng.randint(0, (hi - lo).days))
            # winter peak in sickness
            dur = rng.choice([1, 1, 2, 2, 3, 5]) + (rng.randint(0, 3) if s.month in (12, 1, 2) else 0)
            n += 1
            abs_rows.append([f"A{n:06d}", emp_id, _fmt(s, rng), _fmt(min(s + timedelta(days=dur - 1), hi), rng),
                             rng.choice(ABSENCE_REASONS)])
    abs_rows.append([f"A{n + 1:06d}", "E99999", start.isoformat(), start.isoformat(), "sick"])  # orphan
    abs_rows.append([f"A{n + 2:06d}", "E00001", "", "", "sick"])  # unusable dates
    abs_rows += rng.sample(abs_rows, 25)
    _write(out / "hr_absences.csv", ["absence_id", "employee_id", "start_date", "end_date", "reason"], abs_rows)

    # --- CMMS: work orders ---------------------------------------------------
    wo_rows, n = [], 0
    assets = [f"{line}-V{k:02d}" for line, req in LINES.items() for k in range(1, req + 3)]
    d = start
    while d <= end:
        for asset in assets:
            if rng.random() < 0.06:  # preventive plan
                n += 1
                late = rng.random()
                done = None if late < 0.05 else d + timedelta(days=0 if late < 0.85 else rng.randint(1, 20))
                if done and done > end:
                    done = None
                wo_rows.append([f"WO{n:07d}", asset, _messy("Preventive", rng), _fmt(d, rng), _fmt(done, rng),
                                "closed" if done else rng.choice(["open", "in_progress"])])
            if rng.random() < 0.025:  # corrective
                n += 1
                done = d + timedelta(days=rng.randint(0, 5))
                wo_rows.append([f"WO{n:07d}", asset, _messy("Corrective", rng), _fmt(d, rng),
                                _fmt(done if done <= end else None, rng), "closed" if done <= end else "open"])
        d += timedelta(days=7)
    wo_rows += rng.sample(wo_rows, 30)
    _write(out / "maint_work_orders.csv",
           ["work_order_id", "asset_id", "wo_type", "planned_date", "completed_date", "status"], wo_rows)

    # --- Ops: daily fleet availability ---------------------------------------
    fa_rows = []
    d = start
    while d <= end:
        for line, req in LINES.items():
            dip = 2 if d.month in (7, 8) else 0  # summer heat -> more failures
            out_of_service = rng.choices([0, 1, 2, 3, 4], [0.45, 0.3, 0.15, 0.07, 0.03])[0]
            out_of_service += dip * (rng.random() < 0.3)
            avail = max(0, req + 2 - out_of_service)  # +2 spare vehicles per line
            fa_rows.append([_fmt(d, rng), _messy(line, rng), req, avail])
        d += timedelta(days=1)
    _write(out / "fleet_availability.csv", ["date", "line", "vehicles_required", "vehicles_available"], fa_rows)

    return {"hr_employees": len(emp_rows), "hr_absences": len(abs_rows),
            "maint_work_orders": len(wo_rows), "fleet_availability": len(fa_rows)}


def main() -> None:
    p = argparse.ArgumentParser(description="Generate synthetic source extracts")
    p.add_argument("--out", default="data/raw")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()
    for name, n in generate(args.out, seed=args.seed).items():
        print(f"{name:<22} {n:>7,} rows")


if __name__ == "__main__":
    main()
