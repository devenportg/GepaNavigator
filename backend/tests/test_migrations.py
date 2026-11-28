from app import main
from sqlalchemy import create_engine, inspect, text


def test_audit_org_migration_backfills_legacy_rows(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE audit_logs (id INTEGER PRIMARY KEY)"))
        connection.execute(text("INSERT INTO audit_logs (id) VALUES (1)"))

    monkeypatch.setattr(main, "engine", engine)
    main.upgrade_audit_org_column()

    assert "org" in {column["name"] for column in inspect(engine).get_columns("audit_logs")}
    with engine.connect() as connection:
        org = connection.execute(text("SELECT org FROM audit_logs WHERE id = 1")).scalar_one()
    assert org == main.DEFAULT_ORG
    engine.dispose()


def test_patient_identifier_migration_drops_legacy_column(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'patient_legacy.db'}")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE patients (id INTEGER PRIMARY KEY, full_name VARCHAR(160), "
            "snils VARCHAR(20))"
        ))
        connection.execute(text("CREATE INDEX ix_patients_snils ON patients (snils)"))
        connection.execute(text("INSERT INTO patients VALUES (1, 'Пациент Тестовый', '12345678901')"))

    monkeypatch.setattr(main, "engine", engine)
    main.upgrade_remove_patient_snils()

    assert "snils" not in {column["name"] for column in inspect(engine).get_columns("patients")}
    with engine.connect() as connection:
        assert connection.execute(text("SELECT full_name FROM patients WHERE id = 1")).scalar_one() == "Пациент Тестовый"
    engine.dispose()
