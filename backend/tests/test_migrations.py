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
