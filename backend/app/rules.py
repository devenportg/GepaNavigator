"""Клинический слой: мотор правил КР и приказа №168н (блок 2 ТЗ).

Чистые функции без зависимости от БД — покрыты unit-тестами.
Периодичность (docs/01, docs/03):
  - приём инфекциониста: 1 раз в 6 мес
  - лабораторные анализы (ОАК, БАК, ПЦР, АЛТ/АСТ): 2 раза в год
  - УЗИ + эластометрия: 1 раз в год
  - цирроз: скрининг ГЦР (УЗИ + АФП) каждые 6 мес
  - УВО-12: ПЦР РНК ВГС через 12 недель после окончания ПВТ; УВО-24 при необходимости
Окно допустимости визита: ±14 дней.
"""
import re
from dataclasses import dataclass
from datetime import date, timedelta

VISIT_INTERVAL_DAYS = 180
LABS_INTERVAL_DAYS = 180
IMAGING_INTERVAL_DAYS = 365
HCC_INTERVAL_DAYS = 180
SVR12_WEEKS = 12
DEFAULT_WINDOW = 14


@dataclass
class PlanSpec:
    kind: str
    title: str
    due_date: date
    window_days: int
    rule_ref: str


def build_initial_plan(nosology: str, cirrhosis: bool, anchor: date) -> list[PlanSpec]:
    """Стартовый план при постановке на диспансерный учёт."""
    plan = [
        PlanSpec("VISIT", "Первичный приём врача-инфекциониста", anchor + timedelta(days=7),
                 DEFAULT_WINDOW, "КР: постановка на ДН, первичный осмотр после выявления B18.*"),
        PlanSpec("LABS", "ОАК, БАК (АЛТ, АСТ, билирубин)", anchor + timedelta(days=14),
                 DEFAULT_WINDOW, "КР: лабораторный контроль 2 раза в год"),
        PlanSpec("PCR", "ПЦР (качественный/количественный)", anchor + timedelta(days=14),
                 DEFAULT_WINDOW, "КР: вирусологический контроль при постановке на учёт"),
        PlanSpec("ULTRASOUND", "УЗИ брюшной полости", anchor + timedelta(days=90),
                 30, "КР: инструментальный контроль 1 раз в год"),
        PlanSpec("ELASTOMETRY", "Эластометрия печени (FibroScan)", anchor + timedelta(days=90),
                 30, "КР: оценка стадии фиброза 1 раз в год"),
    ]
    if cirrhosis:
        plan += [
            PlanSpec("HCC_SCREENING", "Скрининг ГЦР: УЗИ", anchor + timedelta(days=30),
                     DEFAULT_WINDOW, "КР: при циррозе — скрининг ГЦР каждые 6 мес"),
            PlanSpec("AFP", "Альфа-фетопротеин (АФП)", anchor + timedelta(days=30),
                     DEFAULT_WINDOW, "КР: при циррозе — АФП в рамках скрининга ГЦР каждые 6 мес"),
        ]
    return plan


def plan_after_visit(anchor: date, cirrhosis: bool) -> list[PlanSpec]:
    """План следующего цикла после завершённого приёма."""
    plan = [
        PlanSpec("VISIT", "Плановый приём врача-инфекциониста", anchor + timedelta(days=VISIT_INTERVAL_DAYS),
                 DEFAULT_WINDOW, "КР: приём инфекциониста 1 раз в 6 месяцев"),
        PlanSpec("LABS", "ОАК, БАК (АЛТ, АСТ, билирубин)", anchor + timedelta(days=LABS_INTERVAL_DAYS),
                 DEFAULT_WINDOW, "КР: лабораторный контроль 2 раза в год"),
        PlanSpec("ULTRASOUND", "УЗИ брюшной полости", anchor + timedelta(days=IMAGING_INTERVAL_DAYS),
                 30, "КР: УЗИ 1 раз в год"),
        PlanSpec("ELASTOMETRY", "Эластометрия печени", anchor + timedelta(days=IMAGING_INTERVAL_DAYS),
                 30, "КР: оценка фиброза 1 раз в год"),
    ]
    if cirrhosis:
        plan.append(PlanSpec("HCC_SCREENING", "Скрининг ГЦР: УЗИ + АФП",
                             anchor + timedelta(days=HCC_INTERVAL_DAYS),
                             DEFAULT_WINDOW, "КР: при циррозе — скрининг ГЦР каждые 6 мес"))
    return plan


def plan_after_therapy_end(therapy_end: date) -> list[PlanSpec]:
    """Контроль УВО после окончания ПВТ — критический триггер КР."""
    return [
        PlanSpec("SVR12", "Контроль УВО-12: ПЦР РНК через 12 недель после ПВТ",
                 therapy_end + timedelta(weeks=SVR12_WEEKS), DEFAULT_WINDOW,
                 "КР: УВО-12 — ключевой критерий излечения ХГС"),
        PlanSpec("SVR24", "Контроль УВО-24: ПЦР РНК через 24 недели после ПВТ",
                 therapy_end + timedelta(weeks=24), 30,
                 "КР: УВО-24 по показаниям после УВО-12"),
    ]


def svr_result_achieved(result: str | None) -> bool | None:
    """Conservative parser for explicit demo result text.

    Returns True for clearly undetectable/negative results, False for clearly
    detectable/positive results, and None for missing or ambiguous text. It is
    intentionally not a clinical interpretation engine.
    """
    if not result or not result.strip():
        return None
    text = " ".join(result.casefold().replace("ё", "е").split())

    # Evaluate both directions: contradictory free text is ambiguous and must
    # not be silently converted into either a successful or failed outcome.
    explicit_failure = any(re.search(pattern, text) for pattern in (
        r"\bуво\s+не\s+(?:достигнут|достигнуто|получен|подтвержден)\b",
        r"\bне\s+(?:достигнут|достигнуто|получен|подтвержден)\s+уво\b",
        r"\bне\s+отрицательн",
        r"\bпцр\s*\+",
    ))
    positive_word = re.search(r"\bположительн", text)
    if positive_word and not re.search(r"\bне\s+положительн", text):
        explicit_failure = True

    achieved_svr = any(re.search(pattern, text) for pattern in (
        r"\bуво\s+достигнут",
        r"\bне\s+(?:был\s+)?обнаружен(?:а|о|ы)?\b",
        r"\bне\s+(?:был\s+)?выявлен(?:а|о|ы)?\b",
        r"\bне\s+определяется\b",
        r"\bотрицательн",
        r"\b(?:рнк|вирусная\s+нагрузка)\s+отсутствует\b",
        r"\bnot\s+detected\b",
        r"\bundetectable\b",
    ))

    # Positive qualitative result. Skip detections explicitly negated by "не".
    detection_words = re.finditer(
        r"\b(?:обнаружен|обнаружена|обнаружено|обнаружены|выявлен|выявлена|выявлено|выявлены|detected)\b",
        text,
    )
    detected = False
    for match in detection_words:
        prefix = text[max(0, match.start() - 20):match.start()]
        if not re.search(r"\b(?:не|not)\s+(?:был\s+)?$", prefix):
            detected = True
            break

    failed_svr = explicit_failure or detected
    if failed_svr and achieved_svr:
        return None
    if failed_svr:
        return False
    if achieved_svr:
        return True
    return None


def effective_status(status: str, due: date, window_days: int, today: date) -> str:
    """Пересчёт просрочки: PLANNED -> OVERDUE по истечении окна допустимости."""
    if status in ("DONE", "CANCELLED", "OVERDUE"):
        return status
    return "OVERDUE" if today > due + timedelta(days=window_days) else "PLANNED"


def patient_zone(items: list[dict], today: date) -> str:
    """Цветовая зона рабочего места врача (блок 3 ТЗ).

    purple — через 4–6 недель контроль УВО; red — есть просрочки;
    yellow — есть запланированные события; green — всё выполнено.
    Приоритет: purple > red > yellow > green (УВО — критический контроль излечения).
    """
    active = [i for i in items if i["status"] in ("PLANNED", "OVERDUE")]
    for i in active:
        if i["kind"] in ("SVR12", "SVR24"):
            days = (i["due_date"] - today).days
            if 28 <= days <= 42 or i["status"] == "OVERDUE":
                return "purple"
    if any(i["status"] == "OVERDUE" for i in active):
        return "red"
    if active:
        return "yellow"
    return "green"


def reminder_kind_for(item_kind: str, days_before: int) -> str | None:
    """Какое напоминание пациенту положено за N дней до события (блок 5 ТЗ)."""
    if item_kind == "SVR12":
        return "SVR12_REMINDER" if days_before in (7, 1) else None
    if item_kind in ("LABS", "PCR", "AFP"):
        return "LABS_REMINDER" if days_before == 10 else None
    if item_kind == "VISIT":
        return "VISIT_REMINDER" if days_before in (7, 1) else None
    return None


def draft_conclusion(patient_name: str, nosology: str, diagnosis_code: str,
                     complaints: str | None, next_step: str) -> str:
    """Демонстрационный макет заключения; YandexGPT здесь не вызывается."""
    complaints_part = complaints.strip() if complaints and complaints.strip() else "Не указаны."
    return (
        "Черновик заключения — демонстрационный шаблон, требует проверки врача\n\n"
        f"Пациент: {patient_name}\n"
        f"Диагноз: {diagnosis_code} ({nosology})\n\n"
        "Жалобы и данные осмотра\n"
        f"{complaints_part}\n\n"
        "План наблюдения и рекомендации\n"
        f"{next_step}\n\n"
        "Перед сохранением проверьте и при необходимости отредактируйте текст. "
        "YandexGPT не подключён; текст сформирован локальным шаблоном."
    )
