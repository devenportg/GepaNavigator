"""API-тесты: регистр, RBAC, дедупликация, приём, терапия/УВО, коммуникации, аналитика."""
import time
from datetime import date, timedelta

import jwt
from app.config import settings
from app.db import SessionLocal
from app.models import CareTask, Notification, Patient, PlanItem, User
from app.security import hash_password
from tests.conftest import login

PATIENT = {
    "full_name": "Тестов Тест Тестович", "birth_date": "1990-05-10", "sex": "M",
    "snils": "999-888-777 01", "oms": "1600000000999901", "phone": "+79170009901",
    "consent_notifications": True, "diagnosis_code": "B18.2",
    "nosology": "HCV", "fibrosis_stage": "F2", "cirrhosis": False,
}


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_auth_rejects_bad_password(client):
    r = client.post("/api/auth/login", json={"email": "doctor@gepa.local", "password": "wrong"})
    assert r.status_code == 401


def test_unauthorized_without_token(client):
    assert client.get("/api/patients").status_code == 401


def test_malformed_signed_token_returns_401_instead_of_server_error(client):
    token = jwt.encode({"exp": int(time.time()) + 60}, settings.jwt_secret, algorithm="HS256")
    response = client.get("/api/patients", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_seed_worklist_has_zones(client, doctor):
    r = client.get("/api/worklist", headers=doctor)
    assert r.status_code == 200
    data = r.json()
    assert data["summary"]["red"] >= 1
    assert data["summary"]["purple"] == 1  # пациент на контроле УВО-12


def test_create_patient_generates_plan_and_welcome(client, doctor):
    r = client.post("/api/patients", json=PATIENT, headers=doctor)
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["zone"] in ("yellow", "green", "red")
    assert {i["kind"] for i in p["plan"]} >= {"VISIT", "LABS", "PCR"}
    notes = client.get(f"/api/notifications?patient_id={p['id']}", headers=doctor).json()
    assert any(n["kind"] == "WELCOME" and n["status"] == "QUEUED" for n in notes)


def test_duplicate_patient_rejected(client, doctor):
    by_snils = dict(PATIENT, full_name="Другой Человек Пациент", birth_date="1991-02-03",
                    snils="999 888 777 01", oms="1600000000999902")
    assert client.post("/api/patients", json=by_snils, headers=doctor).status_code == 409
    by_oms = dict(PATIENT, full_name="Ещё Один Пациент", birth_date="1992-02-03",
                  snils="999-888-777 09")
    assert client.post("/api/patients", json=by_oms, headers=doctor).status_code == 409
    by_name_and_birth = dict(PATIENT, full_name="  ТЕСТОВ   ТЕСТ ТЕСТОВИЧ ", snils="99988877709",
                             oms="1600000000999909")
    assert client.post("/api/patients", json=by_name_and_birth, headers=doctor).status_code == 409


def test_analyst_cannot_create_patient(client, analyst):
    body = dict(PATIENT, snils="999-888-777 02", full_name="Другой Пациент Пациентович")
    assert client.post("/api/patients", json=body, headers=analyst).status_code == 403


def test_complete_plan_item_and_encounter_flow(client, doctor):
    patients = client.get("/api/patients?search=Тестов", headers=doctor).json()
    pid = patients[0]["id"]
    detail = client.get(f"/api/patients/{pid}", headers=doctor).json()
    labs = next(i for i in detail["plan"] if i["kind"] == "LABS")
    r = client.post(f"/api/plan-items/{labs['id']}/complete",
                    json={"result": "АЛТ 22, АСТ 19"}, headers=doctor)
    assert r.status_code == 200 and r.json()["status"] == "DONE"

    r = client.post(f"/api/patients/{pid}/encounters",
                    json={"complaints": "Жалоб нет.", "conclusion": "Продолжить наблюдение."}, headers=doctor)
    assert r.status_code == 201
    assert r.json()["signed"] is False  # текст не считается электронной подписью
    assert "Черновик заключения" in r.json()["draft_conclusion"]
    detail = client.get(f"/api/patients/{pid}", headers=doctor).json()
    assert any(i["kind"] == "VISIT" and i["status"] == "PLANNED" for i in detail["plan"])  # следующий визит +6 мес


def test_completed_plan_item_is_first_when_due_dates_match(client, doctor):
    body = dict(PATIENT, full_name="Сортировка Плана Пациент", snils="99988877733",
                oms="1600000000999933")
    response = client.post("/api/patients", json=body, headers=doctor)
    assert response.status_code == 201
    patient_id = response.json()["id"]
    shared_date = date.today() + timedelta(days=400)

    db = SessionLocal()
    try:
        still_open = PlanItem(
            patient_id=patient_id, kind="LABS", title="Оставшееся событие",
            due_date=shared_date, status="PLANNED", window_days=14,
        )
        completed = PlanItem(
            patient_id=patient_id, kind="PCR", title="Отмеченное событие",
            due_date=shared_date, status="PLANNED", window_days=14,
        )
        db.add_all([still_open, completed])
        db.commit()
        still_open_id, completed_id = still_open.id, completed.id
    finally:
        db.close()

    result = client.post(f"/api/plan-items/{completed_id}/complete",
                         json={"result": "Выполнено"}, headers=doctor)
    assert result.status_code == 200
    detail = client.get(f"/api/patients/{patient_id}", headers=doctor).json()
    same_date = [item for item in detail["plan"] if item["due_date"] == shared_date.isoformat()]
    assert [item["id"] for item in same_date] == [completed_id, still_open_id]


def test_repeated_same_day_encounter_is_rejected_without_adding_another_plan_cycle(client, doctor):
    body = dict(PATIENT, full_name="Повторный Приём Пациент", snils="99988877731",
                oms="1600000000999931")
    patient = client.post("/api/patients", json=body, headers=doctor).json()
    endpoint = f"/api/patients/{patient['id']}/encounters"

    first = client.post(endpoint, json={"complaints": "Контрольный визит"}, headers=doctor)
    assert first.status_code == 201
    after_first = client.get(f"/api/patients/{patient['id']}", headers=doctor).json()
    plan_count = len(after_first["plan"])
    assert len(after_first["encounters"]) == 1
    assert any(item["kind"] == "VISIT" and item["status"] == "PLANNED"
               and item["due_date"] > date.today().isoformat() for item in after_first["plan"])

    repeated = client.post(endpoint, json={"complaints": "Повторный клик"}, headers=doctor)
    assert repeated.status_code == 409
    assert "уже сохранена" in repeated.json()["detail"]
    after_repeat = client.get(f"/api/patients/{patient['id']}", headers=doctor).json()
    assert len(after_repeat["encounters"]) == 1
    assert len(after_repeat["plan"]) == plan_count


def test_encounter_does_not_complete_a_visit_scheduled_far_in_the_future(client, doctor):
    body = dict(PATIENT, full_name="Будущий Визит Пациент", snils="99988877732",
                oms="1600000000999932")
    patient = client.post("/api/patients", json=body, headers=doctor).json()
    db = SessionLocal()
    try:
        initial_visit = db.query(PlanItem).filter(
            PlanItem.patient_id == patient["id"], PlanItem.kind == "VISIT"
        ).one()
        initial_visit.status = "DONE"
        initial_visit.completed_at = date.today()
        future_visit = PlanItem(
            patient_id=patient["id"], kind="VISIT", title="Плановый приём через полгода",
            due_date=date.today() + timedelta(days=180), window_days=14,
            status="PLANNED", rule_ref="Тест будущего визита",
        )
        db.add(future_visit)
        db.commit()
        future_visit_id = future_visit.id
    finally:
        db.close()

    response = client.post(f"/api/patients/{patient['id']}/encounters", json={}, headers=doctor)
    assert response.status_code == 201
    after = client.get(f"/api/patients/{patient['id']}", headers=doctor).json()
    kept_visit = next(item for item in after["plan"] if item["id"] == future_visit_id)
    assert kept_visit["status"] == "PLANNED"
    assert sum(item["kind"] == "VISIT" and item["status"] == "PLANNED"
               for item in after["plan"]) == 1


def test_whitespace_encounter_text_is_stored_as_empty_unsigned_draft(client, doctor):
    body = dict(PATIENT, full_name="Пробелы В Заключении", snils="99988877721",
                oms="1600000000999921")
    patient = client.post("/api/patients", json=body, headers=doctor).json()
    response = client.post(f"/api/patients/{patient['id']}/encounters",
                           json={"complaints": "   ", "conclusion": "  \n "}, headers=doctor)
    assert response.status_code == 201
    assert response.json()["signed"] is False
    assert response.json()["conclusion"] is None


def test_therapy_end_creates_svr12_idempotently_and_validates_dates(client, doctor):
    pid = client.get("/api/patients?search=Тестов", headers=doctor).json()[0]["id"]
    end = date.today() - timedelta(days=10)
    therapy = {"regimen": "Софосбувир/Велпатасвир", "therapy_start": "2026-01-01",
               "therapy_end": end.isoformat()}
    r = client.post(f"/api/patients/{pid}/therapy", json=therapy, headers=doctor)
    assert r.status_code == 200
    assert r.json()["status"] == "POST_THERAPY"
    svr = next(i for i in r.json()["plan"] if i["kind"] == "SVR12")
    assert svr["due_date"] == (end + timedelta(weeks=12)).isoformat()

    repeated = client.post(f"/api/patients/{pid}/therapy", json=therapy, headers=doctor)
    assert repeated.status_code == 200
    assert sum(i["kind"] == "SVR12" and i["status"] != "CANCELLED"
               for i in repeated.json()["plan"]) == 1

    invalid = dict(therapy, therapy_start=date.today().isoformat(), therapy_end=end.isoformat())
    assert client.post(f"/api/patients/{pid}/therapy", json=invalid, headers=doctor).status_code == 422

    assert client.post(f"/api/plan-items/{svr['id']}/complete", json={"result": "УВО"},
                       headers=doctor).status_code == 422
    assert client.post(f"/api/plan-items/{svr['id']}/complete", json={"result": "УВО не достигнут"},
                       headers=doctor).status_code == 200
    detail = client.get(f"/api/patients/{pid}", headers=doctor).json()
    assert detail["svr12_achieved"] is False
    assert client.post(f"/api/plan-items/{svr['id']}/complete", json={"result": "РНК не обнаружена"},
                       headers=doctor).status_code == 409


def test_cancelled_plan_item_cannot_be_completed(client, doctor):
    body = dict(PATIENT, full_name="Отменённый План Пациента", snils="99988877717",
                oms="1600000000999917")
    patient = client.post("/api/patients", json=body, headers=doctor).json()
    visit = next(item for item in patient["plan"] if item["kind"] == "VISIT")
    assert client.post(f"/api/plan-items/{visit['id']}/cancel", headers=doctor).status_code == 200
    assert client.post(f"/api/plan-items/{visit['id']}/complete", json={}, headers=doctor).status_code == 409
    assert client.post(f"/api/plan-items/{visit['id']}/cancel", headers=doctor).status_code == 409


def test_gis_webhook_enrolls_and_dedupes(client):
    body = {"event_type": "Condition", "code": "B18.2",
            "patient": dict(PATIENT, full_name="Вебхук Пациент Событийный", snils="999-888-777 03",
                            oms="1600000000999903")}
    h = {"X-Integration-Key": settings.integration_key}
    r = client.post("/api/integrations/gis/events", json=body, headers=h)
    assert r.status_code == 201 and r.json()["enrolled"] is True
    r2 = client.post("/api/integrations/gis/events", json=body, headers=h)
    assert r2.status_code == 200 and r2.json()["duplicate"] is True
    assert client.post("/api/integrations/gis/events", json=body, headers={}).status_code == 403
    assert client.post("/api/integrations/gis/events", json=body,
                       headers={"X-Integration-Key": "incorrect-integration-key"}).status_code == 403


def test_non_trigger_event_ignored(client):
    body = {"event_type": "Condition", "code": "J06.9",
            "patient": dict(PATIENT, full_name="Простуда Обычная Тестовна", snils="999-888-777 04")}
    r = client.post("/api/integrations/gis/events", json=body, headers={"X-Integration-Key": settings.integration_key})
    assert r.status_code == 200 and r.json()["enrolled"] is False
    malformed = dict(body, code="B18.NOTVALID",
                     patient=dict(body["patient"], full_name="Неверный Код События", snils="999-888-777 06"))
    r = client.post("/api/integrations/gis/events", json=malformed,
                    headers={"X-Integration-Key": settings.integration_key})
    assert r.status_code == 200 and r.json()["enrolled"] is False


def test_notifications_respect_consent(client, doctor):
    body = dict(PATIENT, full_name="Без Согласия Пациентович", snils="999-888-777 05",
                oms="1600000000999905", consent_notifications=False)
    p = client.post("/api/patients", json=body, headers=doctor).json()
    notes = client.get(f"/api/notifications?patient_id={p['id']}", headers=doctor).json()
    assert notes and all(n["status"] == "SKIPPED_NO_CONSENT" for n in notes)


def test_notifications_are_opt_in_and_revocation_cancels_queued(client, doctor):
    no_consent = dict(PATIENT, full_name="Согласие Не Дано", snils="99988877710",
                      oms="1600000000999910")
    no_consent.pop("consent_notifications")
    p = client.post("/api/patients", json=no_consent, headers=doctor)
    assert p.status_code == 201 and p.json()["consent_notifications"] is False
    notes = client.get(f"/api/notifications?patient_id={p.json()['id']}", headers=doctor).json()
    assert notes and all(n["status"] == "SKIPPED_NO_CONSENT" for n in notes)

    opted_in = dict(PATIENT, full_name="Согласие Отозвано", snils="99988877711",
                    oms="1600000000999911", consent_notifications=True)
    created = client.post("/api/patients", json=opted_in, headers=doctor).json()
    assert client.post(f"/api/patients/{created['id']}/consent",
                       json={"consent_notifications": False, "preferred_channel": "sms"},
                       headers=doctor).status_code == 200
    notes = client.get(f"/api/notifications?patient_id={created['id']}", headers=doctor).json()
    assert notes and all(n["status"] == "CANCELLED_NO_CONSENT" for n in notes)


def test_discharge_closes_future_work_and_rejects_invalid_transitions(client, doctor, nurse):
    body = dict(PATIENT, full_name="Снятие Проверка", snils="99988877719",
                oms="1600000000999919", consent_notifications=True)
    created = client.post("/api/patients", json=body, headers=doctor).json()
    db = SessionLocal()
    try:
        visit = db.query(PlanItem).filter(
            PlanItem.patient_id == created["id"], PlanItem.kind == "VISIT"
        ).first()
        visit.status = "OVERDUE"
        task = CareTask(patient_id=created["id"], kind="CALL", title="Проверка снятия", priority="normal")
        db.add(task)
        db.commit()
        visit_id = visit.id
    finally:
        db.close()

    endpoint = f"/api/patients/{created['id']}"
    assert client.patch(endpoint, json={"fibrosis_stage": "F3"}, headers=nurse).status_code == 403
    assert client.post(f"/api/plan-items/{visit_id}/complete", json={}, headers=nurse).status_code == 403
    assert client.patch(endpoint, json={"status": "DISCHARGED", "discharge_reason": "Переезд"},
                        headers=nurse).status_code == 403
    assert client.patch(endpoint, json={"status": "DISCHARGED"}, headers=doctor).status_code == 422
    response = client.patch(endpoint, json={"status": "DISCHARGED", "discharge_reason": "Переезд"},
                            headers=doctor)
    assert response.status_code == 200 and response.json()["status"] == "DISCHARGED"
    assert client.patch(endpoint, json={"status": "ACTIVE"}, headers=doctor).status_code == 409
    assert client.post(f"/api/plan-items/{visit_id}/complete", json={}, headers=doctor).status_code == 409
    assert client.post(f"{endpoint}/encounters", json={}, headers=doctor).status_code == 409
    assert client.post(f"{endpoint}/therapy", json={"regimen": "DAA", "therapy_start": date.today().isoformat()},
                       headers=doctor).status_code == 409

    db = SessionLocal()
    try:
        assert db.query(PlanItem).filter(
            PlanItem.patient_id == created["id"], PlanItem.status.in_(("PLANNED", "OVERDUE"))
        ).count() == 0
        assert db.query(CareTask).filter(CareTask.patient_id == created["id"],
                                         CareTask.status == "OPEN").count() == 0
        assert db.query(Notification).filter(
            Notification.patient_id == created["id"], Notification.status == "QUEUED"
        ).count() == 0
    finally:
        db.close()


def test_daily_reminders_are_deduplicated_and_respect_new_consent(client, doctor):
    body = dict(PATIENT, full_name="Напоминание Проверка", snils="99988877716",
                oms="1600000000999916", consent_notifications=False)
    patient = client.post("/api/patients", json=body, headers=doctor).json()
    head = login(client, "head@gepa.local", "head12345")
    assert client.post("/api/jobs/run-daily", headers=head).status_code == 200
    assert client.post("/api/jobs/run-daily", headers=head).status_code == 200
    notes = client.get(f"/api/notifications?patient_id={patient['id']}", headers=doctor).json()
    visit_notes = [n for n in notes if n["kind"] == "VISIT_REMINDER"]
    assert len(visit_notes) == 1 and visit_notes[0]["status"] == "SKIPPED_NO_CONSENT"

    assert client.post(f"/api/patients/{patient['id']}/consent",
                       json={"consent_notifications": True, "preferred_channel": "sms"},
                       headers=doctor).status_code == 200
    client.post("/api/jobs/run-daily", headers=head).raise_for_status()
    notes = client.get(f"/api/notifications?patient_id={patient['id']}", headers=doctor).json()
    visit_notes = [n for n in notes if n["kind"] == "VISIT_REMINDER"]
    assert len(visit_notes) == 1 and visit_notes[0]["status"] == "QUEUED"


def test_invalid_patient_data_returns_422(client, doctor):
    invalid_diagnosis = dict(PATIENT, full_name="Неверный Код", snils="99988877712",
                             oms="1600000000999912", diagnosis_code="J06.9")
    assert client.post("/api/patients", json=invalid_diagnosis, headers=doctor).status_code == 422
    invalid_stage = dict(PATIENT, full_name="Неверный Фиброз", snils="99988877713",
                         oms="1600000000999913", fibrosis_stage="F9")
    assert client.post("/api/patients", json=invalid_stage, headers=doctor).status_code == 422
    future_birth = dict(PATIENT, full_name="Будущий Пациент", snils="99988877714",
                        oms="1600000000999914", birth_date=(date.today() + timedelta(days=1)).isoformat())
    assert client.post("/api/patients", json=future_birth, headers=doctor).status_code == 422


def test_analyst_is_aggregate_only(client, analyst, doctor):
    patient_id = client.get("/api/worklist", headers=doctor).json()["patients"][0]["id"]
    assert client.get("/api/patients", headers=analyst).status_code == 403
    assert client.get("/api/worklist", headers=analyst).status_code == 403
    assert client.get(f"/api/patients/{patient_id}", headers=analyst).status_code == 403
    assert client.get("/api/notifications", headers=analyst).status_code == 403
    assert client.get("/api/care/tasks", headers=analyst).status_code == 403
    assert client.get("/api/analytics/overview", headers=analyst).status_code == 200


def test_doctor_cannot_read_another_doctors_or_org_patient(client, doctor):
    body = dict(PATIENT, full_name="Чужая Область Доступа", snils="99988877715",
                oms="1600000000999915")
    patient = client.post("/api/patients", json=body, headers=doctor).json()
    db = SessionLocal()
    try:
        other = User(email="other-doctor@gepa.local", password_hash=hash_password("other123"),
                     full_name="Другой врач", role="doctor", org="ГАУЗ Другая МО")
        db.add(other)
        db.commit()
        db.refresh(other)
        record = db.get(Patient, patient["id"])
        record.doctor_id = other.id
        record.org = other.org
        db.commit()
        other_id = other.id
    finally:
        db.close()

    assert client.get(f"/api/patients/{patient['id']}", headers=doctor).status_code == 404
    other_headers = login(client, "other-doctor@gepa.local", "other123")
    assert client.get(f"/api/patients/{patient['id']}", headers=other_headers).status_code == 200
    assert other_id > 0


def test_doctor_refresh_is_assignment_scoped_and_analytics_is_read_only(client, doctor):
    body = dict(PATIENT, full_name="Чужой Врач Просрочка", snils="99988877720",
                oms="1600000000999920")
    patient = client.post("/api/patients", json=body, headers=doctor).json()
    db = SessionLocal()
    try:
        other = User(email="scope-same-org-doctor@gepa.local", password_hash=hash_password("other123"),
                     full_name="Врач в той же МО", role="doctor")
        db.add(other)
        db.flush()
        record = db.get(Patient, patient["id"])
        record.doctor_id = other.id
        visit = db.query(PlanItem).filter(PlanItem.patient_id == record.id, PlanItem.kind == "VISIT").first()
        visit.due_date = date.today() - timedelta(days=60)
        db.commit()
        item_id, patient_id = visit.id, record.id
    finally:
        db.close()

    assert all(row["id"] != patient_id for row in client.get("/api/worklist", headers=doctor).json()["patients"])
    db = SessionLocal()
    try:
        assert db.get(PlanItem, item_id).status == "PLANNED"
    finally:
        db.close()

    head = login(client, "head@gepa.local", "head12345")
    assert client.get("/api/analytics/overview", headers=head).status_code == 200
    db = SessionLocal()
    try:
        assert db.get(PlanItem, item_id).status == "PLANNED"
    finally:
        db.close()
    assert any(row["id"] == patient_id for row in client.get("/api/worklist", headers=head).json()["patients"])
    db = SessionLocal()
    try:
        assert db.get(PlanItem, item_id).status == "OVERDUE"
    finally:
        db.close()


def test_daily_job_does_not_touch_another_organization(client, doctor):
    body = dict(PATIENT, full_name="Другая МО Просрочка", snils="99988877718",
                oms="1600000000999918")
    patient = client.post("/api/patients", json=body, headers=doctor).json()
    db = SessionLocal()
    try:
        other = User(email="job-scope-doctor@gepa.local", password_hash=hash_password("other123"),
                     full_name="Врач другой МО", role="doctor", org="Другая медицинская организация")
        db.add(other)
        db.flush()
        record = db.get(Patient, patient["id"])
        record.org = other.org
        record.doctor_id = other.id
        visit = db.query(PlanItem).filter(PlanItem.patient_id == record.id, PlanItem.kind == "VISIT").first()
        visit.due_date = date.today() - timedelta(days=60)
        db.commit()
        patient_id, item_id = record.id, visit.id
    finally:
        db.close()

    head = login(client, "head@gepa.local", "head12345")
    assert client.post("/api/jobs/run-daily", headers=head).status_code == 200
    db = SessionLocal()
    try:
        assert db.get(PlanItem, item_id).status == "PLANNED"
        assert db.query(CareTask).filter(CareTask.patient_id == patient_id).count() == 0
    finally:
        db.close()


def test_head_audit_is_organization_scoped_admin_can_see_all(client):
    db = SessionLocal()
    try:
        other = User(email="audit-other-doctor@gepa.local", password_hash=hash_password("other123"),
                     full_name="Врач аудита другой МО", role="doctor", org="МО для проверки аудита")
        db.add(other)
        db.commit()
    finally:
        db.close()
    other_headers = login(client, "audit-other-doctor@gepa.local", "other123")
    body = dict(PATIENT, full_name="Аудит Другая Организация", snils="99988877722",
                oms="1600000000999922")
    patient = client.post("/api/patients", json=body, headers=other_headers).json()

    head = login(client, "head@gepa.local", "head12345")
    own_audit = client.get("/api/audit", headers=head)
    assert own_audit.status_code == 200
    assert all(row["entity_id"] != patient["id"] for row in own_audit.json())
    admin = login(client, "admin@gepa.local", "admin12345")
    all_audit = client.get("/api/audit", headers=admin)
    assert any(row["entity"] == "patient" and row["entity_id"] == patient["id"]
               for row in all_audit.json())


def test_daily_job_and_analytics(client):
    head = login(client, "head@gepa.local", "head12345")
    r = client.post("/api/jobs/run-daily", headers=head)
    assert r.status_code == 200
    a = client.get("/api/analytics/overview", headers=head).json()
    assert a["active_total"] >= 8
    assert a["zones"]["red"] >= 1
    tasks = client.get("/api/care/tasks", headers=head).json()
    assert len(tasks) >= 1  # эскалация красной зоны создала задачи обзвона


def test_care_task_outcome_validation(client, nurse):
    tasks = client.get("/api/care/tasks", headers=nurse).json()
    if not tasks:
        return
    tid = tasks[0]["id"]
    assert client.post(f"/api/care/tasks/{tid}/complete", json={"outcome": "BOGUS"}, headers=nurse).status_code == 422
    r = client.post(f"/api/care/tasks/{tid}/complete", json={"outcome": "WILL_COME", "comment": "Подтвердил явку"}, headers=nurse)
    assert r.status_code == 200 and r.json()["outcome"] == "WILL_COME"


def test_audit_visible_only_to_head(client, doctor):
    assert client.get("/api/audit", headers=doctor).status_code == 403
    head = login(client, "head@gepa.local", "head12345")
    assert client.get("/api/audit", headers=head).status_code == 200
