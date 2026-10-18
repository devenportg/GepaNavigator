from datetime import date, timedelta

from sqlalchemy.orm import Session

from . import rules
from .models import AuditLog, CareTask, Notification, Patient, PlanItem


def audit(db: Session, actor: str, action: str, entity: str, entity_id: int | None, details: str = ""):
    db.add(AuditLog(actor=actor, action=action, entity=entity, entity_id=entity_id, details=details))


def add_plan(db: Session, patient: Patient, specs: list[rules.PlanSpec]):
    for s in specs:
        db.add(PlanItem(patient_id=patient.id, kind=s.kind, title=s.title, due_date=s.due_date,
                        window_days=s.window_days, rule_ref=s.rule_ref, status="PLANNED"))


def refresh_overdue(db: Session, today: date | None = None) -> int:
    today = today or date.today()
    changed = 0
    for item in db.query(PlanItem).filter(PlanItem.status == "PLANNED").all():
        new = rules.effective_status(item.status, item.due_date, item.window_days, today)
        if new != item.status:
            item.status = new
            changed += 1
    if changed:
        db.commit()
    return changed


def patient_dict(db: Session, p: Patient, today: date | None = None) -> dict:
    today = today or date.today()
    items = db.query(PlanItem).filter(PlanItem.patient_id == p.id).order_by(PlanItem.due_date).all()
    item_dicts = [{
        "id": i.id, "kind": i.kind, "title": i.title, "due_date": i.due_date,
        "window_days": i.window_days, "status": rules.effective_status(i.status, i.due_date, i.window_days, today),
        "rule_ref": i.rule_ref, "completed_at": i.completed_at, "result": i.result,
    } for i in items]
    upcoming = [i for i in item_dicts if i["status"] in ("PLANNED", "OVERDUE")]
    return {
        "id": p.id, "full_name": p.full_name, "birth_date": p.birth_date, "sex": p.sex,
        "snils": p.snils, "oms": p.oms, "phone": p.phone,
        "consent_notifications": p.consent_notifications, "preferred_channel": p.preferred_channel,
        "diagnosis_code": p.diagnosis_code, "nosology": p.nosology, "fibrosis_stage": p.fibrosis_stage,
        "cirrhosis": p.cirrhosis, "genotype": p.genotype, "viral_load": p.viral_load,
        "status": p.status, "enrollment_trigger": p.enrollment_trigger, "enrolled_at": p.enrolled_at,
        "therapy_regimen": p.therapy_regimen, "therapy_start": p.therapy_start, "therapy_end": p.therapy_end,
        "svr12_achieved": p.svr12_achieved, "discharge_reason": p.discharge_reason,
        "doctor_id": p.doctor_id, "org": p.org,
        "zone": rules.patient_zone(item_dicts, today) if p.status not in ("DISCHARGED", "DECEASED") else "green",
        "next_due": min((i["due_date"] for i in upcoming), default=None),
        "overdue_count": sum(1 for i in item_dicts if i["status"] == "OVERDUE"),
        "plan": item_dicts,
    }


def notify(db: Session, patient: Patient, kind: str, text: str, when: date | None = None) -> Notification:
    status = "QUEUED" if patient.consent_notifications else "SKIPPED_NO_CONSENT"
    n = Notification(patient_id=patient.id, channel=patient.preferred_channel, kind=kind,
                     text=text, status=status, scheduled_for=when or date.today())
    db.add(n)
    return n


def escalate_red_zone(db: Session, today: date | None = None) -> int:
    """Эскалация: просрочка -> задача обзвона (высокий приоритет при >30 дней)."""
    today = today or date.today()
    refresh_overdue(db, today)
    created = 0
    red_patients = []
    for p in db.query(Patient).filter(Patient.status.in_(["ACTIVE", "ON_THERAPY", "POST_THERAPY"])).all():
        d = patient_dict(db, p, today)
        if d["zone"] in ("red", "purple") and d["overdue_count"] > 0:
            red_patients.append((p, d))
    for p, d in red_patients:
        exists = db.query(CareTask).filter(CareTask.patient_id == p.id, CareTask.status == "OPEN").first()
        if exists:
            continue
        worst = min(i["due_date"] for i in d["plan"] if i["status"] == "OVERDUE")
        overdue_days = (today - worst).days
        db.add(CareTask(
            patient_id=p.id, kind="ESCALATION" if overdue_days > 30 else "CALL",
            title=f"Обзвон: просрочено событий — {d['overdue_count']} (с {worst.isoformat()})",
            priority="high" if overdue_days > 30 else "normal",
            due_date=today + timedelta(days=1),
        ))
        created += 1
    if created:
        db.commit()
    return created


def generate_reminders(db: Session, today: date | None = None) -> int:
    """Напоминания за 7/1 день до визита, за 10 дней до анализов, УВО-12 (блок 5)."""
    today = today or date.today()
    created = 0
    items = db.query(PlanItem).filter(PlanItem.status.in_(["PLANNED", "OVERDUE"])).all()
    for item in items:
        days_before = (item.due_date - today).days
        kind = rules.reminder_kind_for(item.kind, days_before)
        if not kind:
            continue
        patient = db.get(Patient, item.patient_id)
        if not patient or patient.status in ("DISCHARGED", "DECEASED"):
            continue
        dup = db.query(Notification).filter(
            Notification.patient_id == patient.id, Notification.kind == kind,
            Notification.scheduled_for == today).first()
        if dup:
            continue
        notify(db, patient, kind,
               f"Напоминание ГепаНавигатора: {item.title} — запланировано на {item.due_date.isoformat()}. "
               f"Не забудьте, пожалуйста. Для переноса позвоните в поликлинику.", today)
        created += 1
    if created:
        db.commit()
    return created
