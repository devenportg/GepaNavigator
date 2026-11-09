import type { KeyboardEvent } from "react";
import type { Patient } from "./types";
import { STATUS_LABELS, ZONE_META, age, fmtDate } from "./utils";

export function ZoneBadge({ zone }: { zone: Patient["zone"] }) {
  const meta = ZONE_META[zone];
  return (
    <span className={`zone-badge zone-${zone}`} title={meta.hint}>
      <span className="zone-dot" style={{ background: meta.color }} />
      {meta.label}
    </span>
  );
}

export function StatCard({ title, value, hint, accent }: { title: string; value: string; hint?: string; accent?: string }) {
  return (
    <article className="stat-card" style={accent ? { borderTopColor: accent } : undefined}>
      <div className="stat-title">{title}</div>
      <div className="stat-value">{value}</div>
      {hint && <div className="stat-hint">{hint}</div>}
    </article>
  );
}

export function PatientRow({ patient, onOpen }: { patient: Patient; onOpen: (p: Patient) => void }) {
  function onKeyDown(event: KeyboardEvent<HTMLTableRowElement>) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onOpen(patient);
    }
  }
  return (
    <tr onClick={() => onOpen(patient)} onKeyDown={onKeyDown} tabIndex={0}
      className="patient-row" data-testid="patient-row" aria-label={`Открыть карточку: ${patient.full_name}`}>
      <td>
        <button className="patient-name-button" onClick={(event) => { event.stopPropagation(); onOpen(patient); }}>
          {patient.full_name}
        </button>
        <div className="p-sub">{age(patient.birth_date)} лет · {patient.sex === "F" ? "ж" : "м"}</div>
      </td>
      <td>
        <b>{patient.diagnosis_code}</b>
        <div className="p-sub">{patient.nosology} · {patient.fibrosis_stage}{patient.cirrhosis ? " · цирроз" : ""}</div>
      </td>
      <td><span className={`status-pill status-${patient.status.toLowerCase()}`}>{STATUS_LABELS[patient.status] ?? patient.status}</span></td>
      <td><ZoneBadge zone={patient.zone} /></td>
      <td><span className="date-cell">{fmtDate(patient.next_due)}</span>{patient.overdue_count > 0 && <span className="overdue-count">{patient.overdue_count} просрочено</span>}</td>
    </tr>
  );
}
