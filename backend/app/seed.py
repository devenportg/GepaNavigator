from datetime import date, timedelta

from sqlalchemy.orm import Session

from . import rules, services
from .models import Patient, PlanItem, User
from .security import hash_password

DEMO_USERS = [
    ("doctor@gepa.local", "doctor123", "Иванова Анна Сергеевна", "doctor"),
    ("head@gepa.local", "head12345", "Петров Олег Владимирович", "head"),
    ("nurse@gepa.local", "nurse1234", "Сидорова Мария Ильинична", "nurse"),
    ("analyst@gepa.local", "analyst123", "Ким Дмитрий Андреевич", "analyst"),
    ("admin@gepa.local", "admin12345", "Администратор Системы", "admin"),
]


def seed(db: Session):
    if db.query(User).first():
        return
    users = {}
    for email, pwd, name, role in DEMO_USERS:
        u = User(email=email, password_hash=hash_password(pwd), full_name=name, role=role)
        db.add(u)
        users[role] = u
    db.commit()
    doctor = users["doctor"]
    today = date.today()

    # (ФИО, дни до ближайшего контрольного события сдвигаются через due-корректировки ниже)
    specs = [
        # фио, диагноз, нозология, фиброз, цирроз, статус, сдвиг плана (дни от today)
        ("Ахметов Рустем Наилевич", "B18.2", "HCV", "F2", False, "ACTIVE", -40),      # red: просрочка
        ("Гарипова Эльвира Ринатовна", "B18.2", "HCV", "F1", False, "ACTIVE", 20),    # yellow
        ("Смирнов Игорь Павлович", "B18.1", "HBV", "F3", True, "ACTIVE", 10),        # yellow + цирроз
        ("Кузнецова Ольга Викторовна", "B18.2", "HCV", "F0", False, "ACTIVE", -5),   # red (в окне -> недавно просрочен)
        ("Фёдоров Тимур Альбертович", "B18.2", "HCV", "F2", False, "ON_THERAPY", 45),
        ("Васильева Наталья Юрьевна", "B18.2", "HCV", "F1", False, "ACTIVE", 60),    # green-ish/yellow дальний план
        ("Нигматуллин Азат Фаритович", "B18.8", "MIXED", "F4", True, "ACTIVE", -70), # red, цирроз
    ]
    for idx, (name, diag, nos, fib, cirr, status, offset) in enumerate(specs, start=1):
        p = Patient(
            full_name=name, birth_date=date(1975 + idx, (idx % 12) + 1, min(idx * 3, 28)),
            sex="M" if idx % 2 else "F", snils=f"112-233-445 {idx:02d}", oms=f"16000000000000{idx:02d}",
            phone=f"+791700000{idx:02d}", diagnosis_code=diag, nosology=nos, fibrosis_stage=fib,
            cirrhosis=cirr, genotype="1b" if nos == "HCV" else None, status=status,
            enrollment_trigger="gis_event", enrolled_at=today - timedelta(days=90),
            doctor_id=doctor.id,
        )
        db.add(p)
        db.commit()
        anchor = today + timedelta(days=offset) - timedelta(days=7)
        services.add_plan(db, p, rules.build_initial_plan(nos, cirr, anchor))
        db.commit()

    # Пациент на контроле УВО-12 через ~5 недель -> фиолетовая зона
    p = Patient(full_name="Орлова Светлана Дмитриевна", birth_date=date(1988, 4, 12), sex="F",
                snils="112-233-445 95", oms="1600000000000095", phone="+79170000095",
                diagnosis_code="B18.2", nosology="HCV", fibrosis_stage="F1", status="POST_THERAPY",
                enrollment_trigger="frvg", enrolled_at=today - timedelta(days=200), doctor_id=doctor.id,
                therapy_regimen="Софосбувир/Велпатасвир 12 нед", therapy_start=today - timedelta(days=140),
                therapy_end=today - timedelta(days=56))
    db.add(p)
    db.commit()
    svr_due = today + timedelta(days=35)
    db.add(PlanItem(patient_id=p.id, kind="SVR12", title="Контроль УВО-12: ПЦР РНК через 12 недель после ПВТ",
                    due_date=svr_due, window_days=14, status="PLANNED",
                    rule_ref="КР: УВО-12 — ключевой критерий излечения ХГС"))
    db.commit()
    services.refresh_overdue(db, today)
    services.escalate_red_zone(db, today)
