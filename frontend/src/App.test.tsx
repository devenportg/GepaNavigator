import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { api, getToken, patch, post } from "./api";
import type { Analytics, Patient, User } from "./types";

vi.mock("./api", () => ({
  api: vi.fn(),
  getToken: vi.fn(),
  patch: vi.fn(),
  post: vi.fn(),
  setToken: vi.fn(),
}));

const analyst: User = {
  id: 4,
  email: "analyst@gepa.local",
  full_name: "Аналитик",
  role: "analyst",
  org: "МО тест",
};
const doctor: User = {
  id: 1,
  email: "doctor@gepa.local",
  full_name: "Врач",
  role: "doctor",
  org: "МО тест",
};
let activeUser = analyst;
const futureDueDate = (() => {
  const date = new Date();
  date.setDate(date.getDate() + 30);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
})();
const worklist = {
  summary: { green: 0, yellow: 0, red: 0, purple: 0 },
  patients: [],
};
const focusPatient: Patient = {
  id: 12,
  full_name: "Тестовый Пациент",
  birth_date: "1981-01-02",
  sex: "M",
  snils: null,
  phone: null,
  consent_notifications: false,
  preferred_channel: "sms",
  diagnosis_code: "B18.2",
  nosology: "HCV",
  fibrosis_stage: "F2",
  cirrhosis: false,
  genotype: null,
  viral_load: null,
  status: "ACTIVE",
  enrollment_trigger: "manual",
  enrolled_at: "2026-01-01",
  therapy_regimen: null,
  therapy_start: null,
  therapy_end: null,
  svr12_achieved: null,
  zone: "yellow",
  next_due: futureDueDate,
  overdue_count: 0,
  plan: [{
    id: 56,
    kind: "LABS",
    title: "Контроль анализов",
    due_date: futureDueDate,
    window_days: 14,
    status: "PLANNED",
    rule_ref: "",
    completed_at: null,
    result: null,
  }],
  encounters: [],
};
const analytics: Analytics = {
  registry_total: 8,
  active_total: 8,
  zones: { green: 1, yellow: 4, red: 2, purple: 1 },
  adherence: 0.8,
  plan_done: 4,
  plan_overdue: 1,
  svr12_checked: 2,
  svr12_achieved: 1,
  svr_rate: 0.5,
  by_nosology: { HCV: 8 },
  by_doctor: { "Врач тест": 8 },
};

beforeEach(() => {
  activeUser = analyst;
  vi.mocked(getToken).mockReturnValue("valid-demo-token");
  vi.mocked(api).mockImplementation(((path: string) => {
    if (path === "/api/auth/me") return Promise.resolve(activeUser);
    if (path === "/api/analytics/overview") return Promise.resolve(analytics);
    if (path === "/api/worklist") return Promise.resolve(worklist);
    return Promise.reject(new Error(`Unexpected API request: ${path}`));
  }) as typeof api);
  vi.mocked(patch).mockResolvedValue({} as never);
  vi.mocked(post).mockResolvedValue({} as never);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  activeUser = analyst;
});

describe("role-based navigation", () => {
  it("opens aggregate analytics for an analyst and hides patient-level pages", async () => {
    render(<App />);
    expect(await screen.findByRole("heading", { name: /Аналитика/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Рабочее место" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Задачи обзвона" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Уведомления" })).not.toBeInTheDocument();
    expect(screen.getByText("В регистре")).toBeInTheDocument();
  });

  it("shows a registration form to a doctor and sends consent only after explicit opt-in", async () => {
    activeUser = doctor;
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Добавить пациента" }));

    fireEvent.change(screen.getByLabelText("ФИО *"), { target: { value: "Тестовый Новый Пациент" } });
    fireEvent.change(screen.getByLabelText("Дата рождения *"), { target: { value: "1990-01-01" } });
    fireEvent.change(screen.getByLabelText("Пол *"), { target: { value: "F" } });
    const consent = screen.getByLabelText("Получено согласие пациента");
    expect(consent).not.toBeChecked();
    fireEvent.click(consent);

    fireEvent.click(screen.getByRole("button", { name: "Создать пациента и план" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/api/patients", expect.objectContaining({
      full_name: "Тестовый Новый Пациент",
      sex: "F",
      consent_notifications: true,
      preferred_channel: "sms",
    })));
  });

  it("keeps consent false when a doctor submits the form without opting in", async () => {
    activeUser = doctor;
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Добавить пациента" }));
    fireEvent.change(screen.getByLabelText("ФИО *"), { target: { value: "Пациент Без Согласия" } });
    fireEvent.change(screen.getByLabelText("Дата рождения *"), { target: { value: "1990-01-01" } });
    fireEvent.change(screen.getByLabelText("Пол *"), { target: { value: "M" } });
    expect(screen.getByLabelText("Получено согласие пациента")).not.toBeChecked();

    fireEvent.click(screen.getByRole("button", { name: "Создать пациента и план" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/api/patients", expect.objectContaining({
      full_name: "Пациент Без Согласия",
      consent_notifications: false,
    })));
  });

  it("keeps focus within accessible dialogs and restores it to the opener", async () => {
    activeUser = doctor;
    vi.mocked(api).mockImplementation(((path: string) => {
      if (path === "/api/auth/me") return Promise.resolve(activeUser);
      if (path === "/api/worklist") return Promise.resolve({
        summary: worklist.summary,
        patients: [focusPatient],
      });
      if (path === `/api/patients/${focusPatient.id}`) return Promise.resolve(focusPatient);
      return Promise.reject(new Error(`Unexpected API request: ${path}`));
    }) as typeof api);

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: focusPatient.full_name }));
    const openDialogButton = await screen.findByRole("button", { name: "Отметить" });
    openDialogButton.focus();
    fireEvent.click(openDialogButton);

    const resultDialog = await screen.findByRole("dialog", { name: "Отметить событие выполненным" });
    expect(resultDialog.closest(".modal-layer")?.parentElement).toBe(document.body);
    const resultField = screen.getByRole("textbox", { name: /Результат или комментарий/ });
    await waitFor(() => expect(document.activeElement).toBe(resultField));

    const saveButton = screen.getByRole("button", { name: "Сохранить результат" });
    saveButton.focus();
    fireEvent.keyDown(saveButton, { key: "Tab" });
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Закрыть окно" }));
    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("heading", { name: "Отметить событие выполненным" })).not.toBeInTheDocument());
    expect(document.activeElement).toBe(openDialogButton);
    expect(resultDialog).not.toBeInTheDocument();
  });

  it("allows a doctor to edit a future planned event with an explicit reason", async () => {
    activeUser = doctor;
    vi.mocked(api).mockImplementation(((path: string) => {
      if (path === "/api/auth/me") return Promise.resolve(activeUser);
      if (path === "/api/worklist") return Promise.resolve({ summary: worklist.summary, patients: [focusPatient] });
      if (path === `/api/patients/${focusPatient.id}`) return Promise.resolve(focusPatient);
      return Promise.reject(new Error(`Unexpected API request: ${path}`));
    }) as typeof api);

    const changedDate = new Date();
    changedDate.setDate(changedDate.getDate() + 60);
    const dueDate = `${changedDate.getFullYear()}-${String(changedDate.getMonth() + 1).padStart(2, "0")}-${String(changedDate.getDate()).padStart(2, "0")}`;
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: focusPatient.full_name }));
    fireEvent.click(await screen.findByRole("button", {
      name: `Редактировать событие плана: ${focusPatient.plan[0].title}`,
    }));

    const dialog = await screen.findByRole("dialog", { name: "Редактировать событие плана" });
    fireEvent.change(screen.getByLabelText(/Название события/), { target: { value: "Контрольный анализ крови" } });
    fireEvent.change(screen.getByLabelText(/Новая дата/), { target: { value: dueDate } });
    fireEvent.change(screen.getByLabelText(/Окно выполнения/), { target: { value: "21" } });
    fireEvent.change(screen.getByLabelText(/Причина изменения/), { target: { value: "Срок согласован с пациентом" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить изменения" }));

    await waitFor(() => expect(patch).toHaveBeenCalledWith(`/api/plan-items/${focusPatient.plan[0].id}`, {
      title: "Контрольный анализ крови",
      due_date: dueDate,
      window_days: 21,
      reason: "Срок согласован с пациентом",
    }));
    expect(dialog).not.toBeInTheDocument();
  });

  it("lets a doctor edit a generated conclusion before saving the encounter", async () => {
    activeUser = doctor;
    vi.mocked(api).mockImplementation(((path: string) => {
      if (path === "/api/auth/me") return Promise.resolve(activeUser);
      if (path === "/api/worklist") return Promise.resolve({ summary: worklist.summary, patients: [focusPatient] });
      if (path === `/api/patients/${focusPatient.id}`) return Promise.resolve(focusPatient);
      return Promise.reject(new Error(`Unexpected API request: ${path}`));
    }) as typeof api);
    const generated = "ЧЕРНОВИК\nЖалобы и осмотр\nЖалоб нет.";
    vi.mocked(post)
      .mockResolvedValueOnce({ draft_conclusion: generated, notice: "Демо-шаблон; модель не подключена." } as never)
      .mockResolvedValueOnce({ draft_conclusion: generated, conclusion: "Текст после проверки врача", signed: false } as never);

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: focusPatient.full_name }));
    fireEvent.change(await screen.findByLabelText(/Жалобы и данные осмотра/), { target: { value: "Жалоб нет." } });
    fireEvent.change(await screen.findByLabelText(/Инструкция для оформления/), { target: { value: "Кратко" } });
    fireEvent.click(await screen.findByRole("button", { name: "Сформировать черновик" }));

    const conclusionField = await screen.findByLabelText(/Заключение врача/);
    await waitFor(() => expect(conclusionField).toHaveValue(generated));
    fireEvent.change(conclusionField, { target: { value: "Текст после проверки врача" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить приём" }));

    await waitFor(() => expect(post).toHaveBeenNthCalledWith(2, `/api/patients/${focusPatient.id}/encounters`, {
      complaints: "Жалоб нет.",
      conclusion: "Текст после проверки врача",
      draft_conclusion: generated,
    }));
  });
});
