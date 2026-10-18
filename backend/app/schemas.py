from datetime import date

from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    email: str
    password: str


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
    full_name: str
    birth_date: date
    sex: str = "M"
    snils: str | None = None
    oms: str | None = None
    phone: str | None = None
    consent_notifications: bool = True
    preferred_channel: str = "sms"
    diagnosis_code: str = "B18.2"
    nosology: str = "HCV"
    fibrosis_stage: str = "F1"
    cirrhosis: bool = False
    genotype: str | None = None
    viral_load: str | None = None
    enrollment_trigger: str = "manual"


class PatientPatch(BaseModel):
    fibrosis_stage: str | None = None
    cirrhosis: bool | None = None
    genotype: str | None = None
    viral_load: str | None = None
    phone: str | None = None
    consent_notifications: bool | None = None
    preferred_channel: str | None = None
    status: str | None = None
    discharge_reason: str | None = None


class PlanCompleteIn(BaseModel):
    result: str | None = None
    completed_at: date | None = None


class EncounterIn(BaseModel):
    complaints: str | None = None
    conclusion: str | None = None
    complete_visit_item: bool = True


class TherapyIn(BaseModel):
    regimen: str
    therapy_start: date
    therapy_end: date | None = None


class CareCompleteIn(BaseModel):
    outcome: str = Field(description="WILL_COME|REFUSED|NO_ANSWER|UNREACHABLE")
    comment: str | None = None


class ConsentIn(BaseModel):
    consent_notifications: bool
    preferred_channel: str = "sms"


class GisEventIn(BaseModel):
    """Событие из ГИС ЭЗ РТ / ФРВГ (нормализованный FHIR-подобный payload, блок 6)."""
    event_type: str = Field(description="Condition|Observation|RegistryRecord")
    patient: PatientIn
    code: str | None = None  # B18.* или код маркера PCR_POSITIVE / HBSAG_POSITIVE
