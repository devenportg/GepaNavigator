from datetime import date, timedelta

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from . import rules, services
from .config import settings
from .db import Base, engine, get_db
from .models import CareTask, Encounter, Notification, Patient, PlanItem, User, AuditLog
from .schemas import (CareCompleteIn, ConsentIn, EncounterIn, GisEventIn, LoginIn,
                      PatientIn, PatientPatch, PlanCompleteIn, TherapyIn)
from .security import create_token, get_current_user, require_roles, verify_password
from .seed import seed

Base.metadata.create_all(bind=engine)
app = FastAPI(title="ГепаНавигатор API", version="0.1.0",
              description="Модуль диспансерного наблюдения больных хроническими гепатитами (MVP, этап 2)")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def startup():
    if settings.seed_demo:
        db = next(get_db())
        seed(db)
        db.close()


def user_out(u: User):
    return {"id": u.id, "email": u.email, "full_name": u.full_name, "role": u.role, "org": u.org}


@app.get("/health")
def health():
    return {"status": "ok", "service": "gepanavigator", "version": app.version}


# ---------- Auth (блок 8: RBAC) ----------
@app.post("/api/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Неверный e-mail или пароль")
    return {"access_token": create_token(user), "user": user_out(user)}


@app.get("/api/auth/me")
def me(user: User = Depends(get_current_user)):
    return user_out(user)


# ---------- Регистр пациентов (блок 1) ----------
@app.get("/api/patients")
def list_patients(search: str = "", zone: str = "", status: str = "",
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    services.refresh_overdue(db)
    q = db.query(Patient)
    if search:
        q = q.filter(Patient.full_name.ilike(f"%{search}%"))
    if status:
        q = q.filter(Patient.status == status)
    result = [services.patient_dict(db, p) for p in q.order_by(Patient.full_name).all()]
    if zone:
        result = [r for r in result if r["zone"] == zone]
    if user.role == "doctor":  # врач видит своих; остальные роли — по своей компетенции в MVP не режем
        pass
    return result


@app.post("/api/patients", status_code=201)
def create_patient(body: PatientIn, db: Session = Depends(get_db),
                   user: User = Depends(require_roles("doctor", "head", "nurse"))):
    # Дедупликация: СНИЛС -> ФИО+дата рождения (блок 1)
    existing = None
    if body.snils:
        existing = db.query(Patient).filter(Patient.snils == body.snils).first()
    if not existing:
        existing = db.query(Patient).filter(
            Patient.full_name == body.full_name, Patient.birth_date == body.birth_date).first()
    if existing:
        raise HTTPException(409, f"Пациент уже в регистре (id={existing.id}): дубликат по СНИЛС/ФИО+ДР")
    p = Patient(**body.model_dump(), doctor_id=user.id if user.role == "doctor" else None)
    db.add(p)
    db.commit()
    db.refresh(p)
    services.add_plan(db, p, rules.build_initial_plan(p.nosology, p.cirrhosis, p.enrolled_at))
    services.notify(db, p, "WELCOME",
                    f"Здравствуйте! Вы поставлены на диспансерное наблюдение (гепатит). "
                    f"Первый приём запланирован, мы напомним о дате визита.", date.today())
    services.audit(db, user.full_name, "patient.create", "patient", p.id, body.enrollment_trigger)
    db.commit()
    return services.patient_dict(db, p)


@app.get("/api/patients/{patient_id}")
def get_patient(patient_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = db.get(Patient, patient_id)
    if not p:
        raise HTTPException(404, "Пациент не найден")
    services.refresh_overdue(db)
    d = services.patient_dict(db, p)
    d["encounters"] = [{
        "id": e.id, "visit_date": e.visit_date, "complaints": e.complaints,
        "conclusion": e.conclusion, "draft_conclusion": e.draft_conclusion, "signed": e.signed,
    } for e in sorted(p.encounters, key=lambda x: x.visit_date, reverse=True)]
    return d


@app.patch("/api/patients/{patient_id}")
def patch_patient(patient_id: int, body: PatientPatch, db: Session = Depends(get_db),
                  user: User = Depends(require_roles("doctor", "head", "nurse"))):
    p = db.get(Patient, patient_id)
    if not p:
        raise HTTPException(404, "Пациент не найден")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(p, k, v)
    services.audit(db, user.full_name, "patient.update", "patient", p.id, str(body.model_dump(exclude_none=True)))
    db.commit()
    return services.patient_dict(db, p)


@app.post("/api/patients/{patient_id}/consent")
def set_consent(patient_id: int, body: ConsentIn, db: Session = Depends(get_db),
                user: User = Depends(require_roles("doctor", "head", "nurse"))):
    p = db.get(Patient, patient_id)
    if not p:
        raise HTTPException(404, "Пациент не найден")
    p.consent_notifications = body.consent_notifications
    p.preferred_channel = body.preferred_channel
    services.audit(db, user.full_name, "patient.consent", "patient", p.id, str(body.consent_notifications))
    db.commit()
    return services.patient_dict(db, p)


# ---------- Клинический слой / план (блок 2) ----------
@app.post("/api/plan-items/{item_id}/complete")
def complete_item(item_id: int, body: PlanCompleteIn, db: Session = Depends(get_db),
                  user: User = Depends(require_roles("doctor", "head", "nurse"))):
    item = db.get(PlanItem, item_id)
    if not item:
        raise HTTPException(404, "Событие плана не найдено")
    item.status = "DONE"
    item.completed_at = body.completed_at or date.today()
    item.result = body.result
    patient = db.get(Patient, item.patient_id)
    if item.kind == "SVR12" and patient:
        # Отрицательный ПЦР на УВО-12 = УВО достигнут (результат содержит 'не обнаруж'/'отриц')
        res = (body.result or "").lower()
        patient.svr12_achieved = ("не обнаруж" in res) or ("отриц" in res) or res == "uvо" or "уво" in res
    services.audit(db, user.full_name, "plan.complete", "plan_item", item.id, f"{item.kind}: {body.result or ''}")
    db.commit()
    return {"id": item.id, "status": item.status, "completed_at": item.completed_at}


@app.post("/api/plan-items/{item_id}/cancel")
def cancel_item(item_id: int, db: Session = Depends(get_db),
                user: User = Depends(require_roles("doctor", "head"))):
    item = db.get(PlanItem, item_id)
    if not item:
        raise HTTPException(404, "Событие плана не найдено")
    item.status = "CANCELLED"
    services.audit(db, user.full_name, "plan.cancel", "plan_item", item.id, item.kind)
    db.commit()
    return {"id": item.id, "status": item.status}


# ---------- Приём врача (блок 3) ----------
@app.post("/api/patients/{patient_id}/encounters", status_code=201)
def create_encounter(patient_id: int, body: EncounterIn, db: Session = Depends(get_db),
                     user: User = Depends(require_roles("doctor", "head"))):
    p = db.get(Patient, patient_id)
    if not p:
        raise HTTPException(404, "Пациент не найден")
    today = date.today()
    if body.complete_visit_item:
        visit = (db.query(PlanItem).filter(PlanItem.patient_id == p.id, PlanItem.kind == "VISIT",
                                          PlanItem.status.in_(["PLANNED", "OVERDUE"]))
                 .order_by(PlanItem.due_date).first())
        if visit:
            visit.status = "DONE"
            visit.completed_at = today
    next_step = "явка на плановый приём через 6 месяцев, лабораторный контроль по плану наблюдения."
    draft = rules.draft_conclusion(p.full_name, p.nosology, p.diagnosis_code, body.complaints, next_step)
    enc = Encounter(patient_id=p.id, doctor_id=user.id, visit_date=today, complaints=body.complaints,
                    conclusion=body.conclusion, draft_conclusion=draft, signed=bool(body.conclusion))
    db.add(enc)
    db.flush()  # sessionmaker(autoflush=False): статус визита должен попасть в запрос ниже
    # Следующий цикл наблюдения по КР
    existing_next = (db.query(PlanItem).filter(PlanItem.patient_id == p.id, PlanItem.kind == "VISIT",
                                               PlanItem.status == "PLANNED",
                                               PlanItem.due_date > today).first())
    if not existing_next:
        services.add_plan(db, p, rules.plan_after_visit(today, p.cirrhosis))
    services.audit(db, user.full_name, "encounter.create", "encounter", None, f"patient={p.id}")
    db.commit()
    db.refresh(enc)
    return {"id": enc.id, "visit_date": enc.visit_date, "draft_conclusion": enc.draft_conclusion,
            "conclusion": enc.conclusion, "signed": enc.signed}


@app.post("/api/patients/{patient_id}/therapy")
def set_therapy(patient_id: int, body: TherapyIn, db: Session = Depends(get_db),
                user: User = Depends(require_roles("doctor", "head"))):
    p = db.get(Patient, patient_id)
    if not p:
        raise HTTPException(404, "Пациент не найден")
    p.therapy_regimen, p.therapy_start, p.therapy_end = body.regimen, body.therapy_start, body.therapy_end
    if body.therapy_end:
        p.status = "POST_THERAPY"
        services.add_plan(db, p, rules.plan_after_therapy_end(body.therapy_end))
        services.notify(db, p, "SVR12_REMINDER",
                        f"После окончания терапии важен контроль УВО-12 "
                        f"({(body.therapy_end + timedelta(weeks=12)).isoformat()}). Мы напомним заранее.", date.today())
    else:
        p.status = "ON_THERAPY"
    services.audit(db, user.full_name, "therapy.set", "patient", p.id, body.regimen)
    db.commit()
    return services.patient_dict(db, p)


# ---------- Рабочее место: список на период (блок 3) ----------
@app.get("/api/worklist")
def worklist(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    services.refresh_overdue(db)
    rows = [services.patient_dict(db, p) for p in
            db.query(Patient).filter(Patient.status.notin_(["DISCHARGED", "DECEASED"])).all()]
    rows.sort(key=lambda r: (r["next_due"] is None, r["next_due"] or date.max))
    summary = {z: sum(1 for r in rows if r["zone"] == z) for z in ("green", "yellow", "red", "purple")}
    return {"summary": summary, "patients": rows}


# ---------- Care Management (блок 4) ----------
@app.get("/api/care/tasks")
def list_tasks(status: str = "OPEN", db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.query(CareTask)
    if status:
        q = q.filter(CareTask.status == status)
    out = []
    for t in q.order_by(CareTask.due_date).all():
        p = db.get(Patient, t.patient_id)
        out.append({"id": t.id, "patient_id": t.patient_id, "patient_name": p.full_name if p else None,
                    "kind": t.kind, "title": t.title, "priority": t.priority, "status": t.status,
                    "due_date": t.due_date, "outcome": t.outcome, "comment": t.comment})
    return out


@app.post("/api/care/tasks/{task_id}/complete")
def complete_task(task_id: int, body: CareCompleteIn, db: Session = Depends(get_db),
                  user: User = Depends(require_roles("doctor", "head", "nurse"))):
    t = db.get(CareTask, task_id)
    if not t:
        raise HTTPException(404, "Задача не найдена")
    if body.outcome not in ("WILL_COME", "REFUSED", "NO_ANSWER", "UNREACHABLE"):
        raise HTTPException(422, "Недопустимый исход обзвона")
    t.status = "DONE"
    t.outcome = body.outcome
    t.comment = body.comment
    services.audit(db, user.full_name, "care.complete", "care_task", t.id, body.outcome)
    db.commit()
    return {"id": t.id, "status": t.status, "outcome": t.outcome}


# ---------- Коммуникации (блок 5) ----------
@app.get("/api/notifications")
def list_notifications(patient_id: int | None = None, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    q = db.query(Notification)
    if patient_id:
        q = q.filter(Notification.patient_id == patient_id)
    return [{"id": n.id, "patient_id": n.patient_id, "channel": n.channel, "kind": n.kind,
             "text": n.text, "status": n.status, "scheduled_for": n.scheduled_for}
            for n in q.order_by(Notification.id.desc()).limit(200).all()]


# ---------- Интеграции: события ГИС ЭЗ РТ / ФРВГ (блок 6) ----------
@app.post("/api/integrations/gis/events", status_code=201)
def gis_event(body: GisEventIn, db: Session = Depends(get_db),
              x_integration_key: str = Header(default="")):
    if x_integration_key != settings.integration_key:
        raise HTTPException(403, "Неверный ключ интеграции")
    code = (body.code or body.patient.diagnosis_code or "").upper()
    triggers = ("B18", "PCR_POSITIVE", "HBSAG_POSITIVE", "ANTI_HCV_POSITIVE")
    if not any(code.startswith(t) for t in triggers):
        return {"enrolled": False, "reason": f"Событие {code} не является триггером постановки на учёт"}
    existing = None
    if body.patient.snils:
        existing = db.query(Patient).filter(Patient.snils == body.patient.snils).first()
    if not existing:
        existing = db.query(Patient).filter(
            Patient.full_name == body.patient.full_name,
            Patient.birth_date == body.patient.birth_date).first()
    if existing:
        return {"enrolled": True, "duplicate": True, "patient_id": existing.id}
    trigger = "frvg" if body.event_type == "RegistryRecord" else "gis_event"
    p = Patient(**body.patient.model_dump(exclude={"enrollment_trigger"}), enrollment_trigger=trigger)
    db.add(p)
    db.commit()
    db.refresh(p)
    services.add_plan(db, p, rules.build_initial_plan(p.nosology, p.cirrhosis, p.enrolled_at))
    services.notify(db, p, "WELCOME", "Здравствуйте! Вы поставлены на диспансерное наблюдение (гепатит). "
                                      "Мы будем напоминать о визитах и анализах.", date.today())
    services.audit(db, "gis-integration", "patient.auto_enroll", "patient", p.id, code)
    db.commit()
    return {"enrolled": True, "duplicate": False, "patient_id": p.id}


# ---------- Аналитика (блок 7) ----------
@app.get("/api/analytics/overview")
def analytics(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    services.refresh_overdue(db)
    patients = db.query(Patient).all()
    active = [p for p in patients if p.status not in ("DISCHARGED", "DECEASED")]
    items = db.query(PlanItem).all()
    done = sum(1 for i in items if i.status == "DONE")
    overdue = sum(1 for i in items if i.status == "OVERDUE")
    svr_total = sum(1 for i in items if i.kind == "SVR12" and i.status == "DONE")
    svr_ok = sum(1 for p in patients if p.svr12_achieved)
    rows = [services.patient_dict(db, p) for p in active]
    by_nosology: dict[str, int] = {}
    for p in active:
        by_nosology[p.nosology] = by_nosology.get(p.nosology, 0) + 1
    by_doctor: dict[str, int] = {}
    for p in active:
        doc = db.get(User, p.doctor_id) if p.doctor_id else None
        name = doc.full_name if doc else "Не назначен"
        by_doctor[name] = by_doctor.get(name, 0) + 1
    return {
        "registry_total": len(patients),
        "active_total": len(active),
        "coverage_note": "Охват = активные в регистре / все выявленные (в MVP знаменатель — регистр)",
        "zones": {z: sum(1 for r in rows if r["zone"] == z) for z in ("green", "yellow", "red", "purple")},
        "adherence": round(done / (done + overdue), 3) if (done + overdue) else None,
        "plan_done": done, "plan_overdue": overdue,
        "svr12_checked": svr_total, "svr12_achieved": svr_ok,
        "svr_rate": round(svr_ok / svr_total, 3) if svr_total else None,
        "by_nosology": by_nosology, "by_doctor": by_doctor,
    }


# ---------- Аудит и планировщик (блоки 8 + Scheduler) ----------
@app.get("/api/audit")
def audit_list(db: Session = Depends(get_db), user: User = Depends(require_roles("head", "admin"))):
    return [{"id": a.id, "actor": a.actor, "action": a.action, "entity": a.entity,
             "entity_id": a.entity_id, "details": a.details, "created_at": a.created_at}
            for a in db.query(AuditLog).order_by(AuditLog.id.desc()).limit(200).all()]


@app.post("/api/jobs/run-daily")
def run_daily(db: Session = Depends(get_db), user: User = Depends(require_roles("head", "admin", "nurse"))):
    """Ежедневный job: пересчёт просрочек, напоминания, эскалация красной зоны."""
    overdue = services.refresh_overdue(db)
    reminders = services.generate_reminders(db)
    tasks = services.escalate_red_zone(db)
    services.audit(db, user.full_name, "job.run_daily", "scheduler", None,
                   f"overdue={overdue} reminders={reminders} tasks={tasks}")
    db.commit()
    return {"overdue_marked": overdue, "reminders_created": reminders, "care_tasks_created": tasks}
