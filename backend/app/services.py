import re
import unicodedata
from datetime import date, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

from . import rules
from .models import AuditLog, CareTask, Notification, Patient, PlanItem


def audit(
    db: Session, actor: str, action: str, entity: str, entity_id: int | None,
    details: str = "", *, org: str | None = None,
):
    db.add(AuditLog(actor=actor, action=action, entity=entity, entity_id=entity_id,
                    details=details, org=org))


def add_plan(db: Session, patient: Patient, specs: list[rules.PlanSpec]):
    for s in specs:
        db.add(PlanItem(patient_id=patient.id, kind=s.kind, title=s.title, due_date=s.due_date,
                        window_days=s.window_days, rule_ref=s.rule_ref, status="PLANNED"))


def normalize_name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def find_duplicate_patient(db: Session, *, full_name: str, birth_date: date,
                           snils: str | None = None, oms: str | None = None) -> Patient | None:
    """Resolve registry duplicates by canonical IDs, then normalized name + DOB."""
    if snils:
        digits = re.sub(r"\D", "", snils)
        patient = db.query(Patient).filter(Patient.snils == digits).first()
        if patient:
            return patient
    if oms:
        patient = db.query(Patient).filter(Patient.oms == "".join(oms.split())).first()
        if patient:
            return patient
    normalized = normalize_name(full_name)
    candidates = db.query(Patient).filter(Patient.birth_date == birth_date).all()
    return next((p for p in candidates if normalize_name(p.full_name) == normalized), None)


def sync_svr_plan(db: Session, patient: Patient, therapy_end: date):
    """Keep one active SVR12/SVR24 item for the current therapy end date.

    Repeated submissions of the same therapy are idempotent. If an active course
    is corrected, its outstanding control dates are updated rather than duplicated.
    Completed historical controls are retained.
    """
    for spec in rules.plan_after_therapy_end(therapy_end):
        items = (db.query(PlanItem).filter(PlanItem.patient_id == patient.id,
                                           PlanItem.kind == spec.kind)
                 .order_by(PlanItem.id).all())
        exact_done = next((i for i in items if i.due_date == spec.due_date and i.status == "DONE"), None)
        active = [i for i in items if i.status in ("PLANNED", "OVERDUE")]
        if exact_done:
            for item in active:
                item.status = "CANCELLED"
            continue

        target = next((i for i in active if i.due_date == spec.due_date), None)
        target = target or (active[0] if active else None)
        if target:
            target.title = spec.title
            target.due_date = spec.due_date
            target.window_days = spec.window_days
            target.rule_ref = spec.rule_ref
            target.status = "PLANNED"
            target.completed_at = None
            target.result = None
        else:
            db.add(PlanItem(patient_id=patient.id, kind=spec.kind, title=spec.title,
                            due_date=spec.due_date, window_days=spec.window_days,
                            rule_ref=spec.rule_ref, status="PLANNED"))
        for item in active:
            if item is not target:
                item.status = "CANCELLED"


def cancel_pending_svr_plan(db: Session, patient: Patient):
    for item in db.query(PlanItem).filter(
        PlanItem.patient_id == patient.id,
        PlanItem.kind.in_(("SVR12", "SVR24")),
        PlanItem.status.in_(("PLANNED", "OVERDUE")),
    ).all():
        item.status = "CANCELLED"


def refresh_overdue(
    db: Session, today: date | None = None, org: str | None = None, doctor_id: int | None = None
) -> int:
    today = today or date.today()
    changed = 0
    query = db.query(PlanItem).filter(PlanItem.status == "PLANNED")
    if org is not None or doctor_id is not None:
        query = query.join(Patient)
    if org is not None:
        query = query.filter(Patient.org == org)
    if doctor_id is not None:
        query = query.filter(or_(Patient.doctor_id == doctor_id, Patient.doctor_id.is_(None)))
    for item in query.all():
        new = rules.effective_status(item.status, item.due_date, item.window_days, today)
        if new != item.status:
            item.status = new
            changed += 1
    if changed:
        db.commit()
    return changed


def patient_dict(db: Session, p: Patient, today: date | None = None) -> dict:
    today = today or date.today()
    items = db.query(PlanItem).filter(PlanItem.patient_id == p.id).order_by(PlanItem.due_date, PlanItem.id).all()
    item_dicts = [{
        "id": i.id, "kind": i.kind, "title": i.title, "due_date": i.due_date,
        "window_days": i.window_days, "status": rules.effective_status(i.status, i.due_date, i.window_days, today),
        "rule_ref": i.rule_ref, "completed_at": i.completed_at, "result": i.result,
    } for i in items]
    # For identical due dates, keep completed items at the top of the group so
    # marking an event does not make it jump below still-open events.
    status_order = {"DONE": 0, "PLANNED": 1, "OVERDUE": 2, "CANCELLED": 3}
    item_dicts.sort(key=lambda item: (
        item["due_date"], status_order.get(item["status"], 4), item["id"]
    ))
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


def escalate_red_zone(db: Session, today: date | None = None, org: str | None = None) -> int:
    """Эскалация: просрочка -> задача обзвона (высокий приоритет при >30 дней)."""
    today = today or date.today()
    refresh_overdue(db, today, org=org)
    created = 0
    red_patients = []
    query = db.query(Patient).filter(Patient.status.in_(["ACTIVE", "ON_THERAPY", "POST_THERAPY"]))
    if org:
        query = query.filter(Patient.org == org)
    for p in query.all():
        d = patient_dict(db, p, today)
        if d["zone"] in ("red", "purple") and d["overdue_count"] > 0:
            red_patients.append((p, d))
    for p, d in red_patients:
        exists = db.query(CareTask).filter(CareTask.patient_id == p.id, CareTask.status == "OPEN").first()
        if exists:
            continue
        overdue_items = [i for i in d["plan"] if i["status"] == "OVERDUE"]
        worst_item = min(overdue_items, key=lambda i: i["due_date"])
        worst = worst_item["due_date"]
        overdue_days = (today - (worst + timedelta(days=worst_item["window_days"]))).days
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


def generate_reminders(db: Session, today: date | None = None, org: str | None = None) -> int:
    """Напоминания за 7/1 день до визита, за 10 дней до анализов, УВО-12 (блок 5)."""
    today = today or date.today()
    created = 0
    query = db.query(PlanItem).filter(PlanItem.status.in_(["PLANNED", "OVERDUE"]))
    if org:
        query = query.join(Patient).filter(Patient.org == org)
    items = query.all()
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
            if patient.consent_notifications and dup.status in ("SKIPPED_NO_CONSENT", "CANCELLED_NO_CONSENT"):
                dup.status = "QUEUED"
                dup.channel = patient.preferred_channel
                created += 1
            continue
        notify(db, patient, kind,
               f"Напоминание ГепаНавигатора: {item.title} — запланировано на {item.due_date.isoformat()}. "
               f"Не забудьте, пожалуйста. Для переноса позвоните в поликлинику.", today)
        created += 1
    if created:
        db.commit()
    return created
