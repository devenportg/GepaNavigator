import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PatientRow, ZoneBadge } from "./components";
import type { Patient } from "./types";

const patient: Patient = {
  id: 1, full_name: "Иванов Иван Иванович", birth_date: "1980-01-01", sex: "M",
  snils: "112-233-445 01", phone: null, consent_notifications: true, preferred_channel: "sms",
  diagnosis_code: "B18.2", nosology: "HCV", fibrosis_stage: "F2", cirrhosis: false,
  genotype: null, viral_load: null, status: "ACTIVE", enrollment_trigger: "gis_event",
  enrolled_at: "2026-01-01", therapy_regimen: null, therapy_start: null, therapy_end: null,
  svr12_achieved: null, zone: "red", next_due: "2026-06-01", overdue_count: 2, plan: [],
};

describe("ZoneBadge", () => {
  it("показывает красную зону при просрочке", () => {
    render(<ZoneBadge zone="red" />);
    expect(screen.getByText("Просрочено")).toBeInTheDocument();
  });
  it("показывает фиолетовую зону контроля УВО", () => {
    render(<ZoneBadge zone="purple" />);
    expect(screen.getByText("Контроль УВО")).toBeInTheDocument();
  });
});

describe("PatientRow", () => {
  it("рендерит пациента и открывается по клику", () => {
    const onOpen = vi.fn();
    render(<table><tbody><PatientRow patient={patient} onOpen={onOpen} /></tbody></table>);
    expect(screen.getByText("Иванов Иван Иванович")).toBeInTheDocument();
    expect(screen.getByText(/просрочено: 2/)).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("patient-row"));
    expect(onOpen).toHaveBeenCalledWith(patient);
  });
});
