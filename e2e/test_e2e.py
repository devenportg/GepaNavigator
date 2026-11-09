"""E2E-проверка клинического сценария через HTTP-стек backend + frontend preview.

Сценарий покрывает автоматическую постановку из тестового webhook, план, приём,
терапию/УВО-12, дневную эскалацию, обзвон, аналитику и RBAC. Порты выделяются
динамически, чтобы тест не конфликтовал с локальным сервером или live preview.
"""
import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Stack:
    backend: str
    frontend: str


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_ok(url: str, proc: subprocess.Popen, timeout: int = 60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"Процесс сервера завершился до готовности: {url}")
        try:
            if httpx.get(url, timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    raise RuntimeError(f"Сервис не поднялся за {timeout} секунд: {url}")


def stop_process(proc: subprocess.Popen | None):
    if proc is None or proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=10)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


@pytest.fixture(scope="session", autouse=True)
def stack(tmp_path_factory) -> Stack:
    db = tmp_path_factory.mktemp("gepa-e2e") / "e2e.db"
    be_port, fe_port = free_port(), free_port()
    be_url, fe_url = f"http://127.0.0.1:{be_port}", f"http://127.0.0.1:{fe_port}"
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{db.as_posix()}",
        "JWT_SECRET": "gepanavigator-e2e-secret-at-least-32-bytes",
        "INTEGRATION_KEY": "gepanavigator-e2e-integration-key-2026",
        "SEED_DEMO": "true",
        "YANDEXGPT_ENABLED": "false",
    }
    backend = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(be_port)],
        cwd=ROOT / "backend", env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    frontend = None
    try:
        wait_ok(f"{be_url}/health", backend)
        if not (ROOT / "frontend" / "dist" / "index.html").exists():
            subprocess.run(["npm", "run", "build"], cwd=ROOT / "frontend", check=True,
                           stdout=subprocess.DEVNULL)
        fe_env = {**os.environ, "GEPA_API_PROXY_TARGET": be_url}
        frontend = subprocess.Popen(
            ["node", "node_modules/vite/bin/vite.js", "preview", "--host", "127.0.0.1",
             "--port", str(fe_port), "--strictPort"],
            cwd=ROOT / "frontend", env=fe_env, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True,
        )
        wait_ok(fe_url, frontend)
        yield Stack(backend=be_url, frontend=fe_url)
    finally:
        stop_process(frontend)
        stop_process(backend)


def login(client: httpx.Client, base: str, email: str, password: str):
    r = client.post(f"{base}/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def client(stack: Stack):
    with httpx.Client(timeout=10) as c:
        yield c


@pytest.fixture(scope="session")
def doctor(client: httpx.Client, stack: Stack):
    return login(client, stack.frontend, "doctor@gepa.local", "doctor123")


def test_frontend_is_served(stack: Stack, client: httpx.Client):
    r = client.get(stack.frontend)
    assert r.status_code == 200
    assert "ГепаНавигатор" in r.text and 'id="root"' in r.text


def test_worklist_proxy_and_role_scope(stack: Stack, client: httpx.Client, doctor):
    r = client.get(f"{stack.frontend}/api/worklist", headers=doctor)
    assert r.status_code == 200
    summary = r.json()["summary"]
    assert summary["red"] >= 1 and summary["purple"] == 1
    analyst = login(client, stack.frontend, "analyst@gepa.local", "analyst123")
    assert client.get(f"{stack.frontend}/api/worklist", headers=analyst).status_code == 403
    assert client.get(f"{stack.frontend}/api/analytics/overview", headers=analyst).status_code == 200


def test_full_clinical_pathway(stack: Stack, client: httpx.Client, doctor):
    # 1. Тестовое событие ГИС: хронический гепатит -> автоматическая постановка на учёт.
    payload = {
        "event_type": "Condition", "code": "B18.2",
        "patient": {"full_name": "E2E Сценариев Клинический Путь", "birth_date": "1985-03-04",
                    "sex": "M", "snils": "700-000-000 01", "phone": "+79170007001",
                    "diagnosis_code": "B18.2", "nosology": "HCV", "fibrosis_stage": "F2",
                    "consent_notifications": True},
    }
    r = client.post(f"{stack.backend}/api/integrations/gis/events", json=payload,
                    headers={"X-Integration-Key": "gepanavigator-e2e-integration-key-2026"})
    assert r.status_code == 201 and r.json()["enrolled"] is True
    patient_id = r.json()["patient_id"]

    # 2. Пациент виден врачу; для плана создано приветственное уведомление с учётом согласия.
    detail = client.get(f"{stack.frontend}/api/patients/{patient_id}", headers=doctor).json()
    assert {i["kind"] for i in detail["plan"]} >= {"VISIT", "LABS", "PCR", "ULTRASOUND"}
    notes = client.get(f"{stack.frontend}/api/notifications?patient_id={patient_id}", headers=doctor).json()
    assert any(n["kind"] == "WELCOME" and n["status"] == "QUEUED" for n in notes)

    # 3. Приём закрывает плановый визит и создаёт следующий цикл наблюдения.
    draft_response = client.post(f"{stack.frontend}/api/patients/{patient_id}/encounters/draft",
                                 json={"complaints": "Жалоб нет.", "instructions": "Краткий официальный стиль"},
                                 headers=doctor)
    assert draft_response.status_code == 200
    generated_draft = draft_response.json()["draft_conclusion"]
    r = client.post(f"{stack.frontend}/api/patients/{patient_id}/encounters",
                    json={"complaints": "Жалоб нет.", "conclusion": "Начать ПВТ.",
                          "draft_conclusion": generated_draft}, headers=doctor)
    assert r.status_code == 201 and "Черновик заключения" in r.json()["draft_conclusion"]
    detail = client.get(f"{stack.frontend}/api/patients/{patient_id}", headers=doctor).json()
    assert any(i["kind"] == "VISIT" and i["status"] == "PLANNED" for i in detail["plan"])

    # 4. Окончание ПВТ формирует контроль УВО-12 ровно через 12 недель; повтор не дублирует план.
    end = date.today() - timedelta(days=3)
    start = end - timedelta(weeks=12)
    therapy = {"regimen": "Софосбувир/Велпатасвир 12 нед",
               "therapy_start": start.isoformat(), "therapy_end": end.isoformat()}
    r = client.post(f"{stack.frontend}/api/patients/{patient_id}/therapy", json=therapy, headers=doctor)
    assert r.status_code == 200 and r.json()["status"] == "POST_THERAPY"
    detail = r.json()
    svr = next(i for i in detail["plan"] if i["kind"] == "SVR12")
    assert svr["due_date"] == (end + timedelta(weeks=12)).isoformat()
    client.post(f"{stack.frontend}/api/patients/{patient_id}/therapy", json=therapy, headers=doctor).raise_for_status()
    detail = client.get(f"{stack.frontend}/api/patients/{patient_id}", headers=doctor).json()
    assert sum(i["kind"] == "SVR12" and i["status"] != "CANCELLED" for i in detail["plan"]) == 1

    # 5. Результат ПЦР на УВО-12 отражается в карточке и сводной аналитике.
    r = client.post(f"{stack.frontend}/api/plan-items/{svr['id']}/complete",
                    json={"result": "РНК ВГС не обнаружена"}, headers=doctor)
    assert r.status_code == 200
    detail = client.get(f"{stack.frontend}/api/patients/{patient_id}", headers=doctor).json()
    assert detail["svr12_achieved"] is True
    analytics = client.get(f"{stack.frontend}/api/analytics/overview", headers=doctor).json()
    assert analytics["svr12_achieved"] >= 1 and analytics["svr_rate"] is not None


def test_care_escalation_and_call_log(stack: Stack, client: httpx.Client, doctor):
    head = login(client, stack.frontend, "head@gepa.local", "head12345")
    nurse = login(client, stack.frontend, "nurse@gepa.local", "nurse1234")
    r = client.post(f"{stack.frontend}/api/jobs/run-daily", headers=head)
    assert r.status_code == 200
    tasks = client.get(f"{stack.frontend}/api/care/tasks", headers=nurse).json()
    assert tasks
    r = client.post(f"{stack.frontend}/api/care/tasks/{tasks[0]['id']}/complete",
                    json={"outcome": "WILL_COME", "comment": "Явка подтверждена"}, headers=nurse)
    assert r.status_code == 200 and r.json()["outcome"] == "WILL_COME"
    assert client.get(f"{stack.frontend}/api/audit", headers=head).status_code == 200
    assert client.get(f"{stack.frontend}/api/audit", headers=doctor).status_code == 403
