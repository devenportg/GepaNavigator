import type { Zone } from "./types";

export const ZONE_META: Record<Zone, { label: string; color: string; hint: string }> = {
  green: { label: "Всё выполнено", color: "#1a9e6b", hint: "Все запланированные обследования выполнены" },
  yellow: { label: "Запланировано", color: "#e6a700", hint: "Есть запланированные, но не просроченные события" },
  red: { label: "Просрочено", color: "#d93636", hint: "Есть просроченные события — риск выпадения из наблюдения" },
  purple: { label: "Контроль УВО", color: "#7b4fd0", hint: "Через 4–6 недель контроль УВО-12/24 после ПВТ" },
};

export const STATUS_LABELS: Record<string, string> = {
  ACTIVE: "Активное наблюдение",
  ON_THERAPY: "На терапии (ПВТ)",
  POST_THERAPY: "Посттерапевтический контроль",
  DISCHARGED: "Снят с учёта",
  DECEASED: "Умер",
};

export const ROLE_LABELS: Record<string, string> = {
  doctor: "Врач-инфекционист",
  head: "Заведующий отделением",
  nurse: "Медицинская сестра",
  analyst: "Аналитик",
  admin: "Администратор",
};

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso + (iso.length === 10 ? "T00:00:00" : ""));
  return d.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric" });
}

export function age(birthDate: string, today = new Date()): number {
  const b = new Date(birthDate + "T00:00:00");
  let a = today.getFullYear() - b.getFullYear();
  const m = today.getMonth() - b.getMonth();
  if (m < 0 || (m === 0 && today.getDate() < b.getDate())) a--;
  return a;
}

export function pct(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`;
}
