"""Unit-тесты клинического слоя (блок 2): правила КР без БД."""
from datetime import date, timedelta

from app import rules


def test_initial_plan_has_core_events():
    plan = rules.build_initial_plan("HCV", cirrhosis=False, anchor=date(2026, 1, 1))
    kinds = {p.kind for p in plan}
    assert {"VISIT", "LABS", "PCR", "ULTRASOUND", "ELASTOMETRY"} <= kinds
    assert "HCC_SCREENING" not in kinds  # без цирроза скрининг ГЦР не назначается


def test_cirrhosis_adds_hcc_screening():
    plan = rules.build_initial_plan("HBV", cirrhosis=True, anchor=date(2026, 1, 1))
    kinds = {p.kind for p in plan}
    assert "HCC_SCREENING" in kinds and "AFP" in kinds


def test_svr12_is_12_weeks_after_therapy_end():
    end = date(2026, 1, 1)
    plan = rules.plan_after_therapy_end(end)
    svr12 = next(p for p in plan if p.kind == "SVR12")
    assert svr12.due_date == end + timedelta(weeks=12)


def test_overdue_after_window():
    due = date(2026, 1, 1)
    assert rules.effective_status("PLANNED", due, 14, date(2026, 1, 15)) == "PLANNED"
    assert rules.effective_status("PLANNED", due, 14, date(2026, 1, 16)) == "OVERDUE"
    assert rules.effective_status("DONE", due, 14, date(2026, 2, 1)) == "DONE"


def test_zone_priority_purple_over_red():
    today = date(2026, 6, 1)
    items = [
        {"kind": "LABS", "status": "OVERDUE", "due_date": date(2026, 5, 1)},
        {"kind": "SVR12", "status": "PLANNED", "due_date": today + timedelta(days=35)},
    ]
    assert rules.patient_zone(items, today) == "purple"


def test_zone_red_yellow_green():
    today = date(2026, 6, 1)
    assert rules.patient_zone([{"kind": "LABS", "status": "OVERDUE", "due_date": date(2026, 5, 1)}], today) == "red"
    assert rules.patient_zone([{"kind": "LABS", "status": "PLANNED", "due_date": date(2026, 6, 20)}], today) == "yellow"
    assert rules.patient_zone([{"kind": "LABS", "status": "DONE", "due_date": date(2026, 5, 1)}], today) == "green"


def test_reminder_schedule():
    assert rules.reminder_kind_for("VISIT", 7) == "VISIT_REMINDER"
    assert rules.reminder_kind_for("VISIT", 1) == "VISIT_REMINDER"
    assert rules.reminder_kind_for("VISIT", 3) is None
    assert rules.reminder_kind_for("LABS", 10) == "LABS_REMINDER"
    assert rules.reminder_kind_for("SVR12", 7) == "SVR12_REMINDER"
