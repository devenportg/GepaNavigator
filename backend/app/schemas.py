import re
import unicodedata
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Channel = Literal["sms", "push", "gosuslugi"]
Nosology = Literal["HCV", "HBV", "HDV", "MIXED"]
FibrosisStage = Literal["F0", "F1", "F2", "F3", "F4"]
PatientStatus = Literal["ACTIVE", "ON_THERAPY", "POST_THERAPY", "DISCHARGED", "DECEASED"]
CareOutcome = Literal["WILL_COME", "REFUSED", "NO_ANSWER", "UNREACHABLE"]


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    org: str


class TokenOut(BaseModel):
    access_token: str
    user: UserOut


class PatientIn(BaseModel):
    full_name: str = Field(min_length=3, max_length=160)
    birth_date: date
    sex: Literal["M", "F"] = "M"
    snils: str | None = Field(default=None, max_length=20)
    oms: str | None = Field(default=None, max_length=20)
    phone: str | None = Field(default=None, max_length=30)
    # Opt-in: не предполагаем согласие, если его явно не передали.
    consent_notifications: bool = False
    preferred_channel: Channel = "sms"
    diagnosis_code: str = Field(default="B18.2", min_length=3, max_length=10)
    nosology: Nosology = "HCV"
    fibrosis_stage: FibrosisStage = "F1"
    cirrhosis: bool = False
    genotype: str | None = Field(default=None, max_length=20)
    viral_load: str | None = Field(default=None, max_length=50)
    enrollment_trigger: str = Field(default="manual", max_length=60)

    @field_validator("full_name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = " ".join(unicodedata.normalize("NFKC", value).split())
        if not value:
            raise ValueError("Укажите ФИО пациента")
        return value

    @field_validator("snils", mode="before")
    @classmethod
    def normalize_snils(cls, value: str | None) -> str | None:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        digits = re.sub(r"\D", "", str(value))
        if len(digits) != 11:
            raise ValueError("СНИЛС должен содержать 11 цифр")
        return digits

    @field_validator("oms", mode="before")
    @classmethod
    def clean_oms(cls, value: str | None) -> str | None:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        digits = re.sub(r"\D", "", str(value))
        if len(digits) != 16:
            raise ValueError("Номер полиса ОМС должен содержать 16 цифр")
        return digits

    @field_validator("phone", "genotype", "viral_load", "enrollment_trigger", mode="before")
    @classmethod
    def strip_optional_text(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("diagnosis_code")
    @classmethod
    def normalize_diagnosis_code(cls, value: str) -> str:
        value = value.strip().upper()
        if not re.fullmatch(r"B18(?:\.[01289])?", value):
            raise ValueError("Для регистра хронических гепатитов ожидается корректный код МКБ-10 группы B18.*")
        return value

    @field_validator("birth_date")
    @classmethod
    def birth_date_is_not_in_future(cls, value: date) -> date:
        if value > date.today():
            raise ValueError("Дата рождения не может быть в будущем")
        return value


class PatientPatch(BaseModel):
    fibrosis_stage: FibrosisStage | None = None
    cirrhosis: bool | None = None
    genotype: str | None = Field(default=None, max_length=20)
    viral_load: str | None = Field(default=None, max_length=50)
    phone: str | None = Field(default=None, max_length=30)
    consent_notifications: bool | None = None
    preferred_channel: Channel | None = None
    status: PatientStatus | None = None
    discharge_reason: str | None = Field(default=None, max_length=200)

    @field_validator("discharge_reason")
    @classmethod
    def discharge_reason_is_not_blank(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.strip()
            if not value:
                raise ValueError("Укажите причину снятия с наблюдения")
        return value


class PlanItemUpdateIn(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    due_date: date
    window_days: int = Field(ge=0, le=90)
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("title", "reason")
    @classmethod
    def trim_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Заполните обязательное поле")
        return value

    @field_validator("due_date")
    @classmethod
    def plan_date_is_in_the_future(cls, value: date) -> date:
        if value <= date.today():
            raise ValueError("Для редактирования укажите дату позже сегодняшней")
        return value


class PlanCompleteIn(BaseModel):
    result: str | None = Field(default=None, max_length=5000)
    completed_at: date | None = None

    @field_validator("completed_at")
    @classmethod
    def completion_date_is_not_in_future(cls, value: date | None) -> date | None:
        if value is not None and value > date.today():
            raise ValueError("Нельзя отметить событие выполненным будущей датой")
        return value


class EncounterDraftIn(BaseModel):
    complaints: str | None = Field(default=None, max_length=10000)
    instructions: str | None = Field(default=None, max_length=2000)

    @field_validator("complaints", "instructions")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class EncounterIn(BaseModel):
    complaints: str | None = Field(default=None, max_length=10000)
    conclusion: str | None = Field(default=None, max_length=12000)
    draft_conclusion: str | None = Field(default=None, max_length=12000)
    complete_visit_item: bool = True

    @field_validator("complaints", "conclusion", "draft_conclusion")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class TherapyIn(BaseModel):
    regimen: str = Field(min_length=1, max_length=200)
    therapy_start: date
    therapy_end: date | None = None

    @field_validator("regimen")
    @classmethod
    def regimen_is_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Укажите схему терапии")
        return value

    @model_validator(mode="after")
    def validate_therapy_dates(self):
        if self.therapy_start > date.today():
            raise ValueError("Дата начала терапии не может быть в будущем")
        if self.therapy_end is not None:
            if self.therapy_end > date.today():
                raise ValueError("Нельзя отметить терапию завершённой будущей датой")
            if self.therapy_end < self.therapy_start:
                raise ValueError("Дата окончания терапии раньше даты начала")
        return self


class CareCompleteIn(BaseModel):
    outcome: CareOutcome
    comment: str | None = Field(default=None, max_length=2000)


class ConsentIn(BaseModel):
    consent_notifications: bool
    preferred_channel: Channel = "sms"


class GisEventIn(BaseModel):
    """Событие из ГИС ЭЗ РТ / ФРВГ (нормализованный FHIR-подобный payload, блок 6)."""
    event_type: Literal["Condition", "Observation", "RegistryRecord"]
    patient: PatientIn
    code: str | None = Field(default=None, max_length=40)  # B18.* или PCR_POSITIVE / HBSAG_POSITIVE

    @field_validator("code")
    @classmethod
    def normalize_event_code(cls, value: str | None) -> str | None:
        return value.strip().upper() if value else value
