"""E2E-проверка полного клинического сценария (п. 2.3) через реальный HTTP-стек:

backend (uvicorn) + собранный frontend (vite preview, /api проксируется на backend).
Сценарий повторяет ключевой поток из docs/03 §3.3.4:
событие ГИС -> регистр -> план по КР -> рабочее место -> приём -> ПВТ -> УВО-12 ->
напоминания/эскалация -> обзвон -> аналитика и аудит.
"""
import os
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
# Backend на 8000: именно туда смотрит proxy в frontend/vite.config.ts (единая точка входа UI)
BE_PORT, FE_PORT = 8000, 5174
BE = f"http://127.0.0.1:{BE_PORT}"
FE = f"http://127.0.0.1:{FE_PORT}"


def wait_ok(url: str, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(url, timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"Сервис не поднялся: {url}")


@pytest.fixture(scope="session", autouse=True)
def stack(tmp_path_factory):
    db = tmp_path_factory.mktemp("e2e") / "e2e.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db}", "SEED_DEMO": "true"}
    be = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(BE_PORT)],
        cwd=ROOT / "backend", env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    fe = None
    try:
        wait_ok(f"{BE}/health")
        if not (ROOT / "frontend" / "dist" / "index.html").exists():
            subprocess.run(["npm", "run", "build"], cwd=ROOT / "frontend", check=True,
                           stdout=subprocess.DEVNULL)
        fe = subprocess.Popen(
            ["node", "node_modules/vite/bin/vite.js", "preview", "--port", str(FE_PORT), "--strictPort"],
            cwd=ROOT / "frontend", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
        wait_ok(FE)
        yield
    finally:
        for proc in (fe, be):
            if proc:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()


def login(client, base, email, password):
    r = client.post(f"{base}/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def client():
    with httpx.Client(timeout=10) as c:
        yield c


@pytest.fixture(scope="session")
def doctor(client):
    return login(client, FE, "doctor@gepa.local", "doctor123")


def test_frontend_is_served(client):
    r = client.get(FE)
    assert r.status_code == 200
    assert "ГепаНавигатор" in r.text and 'id="root"' in r.text


def test_seeded_worklist_through_frontend_origin(client, doctor):
    r = client.get(f"{FE}/api/worklist", headers=doctor)
    assert r.status_code == 200
    summary = r.json()["summary"]
    assert summary["red"] >= 1 and summary["purple"] == 1


def test_full_clinical_pathway(client, doctor):
    # 1. ГИС ЭЗ РТ публикует событие «диагноз B18.2» -> автоматическая постановка на учёт
    payload = {
        "event_type": "Condition", "code": "B18.2",
        "patient": {"full_name": "E2E Сценариев Клинический Путь", "birth_date": "1985-03-04",
                    "sex": "M", "snils": "700-000-000 01", "phone": "+79170007001",
                    "diagnosis_code": "B18.2", "nosology": "HCV", "fibrosis_stage": "F2"},
    }
    r = client.post(f"{BE}/api/integrations/gis/events", json=payload,
                    headers={"X-Integration-Key": "gis-demo-key"})
    assert r.status_code == 201 and r.json()["enrolled"] is True
    pid = r.json()["patient_id"]

    # 2. Пациент виден на рабочем месте врача, план по КР сгенерирован, welcome-уведомление в очереди
    detail = client.get(f"{FE}/api/patients/{pid}", headers=doctor).json()
    assert {i["kind"] for i in detail["plan"]} >= {"VISIT", "LABS", "PCR", "ULTRASOUND"}
    notes = client.get(f"{FE}/api/notifications?patient_id={pid}", headers=doctor).json()
    assert any(n["kind"] == "WELCOME" and n["status"] == "QUEUED" for n in notes)

    # 3. Приём: визит закрывается, черновик заключения AI-ассистента, следующий визит +6 мес
    r = client.post(f"{FE}/api/patients/{pid}/encounters",
                    json={"complaints": "Жалоб нет.", "conclusion": "Начать ПВТ."}, headers=doctor)
    assert r.status_code == 201 and "Черновик заключения" in r.json()["draft_conclusion"]
    detail = client.get(f"{FE}/api/patients/{pid}", headers=doctor).json()
    assert any(i["kind"] == "VISIT" and i["status"] == "PLANNED" for i in detail["plan"])

    # 4. Окончание ПВТ -> критический контроль УВО-12 ровно через 12 недель
    end = date.today() - timedelta(days=3)
    r = client.post(f"{FE}/api/patients/{pid}/therapy",
                    json={"regimen": "Софосбувир/Велпатасвир 12 нед", "therapy_start": "2026-01-05",
                          "therapy_end": end.isoformat()}, headers=doctor)
    assert r.status_code == 200 and r.json()["status"] == "POST_THERAPY"
    svr = next(i for i in r.json()["plan"] if i["kind"] == "SVR12")
    assert svr["due_date"] == (end + timedelta(weeks=12)).isoformat()

    # 5. ПЦР на УВО-12 отрицательный -> УВО достигнут, аналитика это видит
    r = client.post(f"{FE}/api/plan-items/{svr['id']}/complete",
                    json={"result": "РНК ВГС не обнаружена"}, headers=doctor)
    assert r.status_code == 200
    detail = client.get(f"{FE}/api/patients/{pid}", headers=doctor).json()
    assert detail["svr12_achieved"] is True
    analytics = client.get(f"{FE}/api/analytics/overview", headers=doctor).json()
    assert analytics["svr12_achieved"] >= 1 and analytics["svr_rate"] is not None


def test_care_escalation_and_call_log(client, doctor):
    head = login(client, FE, "head@gepa.local", "head12345")
    nurse = login(client, FE, "nurse@gepa.local", "nurse1234")
    # 6. Дневной job: просрочки -> напоминания -> задачи обзвона красной зоны
    r = client.post(f"{FE}/api/jobs/run-daily", headers=head)
    assert r.status_code == 200
    tasks = client.get(f"{FE}/api/care/tasks", headers=nurse).json()
    assert len(tasks) >= 1
    # 7. Медсестра фиксирует исход обзвона в журнале
    r = client.post(f"{FE}/api/care/tasks/{tasks[0]['id']}/complete",
                    json={"outcome": "WILL_COME", "comment": "Явка подтверждена"}, headers=nurse)
    assert r.status_code == 200 and r.json()["outcome"] == "WILL_COME"
    # 8. Аудит: заведующий видит журнал, врач — нет (RBAC блока 8)
    assert client.get(f"{FE}/api/audit", headers=head).status_code == 200
    assert client.get(f"{FE}/api/audit", headers=doctor).status_code == 403
