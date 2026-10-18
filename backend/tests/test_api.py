"""API-тесты: регистр, RBAC, дедупликация, приём, терапия/УВО, коммуникации, аналитика."""
from datetime import date, timedelta

from tests.conftest import login

PATIENT = {
    "full_name": "Тестов Тест Тестович", "birth_date": "1990-05-10", "sex": "M",
    "snils": "999-888-777 01", "phone": "+79170009901", "diagnosis_code": "B18.2",
    "nosology": "HCV", "fibrosis_stage": "F2", "cirrhosis": False,
}


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_auth_rejects_bad_password(client):
    r = client.post("/api/auth/login", json={"email": "doctor@gepa.local", "password": "wrong"})
    assert r.status_code == 401


def test_unauthorized_without_token(client):
    assert client.get("/api/patients").status_code == 401


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
    r = client.post("/api/patients", json=PATIENT, headers=doctor)
    assert r.status_code == 409


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
    assert "Черновик заключения" in r.json()["draft_conclusion"]
    detail = client.get(f"/api/patients/{pid}", headers=doctor).json()
    assert any(i["kind"] == "VISIT" and i["status"] == "PLANNED" for i in detail["plan"])  # следующий визит +6 мес


def test_therapy_end_creates_svr12(client, doctor):
    pid = client.get("/api/patients?search=Тестов", headers=doctor).json()[0]["id"]
    end = date.today() - timedelta(days=10)
    r = client.post(f"/api/patients/{pid}/therapy",
                    json={"regimen": "Софосбувир/Велпатасвир", "therapy_start": "2026-01-01",
                          "therapy_end": end.isoformat()}, headers=doctor)
    assert r.status_code == 200
    assert r.json()["status"] == "POST_THERAPY"
    svr = next(i for i in r.json()["plan"] if i["kind"] == "SVR12")
    assert svr["due_date"] == (end + timedelta(weeks=12)).isoformat()


def test_gis_webhook_enrolls_and_dedupes(client):
    body = {"event_type": "Condition", "code": "B18.2",
            "patient": dict(PATIENT, full_name="Вебхук Пациент Событийный", snils="999-888-777 03")}
    h = {"X-Integration-Key": "gis-demo-key"}
    r = client.post("/api/integrations/gis/events", json=body, headers=h)
    assert r.status_code == 201 and r.json()["enrolled"] is True
    r2 = client.post("/api/integrations/gis/events", json=body, headers=h)
    assert r2.json()["duplicate"] is True
    assert client.post("/api/integrations/gis/events", json=body, headers={}).status_code == 403


def test_non_trigger_event_ignored(client):
    body = {"event_type": "Condition", "code": "J06.9",
            "patient": dict(PATIENT, full_name="Простуда Обычная Тестовна", snils="999-888-777 04")}
    r = client.post("/api/integrations/gis/events", json=body, headers={"X-Integration-Key": "gis-demo-key"})
    assert r.json()["enrolled"] is False


def test_notifications_respect_consent(client, doctor):
    body = dict(PATIENT, full_name="Без Согласия Пациентович", snils="999-888-777 05",
                consent_notifications=False)
    p = client.post("/api/patients", json=body, headers=doctor).json()
    notes = client.get(f"/api/notifications?patient_id={p['id']}", headers=doctor).json()
    assert notes and all(n["status"] == "SKIPPED_NO_CONSENT" for n in notes)


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
