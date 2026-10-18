import type { Patient } from "./types";
import { STATUS_LABELS, ZONE_META, age, fmtDate } from "./utils";

export function ZoneBadge({ zone }: { zone: Patient["zone"] }) {
  const meta = ZONE_META[zone];
  return (
    <span className="zone-badge" title={meta.hint}>
      <span className="zone-dot" style={{ background: meta.color }} />
      {meta.label}
    </span>
  );
}

export function StatCard({ title, value, hint, accent }: { title: string; value: string; hint?: string; accent?: string }) {
  return (
    <div className="stat-card" style={accent ? { borderTopColor: accent } : undefined}>
      <div className="stat-title">{title}</div>
      <div className="stat-value">{value}</div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  );
}

export function PatientRow({ patient, onOpen }: { patient: Patient; onOpen: (p: Patient) => void }) {
  return (
    <tr onClick={() => onOpen(patient)} className="patient-row" data-testid="patient-row">
      <td>
        <div className="p-name">{patient.full_name}</div>
        <div className="p-sub">{age(patient.birth_date)} лет · {patient.sex === "F" ? "ж" : "м"}</div>
      </td>
      <td>
        {patient.diagnosis_code}
        <div className="p-sub">{patient.nosology} · {patient.fibrosis_stage}{patient.cirrhosis ? " · цирроз" : ""}</div>
      </td>
      <td>{STATUS_LABELS[patient.status] ?? patient.status}</td>
      <td><ZoneBadge zone={patient.zone} /></td>
      <td>{fmtDate(patient.next_due)}{patient.overdue_count > 0 && <span className="overdue"> · просрочено: {patient.overdue_count}</span>}</td>
    </tr>
  );
}
