export type Zone = "green" | "yellow" | "red" | "purple";

export interface User {
  id: number;
  email: string;
  full_name: string;
  role: string;
  org: string;
}

export interface PlanItem {
  id: number;
  kind: string;
  title: string;
  due_date: string;
  window_days: number;
  status: "PLANNED" | "DONE" | "OVERDUE" | "CANCELLED";
  rule_ref: string;
  completed_at: string | null;
  result: string | null;
}

export interface Encounter {
  id: number;
  visit_date: string;
  complaints: string | null;
  conclusion: string | null;
  draft_conclusion: string | null;
  signed: boolean;
}

export interface Patient {
  id: number;
  full_name: string;
  birth_date: string;
  sex: string;
  snils: string | null;
  phone: string | null;
  consent_notifications: boolean;
  preferred_channel: string;
  diagnosis_code: string;
  nosology: string;
  fibrosis_stage: string;
  cirrhosis: boolean;
  genotype: string | null;
  viral_load: string | null;
  status: string;
  enrollment_trigger: string;
  enrolled_at: string;
  therapy_regimen: string | null;
  therapy_start: string | null;
  therapy_end: string | null;
  svr12_achieved: boolean | null;
  zone: Zone;
  next_due: string | null;
  overdue_count: number;
  plan: PlanItem[];
  encounters?: Encounter[];
}

export interface CareTask {
  id: number;
  patient_id: number;
  patient_name: string;
  kind: string;
  title: string;
  priority: string;
  status: string;
  due_date: string;
  outcome: string | null;
}

export interface Analytics {
  registry_total: number;
  active_total: number;
  zones: Record<Zone, number>;
  adherence: number | null;
  plan_done: number;
  plan_overdue: number;
  svr12_checked: number;
  svr12_achieved: number;
  svr_rate: number | null;
  by_nosology: Record<string, number>;
  by_doctor: Record<string, number>;
}
