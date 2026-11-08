import re
from contextlib import asynccontextmanager
from datetime import date, timedelta
from hmac import compare_digest

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import rules, services, yandexgpt
from .config import settings
from .db import Base, SessionLocal, engine, get_db
from .models import AuditLog, CareTask, Encounter, Notification, Patient, PlanItem, User
from .schemas import (
    CareCompleteIn,
    ConsentIn,
    EncounterDraftIn,
    EncounterIn,
    GisEventIn,
    LoginIn,
    PatientIn,
    PatientPatch,
    PlanCompleteIn,
    PlanItemUpdateIn,
    TherapyIn,
)
from .security import create_token, get_current_user, require_roles, verify_password
from .seed import seed

DEFAULT_ORG = "ГАУЗ «Поликлиника №1», Казань"


def upgrade_audit_org_column():
    """One-time additive migration for pre-MVP SQLite/PostgreSQL databases."""
    inspector = inspect(engine)
    if "audit_logs" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("audit_logs")}
    if "org" in columns:
        return
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE audit_logs ADD COLUMN org VARCHAR(200)"))
        connection.execute(
            text("UPDATE audit_logs SET org = :org WHERE org IS NULL"),
            {"org": DEFAULT_ORG},
        )


upgrade_audit_org_column()
Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.seed_demo:
        db = SessionLocal()
        try:
            seed(db)
        finally:
            db.close()
    yield


app = FastAPI(
    title="ГепаНавигатор API",
    version="0.1.0",
    description="Модуль диспансерного наблюдения больных хроническими гепатитами (MVP, этап 2)",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def user_out(u: User):
    return {"id": u.id, "email": u.email, "full_name": u.full_name, "role": u.role, "org": u.org}


def patient_scope(db: Session, user: User):
    """Return patients the current staff member may access in the MVP.

    Doctors see assigned patients and unassigned referrals in their organization;
    care managers see their organization; admins have system-wide access.
    Analysts use aggregate analytics only and must not access identifiable records.
    """
    query = db.query(Patient)
    if user.role != "admin":
        query = query.filter(Patient.org == user.org)
        if user.role == "doctor":
            query = query.filter(or_(Patient.doctor_id == user.id, Patient.doctor_id.is_(None)))
    return query


def refresh_visible_overdue(db: Session, user: User) -> int:
    return services.refresh_overdue(
        db,
        org=None if user.role == "admin" else user.org,
        doctor_id=user.id if user.role == "doctor" else None,
    )


def ensure_patient_visible(patient: Patient, user: User):
    if user.role == "admin":
        return
    visible_org = patient.org == user.org
    visible_owner = user.role != "doctor" or patient.doctor_id in (None, user.id)
    if not visible_org or not visible_owner:
        # 404 avoids disclosing that a patient exists in another scope.
        raise HTTPException(404, "Пациент не найден")


def find_duplicate(db: Session, body: PatientIn) -> Patient | None:
    return services.find_duplicate_patient(
        db, full_name=body.full_name, birth_date=body.birth_date,
        snils=body.snils, oms=body.oms,
    )


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
                  db: Session = Depends(get_db),
                  user: User = Depends(require_roles("doctor", "head", "nurse"))):
    refresh_visible_overdue(db, user)
    q = patient_scope(db, user)
    if search:
        q = q.filter(Patient.full_name.ilike(f"%{search}%"))
    if status:
        q = q.filter(Patient.status == status)
    result = [services.patient_dict(db, p) for p in q.order_by(Patient.full_name).all()]
    if zone:
        result = [r for r in result if r["zone"] == zone]
    return result


@app.post("/api/patients", status_code=201)
def create_patient(body: PatientIn, db: Session = Depends(get_db),
                   user: User = Depends(require_roles("doctor", "head", "nurse"))):
    existing = find_duplicate(db, body)
    if existing:
        raise HTTPException(409, "Пациент уже есть в регистре: совпал СНИЛС, полис ОМС или ФИО + дата рождения")

    p = Patient(**body.model_dump(), doctor_id=user.id if user.role == "doctor" else None, org=user.org)
    try:
        db.add(p)
        db.flush()
        services.add_plan(db, p, rules.build_initial_plan(p.nosology, p.cirrhosis, p.enrolled_at))
        services.notify(db, p, "WELCOME",
                        "Здравствуйте! Вы поставлены на диспансерное наблюдение. "
                        "Первый приём запланирован; напоминания будут доступны при наличии согласия.",
                        date.today())
        services.audit(db, user.full_name, "patient.create", "patient", p.id, body.enrollment_trigger, org=user.org)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Пациент с таким СНИЛС или полисом ОМС уже есть в регистре")
    db.refresh(p)
    return services.patient_dict(db, p)


@app.get("/api/patients/{patient_id}")
def get_patient(patient_id: int, db: Session = Depends(get_db),
                user: User = Depends(require_roles("doctor", "head", "nurse"))):
    p = db.get(Patient, patient_id)
    if not p:
        raise HTTPException(404, "Пациент не найден")
    ensure_patient_visible(p, user)
    refresh_visible_overdue(db, user)
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
    ensure_patient_visible(p, user)
    updates = body.model_dump(exclude_none=True)
    if user.role == "nurse" and set(updates) - {"phone", "consent_notifications", "preferred_channel"}:
        raise HTTPException(403, "Медицинские и статусные поля может менять только врач")
    new_status = updates.get("status")
    terminal_statuses = {"DISCHARGED", "DECEASED"}
    if new_status is not None:
        if user.role not in ("doctor", "head", "admin"):
            raise HTTPException(403, "Снимать пациента с наблюдения может только врач")
        if new_status in ("ON_THERAPY", "POST_THERAPY"):
            raise HTTPException(422, "Статус терапии изменяется через назначение терапии")
        if p.status in terminal_statuses and new_status != p.status:
            raise HTTPException(409, "Нельзя повторно открыть снятого с наблюдения пациента")
        if new_status == "ACTIVE" and p.status != "ACTIVE":
            raise HTTPException(409, "Возврат в наблюдение требует отдельного клинического решения")
        if new_status in terminal_statuses and not (updates.get("discharge_reason") or p.discharge_reason):
            raise HTTPException(422, "Укажите причину снятия с наблюдения")
    elif "discharge_reason" in updates and p.status not in terminal_statuses:
        raise HTTPException(422, "Причину снятия укажите одновременно со статусом «снят с наблюдения»")

    for k, v in updates.items():
        setattr(p, k, v)
    if updates.get("consent_notifications") is False:
        db.query(Notification).filter(
            Notification.patient_id == p.id, Notification.status == "QUEUED"
        ).update({"status": "CANCELLED_NO_CONSENT"}, synchronize_session=False)
    if updates.get("status") in ("DISCHARGED", "DECEASED"):
        db.query(PlanItem).filter(
            PlanItem.patient_id == p.id, PlanItem.status.in_(("PLANNED", "OVERDUE"))
        ).update({"status": "CANCELLED"}, synchronize_session=False)
        db.query(CareTask).filter(
            CareTask.patient_id == p.id, CareTask.status == "OPEN"
        ).update({"status": "CANCELLED"}, synchronize_session=False)
        db.query(Notification).filter(
            Notification.patient_id == p.id, Notification.status == "QUEUED"
        ).update({"status": "CANCELLED_PATIENT_INACTIVE"}, synchronize_session=False)
    services.audit(db, user.full_name, "patient.update", "patient", p.id, str(updates), org=user.org)
    db.commit()
    return services.patient_dict(db, p)


@app.post("/api/patients/{patient_id}/consent")
def set_consent(patient_id: int, body: ConsentIn, db: Session = Depends(get_db),
                user: User = Depends(require_roles("doctor", "head", "nurse"))):
    p = db.get(Patient, patient_id)
    if not p:
        raise HTTPException(404, "Пациент не найден")
    ensure_patient_visible(p, user)
    p.consent_notifications = body.consent_notifications
    p.preferred_channel = body.preferred_channel
    if not body.consent_notifications:
        # Do not leave queued communications eligible for delivery after consent is withdrawn.
        db.query(Notification).filter(
            Notification.patient_id == p.id, Notification.status == "QUEUED"
        ).update({"status": "CANCELLED_NO_CONSENT"}, synchronize_session=False)
    services.audit(db, user.full_name, "patient.consent", "patient", p.id, str(body.consent_notifications), org=user.org)
    db.commit()
    return services.patient_dict(db, p)


# ---------- Клинический слой / план (блок 2) ----------
@app.patch("/api/plan-items/{item_id}")
def update_plan_item(item_id: int, body: PlanItemUpdateIn, db: Session = Depends(get_db),
                     user: User = Depends(require_roles("doctor", "head"))):
    item = db.get(PlanItem, item_id)
    if not item:
        raise HTTPException(404, "Событие плана не найдено")
    patient = db.get(Patient, item.patient_id)
    if not patient:
        raise HTTPException(404, "Пациент не найден")
    ensure_patient_visible(patient, user)
    if patient.status in ("DISCHARGED", "DECEASED"):
        raise HTTPException(409, "Нельзя менять план снятого с наблюдения пациента")
    if item.status != "PLANNED" or item.due_date <= date.today():
        raise HTTPException(409, "Редактировать можно только будущие запланированные события")

    previous = (item.title, item.due_date, item.window_days)
    item.title = body.title
    item.due_date = body.due_date
    item.window_days = body.window_days
    services.audit(
        db, user.full_name, "plan.edit", "plan_item", item.id,
        f"title={previous[0]!r}->{item.title!r}; due_date={previous[1]}->{item.due_date}; "
        f"window_days={previous[2]}->{item.window_days}; reason={body.reason}",
        org=user.org,
    )
    db.commit()
    return {
        "id": item.id, "kind": item.kind, "title": item.title, "due_date": item.due_date,
        "window_days": item.window_days,
        "status": rules.effective_status(item.status, item.due_date, item.window_days, date.today()),
    }


@app.post("/api/plan-items/{item_id}/complete")
def complete_item(item_id: int, body: PlanCompleteIn, db: Session = Depends(get_db),
                  user: User = Depends(require_roles("doctor", "head", "nurse"))):
    item = db.get(PlanItem, item_id)
    if not item:
        raise HTTPException(404, "Событие плана не найдено")
    patient = db.get(Patient, item.patient_id)
    if not patient:
        raise HTTPException(404, "Пациент не найден")
    ensure_patient_visible(patient, user)
    if user.role == "nurse" and item.kind in ("VISIT", "SVR12"):
        raise HTTPException(403, "Приём и контроль УВО может завершить только врач")
    if patient.status in ("DISCHARGED", "DECEASED"):
        raise HTTPException(409, "Снятого с наблюдения пациента нельзя вести по плану")
    if item.status in ("DONE", "CANCELLED"):
        raise HTTPException(409, "Событие уже выполнено или отменено")

    svr_result = None
    if item.kind == "SVR12":
        svr_result = rules.svr_result_achieved(body.result)
        if svr_result is None:
            raise HTTPException(422, "Для контроля УВО-12 укажите однозначный результат: например, «РНК не обнаружена» или «РНК обнаружена»")

    item.status = "DONE"
    item.completed_at = body.completed_at or date.today()
    item.result = body.result.strip() if body.result else None
    if item.kind == "SVR12":
        patient.svr12_achieved = svr_result
    services.audit(db, user.full_name, "plan.complete", "plan_item", item.id, f"{item.kind}: {body.result or ''}", org=user.org)
    db.commit()
    return {"id": item.id, "status": item.status, "completed_at": item.completed_at}


@app.post("/api/plan-items/{item_id}/cancel")
def cancel_item(item_id: int, db: Session = Depends(get_db),
                user: User = Depends(require_roles("doctor", "head"))):
    item = db.get(PlanItem, item_id)
    if not item:
        raise HTTPException(404, "Событие плана не найдено")
    patient = db.get(Patient, item.patient_id)
    if not patient:
        raise HTTPException(404, "Пациент не найден")
    ensure_patient_visible(patient, user)
    if item.status in ("DONE", "CANCELLED"):
        raise HTTPException(409, "Событие уже выполнено или отменено")
    item.status = "CANCELLED"
    services.audit(db, user.full_name, "plan.cancel", "plan_item", item.id, item.kind, org=user.org)
    db.commit()
    return {"id": item.id, "status": item.status}


# ---------- Приём врача (блок 3) ----------
@app.post("/api/patients/{patient_id}/encounters/draft")
def draft_encounter(patient_id: int, body: EncounterDraftIn, db: Session = Depends(get_db),
                    user: User = Depends(require_roles("doctor", "head"))):
    p = db.get(Patient, patient_id)
    if not p:
        raise HTTPException(404, "Пациент не найден")
    ensure_patient_visible(p, user)
    if p.status in ("DISCHARGED", "DECEASED"):
        raise HTTPException(409, "Нельзя формировать заключение для снятого с наблюдения пациента")
    if db.query(Encounter).filter(
        Encounter.patient_id == p.id, Encounter.visit_date == date.today()
    ).first():
        raise HTTPException(409, "Для пациента уже сохранена запись о приёме сегодня")

    next_item = db.query(PlanItem).filter(
        PlanItem.patient_id == p.id, PlanItem.status == "PLANNED", PlanItem.due_date >= date.today()
    ).order_by(PlanItem.due_date, PlanItem.id).first()
    next_step = (
        f"Ближайшее событие по текущему плану: {next_item.title} — {next_item.due_date.isoformat()}."
        if next_item else "Дальнейшие действия сверить с текущим планом наблюдения и клиническими рекомендациями."
    )
    if settings.yandexgpt_enabled:
        try:
            draft = yandexgpt.generate_conclusion(
                diagnosis_code=p.diagnosis_code,
                nosology=p.nosology,
                complaints=body.complaints,
                instructions=body.instructions,
                next_step=next_step,
            )
        except yandexgpt.YandexGPTConfigurationError:
            raise HTTPException(503, "YandexGPT включён, но не настроен. Проверьте серверную конфигурацию.") from None
        except yandexgpt.YandexGPTError:
            # Never substitute a local or fabricated response after a failed cloud call.
            raise HTTPException(502, "Не удалось получить черновик от YandexGPT. Попробуйте позже.") from None
        mode = "yandexgpt"
        notice = (
            "Черновик сформирован YandexGPT. Проверьте и отредактируйте его перед сохранением. "
            "В Yandex Cloud переданы введённые жалобы и инструкция, код диагноза и ближайшее событие плана; "
            "система не добавляет ФИО и регистрационные идентификаторы. Не вводите их в текст. Автоподпись не ставится."
        )
    else:
        draft = rules.draft_conclusion(p.full_name, p.nosology, p.diagnosis_code, body.complaints, next_step)
        mode = "demo"
        notice = "Сформирован локальный демонстрационный шаблон; YandexGPT не подключён."
        if body.instructions:
            notice += " Инструкция принята, но пока не обрабатывается моделью."
    return {"draft_conclusion": draft, "mode": mode, "notice": notice}


@app.post("/api/patients/{patient_id}/encounters", status_code=201)
def create_encounter(patient_id: int, body: EncounterIn, db: Session = Depends(get_db),
                     user: User = Depends(require_roles("doctor", "head"))):
    p = db.get(Patient, patient_id)
    if not p:
        raise HTTPException(404, "Пациент не найден")
    ensure_patient_visible(p, user)
    if p.status in ("DISCHARGED", "DECEASED"):
        raise HTTPException(409, "Нельзя создавать приём для снятого с наблюдения пациента")
    today = date.today()

    # One encounter per patient per day prevents double-clicks/retries from
    # advancing the monitoring plan more than once.
    existing_today = (db.query(Encounter).filter(
        Encounter.patient_id == p.id, Encounter.visit_date == today
    ).first())
    if existing_today:
        raise HTTPException(409, "Для пациента уже сохранена запись о приёме сегодня")

    if body.complete_visit_item:
        visits = (db.query(PlanItem).filter(
            PlanItem.patient_id == p.id,
            PlanItem.kind == "VISIT",
            PlanItem.status.in_(["PLANNED", "OVERDUE"]),
        ).order_by(PlanItem.due_date).all())
        # Never close a visit scheduled far in the future just because an encounter
        # was recorded today. The visit may be closed only within its grace window.
        visit = next((item for item in visits
                      if item.due_date <= today + timedelta(days=item.window_days)), None)
        if visit:
            visit.status = "DONE"
            visit.completed_at = today

    # Store the source draft separately from the physician-reviewed final text.
    # When the doctor enters a conclusion manually, no generated draft is fabricated after saving.
    # E-signature is not implemented: the encounter remains unsigned in this MVP.
    enc = Encounter(patient_id=p.id, doctor_id=user.id, visit_date=today, complaints=body.complaints,
                    conclusion=body.conclusion, draft_conclusion=body.draft_conclusion, signed=False)
    db.add(enc)
    db.flush()  # sessionmaker(autoflush=False): encounter is visible to the query below

    # Plan the next follow-up cycle only when another future visit is not already present.
    existing_next = (db.query(PlanItem).filter(PlanItem.patient_id == p.id, PlanItem.kind == "VISIT",
                                               PlanItem.status == "PLANNED",
                                               PlanItem.due_date > today).first())
    if not existing_next:
        services.add_plan(db, p, rules.plan_after_visit(today, p.cirrhosis))
    services.audit(db, user.full_name, "encounter.create", "encounter", None, f"patient={p.id}", org=user.org)
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
    ensure_patient_visible(p, user)
    if p.status in ("DISCHARGED", "DECEASED"):
        raise HTTPException(409, "Нельзя назначить терапию снятому с наблюдения пациенту")
    course_changed = (p.therapy_regimen, p.therapy_start, p.therapy_end) != (
        body.regimen, body.therapy_start, body.therapy_end
    )
    p.therapy_regimen, p.therapy_start, p.therapy_end = body.regimen, body.therapy_start, body.therapy_end
    if course_changed:
        p.svr12_achieved = None
        db.query(Notification).filter(
            Notification.patient_id == p.id,
            Notification.kind == "SVR12_REMINDER",
            Notification.status == "QUEUED",
        ).update({"status": "CANCELLED_SUPERSEDED"}, synchronize_session=False)

    if body.therapy_end:
        p.status = "POST_THERAPY"
        services.sync_svr_plan(db, p, body.therapy_end)
        text = ("После окончания терапии важен контроль УВО-12 "
                f"({(body.therapy_end + timedelta(weeks=12)).isoformat()}). Мы напомним заранее.")
        if not db.query(Notification).filter(
            Notification.patient_id == p.id,
            Notification.kind == "SVR12_REMINDER",
            Notification.text == text,
        ).first():
            services.notify(db, p, "SVR12_REMINDER", text, date.today())
    else:
        p.status = "ON_THERAPY"
        services.cancel_pending_svr_plan(db, p)
    services.audit(db, user.full_name, "therapy.set", "patient", p.id, body.regimen, org=user.org)
    db.commit()
    return services.patient_dict(db, p)


# ---------- Рабочее место: список на период (блок 3) ----------
@app.get("/api/worklist")
def worklist(db: Session = Depends(get_db),
            user: User = Depends(require_roles("doctor", "head", "nurse"))):
    refresh_visible_overdue(db, user)
    rows = [services.patient_dict(db, p) for p in
            patient_scope(db, user).filter(Patient.status.notin_(["DISCHARGED", "DECEASED"])).all()]
    rows.sort(key=lambda r: (r["next_due"] is None, r["next_due"] or date.max))
    summary = {z: sum(1 for r in rows if r["zone"] == z) for z in ("green", "yellow", "red", "purple")}
    return {"summary": summary, "patients": rows}


# ---------- Care Management (блок 4) ----------
@app.get("/api/care/tasks")
def list_tasks(status: str = "OPEN", db: Session = Depends(get_db),
               user: User = Depends(require_roles("doctor", "head", "nurse"))):
    visible_ids = [p.id for p in patient_scope(db, user).all()]
    q = db.query(CareTask).filter(CareTask.patient_id.in_(visible_ids))
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
    patient = db.get(Patient, t.patient_id)
    if not patient:
        raise HTTPException(404, "Задача не найдена")
    ensure_patient_visible(patient, user)
    if t.status != "OPEN":
        raise HTTPException(409, "Задача уже закрыта")
    t.status = "DONE"
    t.outcome = body.outcome
    t.comment = body.comment
    services.audit(db, user.full_name, "care.complete", "care_task", t.id, body.outcome, org=user.org)
    db.commit()
    return {"id": t.id, "status": t.status, "outcome": t.outcome}


# ---------- Коммуникации (блок 5) ----------
@app.get("/api/notifications")
def list_notifications(patient_id: int | None = None, db: Session = Depends(get_db),
                      user: User = Depends(require_roles("doctor", "head", "nurse"))):
    visible_ids = [p.id for p in patient_scope(db, user).all()]
    q = db.query(Notification).filter(Notification.patient_id.in_(visible_ids))
    if patient_id is not None:
        if patient_id not in visible_ids:
            raise HTTPException(404, "Пациент не найден")
        q = q.filter(Notification.patient_id == patient_id)
    return [{"id": n.id, "patient_id": n.patient_id, "channel": n.channel, "kind": n.kind,
             "text": n.text, "status": n.status, "scheduled_for": n.scheduled_for}
            for n in q.order_by(Notification.id.desc()).limit(200).all()]


# ---------- Интеграции: события ГИС ЭЗ РТ / ФРВГ (блок 6) ----------
@app.post("/api/integrations/gis/events")
def gis_event(body: GisEventIn, response: Response, db: Session = Depends(get_db),
              x_integration_key: str = Header(default="")):
    if not compare_digest(x_integration_key, settings.integration_key):
        raise HTTPException(403, "Неверный ключ интеграции")
    code = (body.code or body.patient.diagnosis_code or "").upper()
    positive_triggers = {"PCR_POSITIVE", "HBSAG_POSITIVE", "ANTI_HCV_POSITIVE"}
    chronic_hepatitis_code = bool(re.fullmatch(r"B18(?:\.[01289])?", code))
    if not chronic_hepatitis_code and code not in positive_triggers:
        return {"enrolled": False, "reason": f"Событие {code} не является триггером постановки на учёт"}
    existing = find_duplicate(db, body.patient)
    if existing:
        return {"enrolled": True, "duplicate": True, "patient_id": existing.id}
    trigger = "frvg" if body.event_type == "RegistryRecord" else "gis_event"
    p = Patient(**body.patient.model_dump(exclude={"enrollment_trigger"}),
                enrollment_trigger=trigger, org=DEFAULT_ORG)
    try:
        db.add(p)
        db.flush()
        services.add_plan(db, p, rules.build_initial_plan(p.nosology, p.cirrhosis, p.enrolled_at))
        services.notify(db, p, "WELCOME", "Здравствуйте! Вы поставлены на диспансерное наблюдение. "
                                          "Напоминания будут доступны при наличии согласия.", date.today())
        services.audit(db, "gis-integration", "patient.auto_enroll", "patient", p.id, code, org=DEFAULT_ORG)
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = find_duplicate(db, body.patient)
        if existing:
            return {"enrolled": True, "duplicate": True, "patient_id": existing.id}
        raise HTTPException(409, "Не удалось добавить событие: возможен дубликат пациента")
    db.refresh(p)
    response.status_code = 201
    return {"enrolled": True, "duplicate": False, "patient_id": p.id}


# ---------- Аналитика (блок 7) ----------
@app.get("/api/analytics/overview")
def analytics(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    patients = patient_scope(db, user).all()
    active = [p for p in patients if p.status not in ("DISCHARGED", "DECEASED")]
    patient_ids = [p.id for p in patients]
    items = db.query(PlanItem).filter(PlanItem.patient_id.in_(patient_ids)).all() if patient_ids else []
    item_status = {
        i.id: rules.effective_status(i.status, i.due_date, i.window_days, date.today())
        for i in items
    }
    done = sum(1 for i in items if item_status[i.id] == "DONE")
    overdue = sum(1 for i in items if item_status[i.id] == "OVERDUE")
    checked_ids = {i.patient_id for i in items if i.kind == "SVR12" and item_status[i.id] == "DONE"}
    svr_total = len(checked_ids)
    svr_ok = sum(1 for p in patients if p.id in checked_ids and p.svr12_achieved is True)
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
    query = db.query(AuditLog)
    if user.role != "admin":
        query = query.filter(AuditLog.org == user.org)
    return [{"id": a.id, "actor": a.actor, "action": a.action, "entity": a.entity,
             "entity_id": a.entity_id, "details": a.details, "created_at": a.created_at}
            for a in query.order_by(AuditLog.id.desc()).limit(200).all()]


@app.post("/api/jobs/run-daily")
def run_daily(db: Session = Depends(get_db), user: User = Depends(require_roles("head", "admin", "nurse"))):
    """Ежедневный job: пересчёт просрочек, напоминания, эскалация красной зоны."""
    org = None if user.role == "admin" else user.org
    overdue = services.refresh_overdue(db, org=org)
    reminders = services.generate_reminders(db, org=org)
    tasks = services.escalate_red_zone(db, org=org)
    services.audit(db, user.full_name, "job.run_daily", "scheduler", None,
                   f"overdue={overdue} reminders={reminders} tasks={tasks}", org=org)
    db.commit()
    return {"overdue_marked": overdue, "reminders_created": reminders, "care_tasks_created": tasks}
