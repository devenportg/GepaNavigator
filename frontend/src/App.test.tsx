import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { api, getToken, post } from "./api";
import type { Analytics, User } from "./types";

vi.mock("./api", () => ({
  api: vi.fn(),
  getToken: vi.fn(),
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
const worklist = {
  summary: { green: 0, yellow: 0, red: 0, purple: 0 },
  patients: [],
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
    expect(screen.getByText("В регистре / активно")).toBeInTheDocument();
  });

  it("shows a registration form to a doctor and sends consent only after explicit opt-in", async () => {
    activeUser = doctor;
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "+ Пациент в регистр" }));

    fireEvent.change(screen.getByLabelText("ФИО"), { target: { value: "Тестовый Новый Пациент" } });
    fireEvent.change(screen.getByLabelText("Дата рождения"), { target: { value: "1990-01-01" } });
    fireEvent.change(screen.getByLabelText("Пол"), { target: { value: "F" } });
    const consent = screen.getByLabelText("Получено согласие на уведомления");
    expect(consent).not.toBeChecked();
    fireEvent.click(consent);

    fireEvent.click(screen.getByRole("button", { name: "Создать и сгенерировать план по КР" }));
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
    fireEvent.click(await screen.findByRole("button", { name: "+ Пациент в регистр" }));
    fireEvent.change(screen.getByLabelText("ФИО"), { target: { value: "Пациент Без Согласия" } });
    fireEvent.change(screen.getByLabelText("Дата рождения"), { target: { value: "1990-01-01" } });
    fireEvent.change(screen.getByLabelText("Пол"), { target: { value: "M" } });
    expect(screen.getByLabelText("Получено согласие на уведомления")).not.toBeChecked();

    fireEvent.click(screen.getByRole("button", { name: "Создать и сгенерировать план по КР" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/api/patients", expect.objectContaining({
      full_name: "Пациент Без Согласия",
      consent_notifications: false,
    })));
  });
});
