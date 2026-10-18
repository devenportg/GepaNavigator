from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(160))
    # doctor | head | nurse | analyst | admin
    role: Mapped[str] = mapped_column(String(30), default="doctor")
    org: Mapped[str] = mapped_column(String(200), default="ГАУЗ «Поликлиника №1», Казань")


class Patient(Base):
    __tablename__ = "patients"
    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(160), index=True)
    birth_date: Mapped[date] = mapped_column(Date)
    sex: Mapped[str] = mapped_column(String(10), default="M")
    snils: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=True)
    oms: Mapped[str] = mapped_column(String(20), nullable=True)
    phone: Mapped[str] = mapped_column(String(30), nullable=True)
    consent_notifications: Mapped[bool] = mapped_column(Boolean, default=True)
    preferred_channel: Mapped[str] = mapped_column(String(20), default="sms")

    diagnosis_code: Mapped[str] = mapped_column(String(10), default="B18.2")  # МКБ-10 B18.*
    nosology: Mapped[str] = mapped_column(String(20), default="HCV")  # HCV|HBV|HDV|MIXED
    fibrosis_stage: Mapped[str] = mapped_column(String(5), default="F1")
    cirrhosis: Mapped[bool] = mapped_column(Boolean, default=False)
    genotype: Mapped[str] = mapped_column(String(20), nullable=True)
    viral_load: Mapped[str] = mapped_column(String(50), nullable=True)

    # ACTIVE | ON_THERAPY | POST_THERAPY | DISCHARGED | DECEASED
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE", index=True)
    enrollment_trigger: Mapped[str] = mapped_column(String(60), default="manual")
    enrolled_at: Mapped[date] = mapped_column(Date, default=date.today)
    therapy_regimen: Mapped[str] = mapped_column(String(200), nullable=True)
    therapy_start: Mapped[date] = mapped_column(Date, nullable=True)
    therapy_end: Mapped[date] = mapped_column(Date, nullable=True)
    svr12_achieved: Mapped[bool] = mapped_column(Boolean, nullable=True)
    discharge_reason: Mapped[str] = mapped_column(String(200), nullable=True)

    doctor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
    org: Mapped[str] = mapped_column(String(200), default="ГАУЗ «Поликлиника №1», Казань")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    plan_items = relationship("PlanItem", back_populates="patient", cascade="all, delete-orphan")
    encounters = relationship("Encounter", back_populates="patient", cascade="all, delete-orphan")


class PlanItem(Base):
    __tablename__ = "plan_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    # VISIT|LABS|PCR|ULTRASOUND|ELASTOMETRY|SVR12|SVR24|HCC_SCREENING|AFP
    kind: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(240))
    due_date: Mapped[date] = mapped_column(Date, index=True)
    window_days: Mapped[int] = mapped_column(Integer, default=14)
    # PLANNED|DONE|OVERDUE|CANCELLED
    status: Mapped[str] = mapped_column(String(20), default="PLANNED", index=True)
    rule_ref: Mapped[str] = mapped_column(String(300), default="")  # объяснение «назначено по КР…»
    completed_at: Mapped[date] = mapped_column(Date, nullable=True)
    result: Mapped[str] = mapped_column(Text, nullable=True)
    patient = relationship("Patient", back_populates="plan_items")


class Encounter(Base):
    __tablename__ = "encounters"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
    visit_date: Mapped[date] = mapped_column(Date, default=date.today)
    complaints: Mapped[str] = mapped_column(Text, nullable=True)
    conclusion: Mapped[str] = mapped_column(Text, nullable=True)
    draft_conclusion: Mapped[str] = mapped_column(Text, nullable=True)  # черновик «GPT» (mock-фасад)
    signed: Mapped[bool] = mapped_column(Boolean, default=False)
    patient = relationship("Patient", back_populates="encounters")


class CareTask(Base):
    __tablename__ = "care_tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30), default="CALL")  # CALL|ESCALATION|INVITE
    title: Mapped[str] = mapped_column(String(240))
    priority: Mapped[str] = mapped_column(String(10), default="normal")  # low|normal|high
    status: Mapped[str] = mapped_column(String(20), default="OPEN", index=True)
    due_date: Mapped[date] = mapped_column(Date, default=date.today)
    outcome: Mapped[str] = mapped_column(String(40), nullable=True)  # WILL_COME|REFUSED|NO_ANSWER|UNREACHABLE
    comment: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    channel: Mapped[str] = mapped_column(String(20), default="sms")
    kind: Mapped[str] = mapped_column(String(40))  # WELCOME|VISIT_REMINDER|LABS_REMINDER|SVR12_REMINDER|RESULT_READY
    text: Mapped[str] = mapped_column(Text)
    # QUEUED|SENT|SKIPPED_NO_CONSENT
    status: Mapped[str] = mapped_column(String(25), default="QUEUED")
    scheduled_for: Mapped[date] = mapped_column(Date, default=date.today)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=True)
    actor: Mapped[str] = mapped_column(String(160), default="system")
    action: Mapped[str] = mapped_column(String(80))
    entity: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[int] = mapped_column(Integer, nullable=True)
    details: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
