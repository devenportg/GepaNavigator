import { useCallback, useEffect, useId, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { createPortal } from "react-dom";
import { api, getToken, post, setToken } from "./api";
import { PatientRow, StatCard, ZoneBadge } from "./components";
import type { Analytics, CareTask, Patient, PlanItem, User, Zone } from "./types";
import {
  NOTIFICATION_STATUS_LABELS,
  PLAN_STATUS_LABELS,
  ROLE_LABELS,
  STATUS_LABELS,
  ZONE_META,
  fmtDate,
  pct,
} from "./utils";

type View = "worklist" | "tasks" | "analytics" | "audit" | "notifications";
type NewPatientForm = {
  full_name: string;
  birth_date: string;
  sex: "" | "M" | "F";
  snils: string;
  oms: string;
  phone: string;
  consent_notifications: boolean;
  preferred_channel: "sms" | "push" | "gosuslugi";
  diagnosis_code: string;
  nosology: "HCV" | "HBV" | "HDV" | "MIXED";
  fibrosis_stage: "F0" | "F1" | "F2" | "F3" | "F4";
  cirrhosis: boolean;
};
type NotificationItem = {
  id: number;
  patient_id: number;
  channel: string;
  kind: string;
  text: string;
  status: string;
  scheduled_for: string;
};
type AuditItem = {
  id: number;
  actor: string;
  action: string;
  entity: string;
  details: string;
  created_at: string;
};
type TherapyForm = { regimen: string; therapy_start: string; therapy_end: string };
type CareOutcomeCode = "WILL_COME" | "REFUSED" | "NO_ANSWER" | "UNREACHABLE";
type IconName = "brand" | "patients" | "phone" | "chart" | "bell" | "audit" | "refresh" | "logout" | "close" | "calendar" | "check" | "activity" | "plus" | "arrow" | "shield";

const canManagePatients = (role: string) => ["doctor", "head", "nurse", "admin"].includes(role);
const canConductEncounter = (role: string) => ["doctor", "head", "admin"].includes(role);
const canCompletePlanItem = (role: string, kind: string) =>
  ["doctor", "head", "nurse", "admin"].includes(role) &&
  !(role === "nurse" && ["VISIT", "SVR12"].includes(kind));
const canRunDailyJob = (role: string) => ["head", "nurse", "admin"].includes(role);

function localDateInput(value?: Date): string {
  const date = value ?? new Date();
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function initials(name: string): string {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
}

function Icon({ name, className = "" }: { name: IconName; className?: string }) {
  const common = { fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  const content: Record<IconName, ReactNode> = {
    brand: <><path d="M12 2.8S5.7 9.2 5.7 14.7a6.3 6.3 0 0 0 12.6 0C18.3 9.2 12 2.8 12 2.8Z" /><path d="M12 10v9M7.5 14.5h9" /></>,
    patients: <><path d="M16 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="10" cy="7" r="4" /><path d="M20 8v6M23 11h-6" /></>,
    phone: <><path d="M21 15.5v3a2 2 0 0 1-2.2 2 19.7 19.7 0 0 1-8.6-3.1 19.4 19.4 0 0 1-6-6A19.7 19.7 0 0 1 1.1 2.8 2 2 0 0 1 3.1.6h3a2 2 0 0 1 2 1.7c.1.9.4 1.8.7 2.6a2 2 0 0 1-.5 2.1L7 8.3a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.5c.8.3 1.7.6 2.6.7a2 2 0 0 1 2 2.3Z" /></>,
    chart: <><path d="M3 3v18h18" /><path d="m7 14 4-4 4 3 6-7" /></>,
    bell: <><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9" /><path d="M10 21h4" /></>,
    audit: <><path d="M8 4H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-2" /><rect x="8" y="2" width="8" height="4" rx="1" /><path d="M8 11h8M8 15h8" /></>,
    refresh: <><path d="M20 7v5h-5M4 17v-5h5" /><path d="M5.6 9a7 7 0 0 1 11.6-2L20 12M4 12l2.8 5a7 7 0 0 0 11.6-2" /></>,
    logout: <><path d="M10 17l5-5-5-5M15 12H3" /><path d="M12 3h6a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-6" /></>,
    close: <><path d="m18 6-12 12M6 6l12 12" /></>,
    calendar: <><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M16 3v4M8 3v4M3 10h18M8 14h.01M12 14h.01M16 14h.01M8 17h.01M12 17h.01" /></>,
    check: <><path d="m5 12 4 4L19 6" /></>,
    activity: <><path d="M3 12h4l3-8 4 16 3-8h4" /></>,
    plus: <><path d="M12 5v14M5 12h14" /></>,
    arrow: <><path d="M5 12h14M13 6l6 6-6 6" /></>,
    shield: <><path d="M12 22s8-4 8-11V5l-8-3-8 3v6c0 7 8 11 8 11Z" /><path d="m9 12 2 2 4-4" /></>,
  };
  return <svg className={`icon ${className}`} viewBox="0 0 24 24" aria-hidden="true" {...common}>{content[name]}</svg>;
}

function Brand() {
  return (
    <div className="brand" aria-label="ГепаНавигатор">
      <span className="brand-mark"><Icon name="brand" /></span>
      <span className="brand-copy"><strong>ГепаНавигатор</strong><small>маршрут наблюдения</small></span>
    </div>
  );
}

const DIALOG_FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [contenteditable="true"], [tabindex]:not([tabindex="-1"])';

function Modal({ title, description, onClose, children, size = "medium", busy = false }: {
  title: string;
  description?: string;
  onClose: () => void;
  children: ReactNode;
  size?: "medium" | "large";
  busy?: boolean;
}) {
  const titleId = useId();
  const descriptionId = useId();
  const dialogRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  const busyRef = useRef(busy);
  onCloseRef.current = onClose;
  busyRef.current = busy;

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    const previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    const focusableElements = () => Array.from(dialog.querySelectorAll<HTMLElement>(DIALOG_FOCUSABLE_SELECTOR))
      .filter((element) => !element.hasAttribute("hidden") && element.tabIndex >= 0);
    const preferredFocus = dialog.querySelector<HTMLElement>("[data-autofocus]");
    const initialFocus = preferredFocus && !preferredFocus.hasAttribute("disabled")
      ? preferredFocus
      : focusableElements()[0];

    (initialFocus ?? dialog).focus();
    document.body.style.overflow = "hidden";

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (!busyRef.current) {
          event.preventDefault();
          onCloseRef.current();
        }
        return;
      }
      if (event.key !== "Tab") return;

      const focusable = focusableElements();
      if (focusable.length === 0) {
        event.preventDefault();
        dialog.focus();
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!dialog.contains(document.activeElement)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", onKeyDown);
      if (previouslyFocused?.isConnected) previouslyFocused.focus();
    };
  }, []);

  function requestClose() {
    if (!busyRef.current) onCloseRef.current();
  }

  return createPortal(
    <div className="modal-layer" onMouseDown={(event) => { if (event.target === event.currentTarget) requestClose(); }}>
      <section ref={dialogRef} className={`modal-panel modal-${size}`} role="dialog" aria-modal="true"
        aria-labelledby={titleId} aria-describedby={description ? descriptionId : undefined} aria-busy={busy} tabIndex={-1}>
        <header className="modal-header">
          <span className="modal-icon"><Icon name="activity" /></span>
          <div className="modal-heading-copy">
            <p className="eyebrow">ГепаНавигатор · карточка пациента</p>
            <h2 id={titleId}>{title}</h2>
            {description && <p id={descriptionId} className="modal-description">{description}</p>}
          </div>
          <button type="button" className="icon-button modal-close" aria-label="Закрыть окно" onClick={requestClose} disabled={busy}>
            <Icon name="close" />
          </button>
        </header>
        {children}
      </section>
    </div>,
    document.body,
  );
}

function Feedback({ error, message }: { error?: string; message?: string }) {
  if (!error && !message) return null;
  return <div className={`feedback ${error ? "feedback-error" : "feedback-success"}`} role={error ? "alert" : "status"}>
    <span className="feedback-mark"><Icon name={error ? "activity" : "check"} /></span>
    <span>{error || message}</span>
  </div>;
}

function PageHeading({ eyebrow, title, description, actions }: {
  eyebrow: string;
  title: string;
  description: string;
  actions?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div className="page-heading-copy">
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p className="page-description">{description}</p>
      </div>
      {actions && <div className="page-heading-actions">{actions}</div>}
    </div>
  );
}

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [booting, setBooting] = useState(true);

  useEffect(() => {
    let active = true;
    if (!getToken()) {
      setBooting(false);
      return;
    }
    api<User>("/api/auth/me")
      .then((currentUser) => { if (active) setUser(currentUser); })
      .catch(() => setToken(null))
      .finally(() => { if (active) setBooting(false); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    const onExpired = () => {
      setToken(null);
      setUser(null);
    };
    window.addEventListener("gepa:auth-expired", onExpired);
    return () => window.removeEventListener("gepa:auth-expired", onExpired);
  }, []);

  if (booting) return <div className="loading-screen"><div className="loading-mark"><Icon name="brand" /></div><p>Открываем рабочее пространство…</p></div>;
  if (!user) return <Login onLogin={setUser} />;
  return <Shell user={user} onLogout={() => { setToken(null); setUser(null); }} />;
}

function Login({ onLogin }: { onLogin: (u: User) => void }) {
  const [email, setEmail] = useState("doctor@gepa.local");
  const [password, setPassword] = useState("doctor123");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      const data = await post<{ access_token: string; user: User }>("/api/auth/login", { email, password });
      setToken(data.access_token);
      onLogin(data.user);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-page">
      <section className="login-story">
        <Brand />
        <div className="login-story-copy">
          <p className="eyebrow">Диспансерное наблюдение · хронические гепатиты</p>
          <h1>Помогаем пациенту не потеряться на пути лечения.</h1>
          <p>Один маршрут для команды: контрольные события, сроки наблюдения и следующий важный шаг.</p>
          <div className="login-points">
            <div><span><Icon name="calendar" /></span><p><b>План по датам</b><small>Визиты, анализы и контроль терапии</small></p></div>
            <div><span><Icon name="shield" /></span><p><b>Фокус на непрерывности</b><small>Подсветка просрочек и контрольных точек</small></p></div>
          </div>
        </div>
        <p className="login-footnote">Демонстрационный MVP · используйте только синтетические данные</p>
      </section>
      <section className="login-panel-wrap">
        <form className="login-card" onSubmit={submit}>
          <div className="login-card-heading">
            <p className="eyebrow">Добро пожаловать</p>
            <h2>Войти в систему</h2>
            <p>Используйте демонстрационную учётную запись.</p>
          </div>
          <label className="field">
            <span>Электронная почта</span>
            <input autoComplete="username" type="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
          </label>
          <label className="field">
            <span>Пароль</span>
            <input autoComplete="current-password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} required />
          </label>
          <Feedback error={error} />
          <button className="button button-primary button-wide" type="submit" disabled={busy}>
            {busy ? "Выполняется вход…" : "Войти"}<Icon name="arrow" />
          </button>
          <div className="login-demo">
            <span className="demo-dot" />
            <div><b>Демо-вход врача</b><small>doctor@gepa.local <span>·</span> doctor123</small></div>
          </div>
          <details className="other-demo-accounts">
            <summary>Другие демонстрационные роли</summary>
            <p>Заведующий: head@gepa.local / head12345</p>
            <p>Медсестра: nurse@gepa.local / nurse1234</p>
            <p>Аналитик: analyst@gepa.local / analyst123</p>
            <p>Администратор: admin@gepa.local / admin12345</p>
          </details>
          <p className="login-safety">Это учебная среда. Реальные медицинские данные не используйте.</p>
        </form>
      </section>
    </div>
  );
}

function Shell({ user, onLogout }: { user: User; onLogout: () => void }) {
  const [view, setView] = useState<View>(user.role === "analyst" ? "analytics" : "worklist");
  const [selectedPatientId, setSelectedPatientId] = useState<number | null>(null);
  const [jobMsg, setJobMsg] = useState("");
  const [jobError, setJobError] = useState("");
  const [jobBusy, setJobBusy] = useState(false);
  const [refreshToken, setRefreshToken] = useState(0);

  async function runDaily() {
    setJobMsg("");
    setJobError("");
    setJobBusy(true);
    try {
      const result = await post<{ overdue_marked: number; reminders_created: number; care_tasks_created: number }>("/api/jobs/run-daily");
      setJobMsg(`Пересчёт завершён: просрочек — ${result.overdue_marked}, напоминаний — ${result.reminders_created}, новых задач обзвона — ${result.care_tasks_created}.`);
      setRefreshToken((value) => value + 1);
    } catch (err) {
      setJobError((err as Error).message);
    } finally {
      setJobBusy(false);
    }
  }

  const showClinicalViews = user.role !== "analyst";
  const showTasks = ["doctor", "head", "nurse", "admin"].includes(user.role);
  const showNotifications = ["doctor", "head", "nurse", "admin"].includes(user.role);
  const navItems: { id: View; label: string; icon: IconName; visible: boolean }[] = [
    { id: "worklist", label: "Пациенты", icon: "patients", visible: showClinicalViews },
    { id: "tasks", label: "Обзвон", icon: "phone", visible: showTasks },
    { id: "analytics", label: "Аналитика", icon: "chart", visible: true },
    { id: "notifications", label: "Уведомления", icon: "bell", visible: showNotifications },
    { id: "audit", label: "Аудит", icon: "audit", visible: user.role === "head" || user.role === "admin" },
  ];

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="topbar-inner">
          <Brand />
          <nav className="main-nav" aria-label="Основная навигация">
            {navItems.filter((item) => item.visible).map((item) => (
              <button key={item.id} className={`nav-button ${view === item.id ? "is-active" : ""}`}
                aria-current={view === item.id ? "page" : undefined} onClick={() => setView(item.id)}>
                <Icon name={item.icon} /><span>{item.label}</span>
              </button>
            ))}
          </nav>
          <div className="topbar-actions">
            {canRunDailyJob(user.role) && <button className="button button-secondary daily-button" onClick={runDaily} disabled={jobBusy}
              title="Пересчитать просрочки, напоминания и задачи обзвона">
              <Icon name="refresh" />{jobBusy ? "Пересчёт…" : "Дневной пересчёт"}
            </button>}
            <div className="user-menu">
              <span className="user-avatar">{initials(user.full_name)}</span>
              <span className="user-copy"><b>{user.full_name}</b><small>{ROLE_LABELS[user.role] ?? user.role}</small></span>
              <button className="icon-button logout-button" onClick={onLogout} aria-label="Выйти" title="Выйти"><Icon name="logout" /></button>
            </div>
          </div>
        </div>
      </header>
      <main className="app-main">
        {jobMsg && <Feedback message={jobMsg} />}
        {jobError && <Feedback error={jobError} />}
        {view === "worklist" && showClinicalViews && <Worklist
          onOpen={setSelectedPatientId} refreshToken={refreshToken} canCreate={canManagePatients(user.role)} />}
        {view === "tasks" && showTasks && <Tasks onOpenPatient={setSelectedPatientId} refreshToken={refreshToken} />}
        {view === "analytics" && <AnalyticsView refreshToken={refreshToken} />}
        {view === "notifications" && showNotifications && <Notifications refreshToken={refreshToken} />}
        {view === "audit" && (user.role === "head" || user.role === "admin") && <Audit refreshToken={refreshToken} />}
      </main>
      <footer className="app-footer"><span>ГепаНавигатор · демонстрационный MVP</span><span>Не для клинического применения</span></footer>
      {selectedPatientId !== null && <PatientCard patientId={selectedPatientId} user={user} onClose={() => setSelectedPatientId(null)} />}
    </div>
  );
}

function Worklist({ onOpen, refreshToken, canCreate }: {
  onOpen: (id: number) => void;
  refreshToken: number;
  canCreate: boolean;
}) {
  const [patients, setPatients] = useState<Patient[]>([]);
  const [summary, setSummary] = useState<Record<Zone, number> | null>(null);
  const [search, setSearch] = useState("");
  const [zone, setZone] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);

  const load = useCallback(async () => {
    setError("");
    setLoading(true);
    try {
      const data = await api<{ summary: Record<Zone, number>; patients: Patient[] }>("/api/worklist");
      setSummary(data.summary);
      let rows = data.patients;
      if (zone) rows = rows.filter((patient) => patient.zone === zone);
      if (search) rows = rows.filter((patient) => patient.full_name.toLowerCase().includes(search.toLowerCase()));
      setPatients(rows);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [search, zone]);
  useEffect(() => { void load(); }, [load, refreshToken]);

  return (
    <section className="page-section">
      <PageHeading eyebrow="Клиническое наблюдение" title="Пациенты" description="Единый список людей на диспансерном наблюдении и ближайших контрольных событий."
        actions={canCreate ? <button className="button button-primary" onClick={() => setShowForm((open) => !open)}>
          <Icon name="plus" />{showForm ? "Скрыть форму" : "Добавить пациента"}
        </button> : undefined} />
      <div className="notice notice-info worklist-explainer"><Icon name="shield" /><span><b>Статус и зона отвечают на разные вопросы</b><small>Статус показывает этап наблюдения и терапии. Цвет зоны показывает срочность ближайших контрольных событий.</small></span></div>
      {summary && <div className="stats-grid">
        <StatCard title="Всё выполнено" value={String(summary.green)} hint={ZONE_META.green.hint} accent={ZONE_META.green.color} />
        <StatCard title="Запланировано" value={String(summary.yellow)} hint={ZONE_META.yellow.hint} accent={ZONE_META.yellow.color} />
        <StatCard title="Есть просрочки" value={String(summary.red)} hint={ZONE_META.red.hint} accent={ZONE_META.red.color} />
        <StatCard title="Контроль УВО" value={String(summary.purple)} hint={ZONE_META.purple.hint} accent={ZONE_META.purple.color} />
      </div>}
      <div className="toolbar-card">
        <div className="search-control"><span className="search-symbol">⌕</span><input aria-label="Поиск по ФИО" placeholder="Найти пациента по ФИО…" value={search} onChange={(event) => setSearch(event.target.value)} /></div>
        <label className="select-control"><span>Зона</span><select value={zone} onChange={(event) => setZone(event.target.value)} aria-label="Фильтр по зоне">
          <option value="">Все пациенты</option>
          {Object.entries(ZONE_META).map(([key, meta]) => <option key={key} value={key}>{meta.label}</option>)}
        </select></label>
        <span className="toolbar-count">{loading ? "Обновляем…" : `${patients.length} в списке`}</span>
      </div>
      {showForm && canCreate && <NewPatient onCreated={() => { setShowForm(false); void load(); }} onCancel={() => setShowForm(false)} />}
      {error && <Feedback error={error} />}
      <div className="table-card">
        <div className="table-card-heading"><div><h2>Список наблюдения</h2><p>Откройте карточку, чтобы посмотреть план и историю пациента.</p></div></div>
        {loading && patients.length === 0 ? <div className="empty-state"><span className="loading-spinner" />Загружаем список пациентов…</div> : patients.length === 0 ?
          <div className="empty-state"><span className="empty-icon"><Icon name="patients" /></span><b>Пациенты не найдены</b><span>Измените поисковый запрос или фильтр зоны.</span></div> :
          <div className="table-scroll"><table className="data-table">
            <thead><tr><th>Пациент</th><th>Диагноз</th><th>Статус наблюдения</th><th>Сигнал</th><th>Следующее событие</th></tr></thead>
            <tbody>{patients.map((patient) => <PatientRow key={patient.id} patient={patient} onOpen={(selected) => onOpen(selected.id)} />)}</tbody>
          </table></div>}
      </div>
    </section>
  );
}

function NewPatient({ onCreated, onCancel }: { onCreated: () => void; onCancel: () => void }) {
  const [form, setForm] = useState<NewPatientForm>({
    full_name: "", birth_date: "", sex: "", snils: "", oms: "", phone: "",
    consent_notifications: false, preferred_channel: "sms", diagnosis_code: "B18.2",
    nosology: "HCV", fibrosis_stage: "F1", cirrhosis: false,
  });
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const update = <K extends keyof NewPatientForm>(key: K, value: NewPatientForm[K]) =>
    setForm((current) => ({ ...current, [key]: value }));

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSaving(true);
    try {
      await post("/api/patients", form);
      onCreated();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="form-card" onSubmit={submit}>
      <div className="form-card-heading"><span className="section-icon"><Icon name="patients" /></span><div><p className="eyebrow">Новая запись</p><h2>Постановка на наблюдение</h2><p>Заполните минимальные данные — система создаст стартовый план контроля.</p></div></div>
      <div className="form-section"><h3>Данные пациента</h3><div className="form-grid">
        <label className="field"><span>ФИО <i>*</i></span><input value={form.full_name} onChange={(event) => update("full_name", event.target.value)} required minLength={3} maxLength={160} autoComplete="name" /></label>
        <label className="field"><span>Дата рождения <i>*</i></span><input type="date" value={form.birth_date} onChange={(event) => update("birth_date", event.target.value)} required /></label>
        <label className="field"><span>Пол <i>*</i></span><select value={form.sex} onChange={(event) => update("sex", event.target.value as NewPatientForm["sex"])} required>
          <option value="">Выберите</option><option value="F">Женский</option><option value="M">Мужской</option>
        </select></label>
        <label className="field"><span>Телефон</span><input type="tel" value={form.phone} onChange={(event) => update("phone", event.target.value)} autoComplete="tel" /></label>
        <label className="field"><span>СНИЛС</span><input value={form.snils} onChange={(event) => update("snils", event.target.value)} placeholder="11 цифр" inputMode="numeric" /></label>
        <label className="field"><span>Полис ОМС</span><input value={form.oms} onChange={(event) => update("oms", event.target.value)} placeholder="16 цифр" inputMode="numeric" /></label>
      </div></div>
      <div className="form-section"><h3>Клиническая информация</h3><div className="form-grid">
        <label className="field"><span>Код МКБ-10 <i>*</i></span><input value={form.diagnosis_code} onChange={(event) => update("diagnosis_code", event.target.value)} required /></label>
        <label className="field"><span>Нозология</span><select value={form.nosology} onChange={(event) => update("nosology", event.target.value as NewPatientForm["nosology"])}>
          <option value="HCV">Гепатит C</option><option value="HBV">Гепатит B</option><option value="HDV">Гепатит D</option><option value="MIXED">Сочетанная инфекция</option>
        </select></label>
        <label className="field"><span>Стадия фиброза</span><select value={form.fibrosis_stage} onChange={(event) => update("fibrosis_stage", event.target.value as NewPatientForm["fibrosis_stage"])}>
          {["F0", "F1", "F2", "F3", "F4"].map((stage) => <option key={stage} value={stage}>{stage}</option>)}
        </select></label>
        <label className="field check-field"><input type="checkbox" checked={form.cirrhosis} onChange={(event) => update("cirrhosis", event.target.checked)} /><span>У пациента цирроз печени</span></label>
      </div></div>
      <div className="form-section consent-section"><div><h3>Уведомления</h3><p>Уведомления в MVP только записываются в журнал и не отправляются.</p></div>
        <label className="field check-field"><input type="checkbox" checked={form.consent_notifications} onChange={(event) => update("consent_notifications", event.target.checked)} /><span>Получено согласие пациента</span></label>
        <label className="field"><span>Канал</span><select value={form.preferred_channel} disabled={!form.consent_notifications} onChange={(event) => update("preferred_channel", event.target.value as NewPatientForm["preferred_channel"])}>
          <option value="sms">СМС (демо)</option><option value="push">Push (демо)</option><option value="gosuslugi">Госуслуги (демо)</option>
        </select></label>
      </div>
      <Feedback error={error} />
      <div className="form-actions"><button className="button button-quiet" type="button" onClick={onCancel}>Отмена</button>
        <button className="button button-primary" type="submit" disabled={saving}>{saving ? "Создаём запись…" : "Создать пациента и план"}<Icon name="arrow" /></button></div>
      <p className="form-safety"><Icon name="shield" /> Только демонстрационные данные. Не вводите реальные медицинские сведения.</p>
    </form>
  );
}

function PatientCard({ patientId, user, onClose }: { patientId: number; user: User; onClose: () => void }) {
  const [patient, setPatient] = useState<Patient | null>(null);
  const [complaints, setComplaints] = useState("");
  const [conclusion, setConclusion] = useState("");
  const [draft, setDraft] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [modalError, setModalError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [completionItem, setCompletionItem] = useState<PlanItem | null>(null);
  const [completionResult, setCompletionResult] = useState("");
  const [therapyOpen, setTherapyOpen] = useState(false);
  const [therapyForm, setTherapyForm] = useState<TherapyForm>({ regimen: "", therapy_start: localDateInput(), therapy_end: "" });
  const canEncounter = canConductEncounter(user.role);
  const canConsent = canManagePatients(user.role);

  const load = useCallback(async () => {
    setError("");
    setLoading(true);
    try {
      setPatient(await api<Patient>(`/api/patients/${patientId}`));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [patientId]);
  useEffect(() => { void load(); }, [load]);

  function openCompletion(item: PlanItem) {
    setCompletionItem(item);
    setCompletionResult(item.result ?? "");
    setModalError("");
  }

  async function submitCompletion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!completionItem) return;
    if (completionItem.kind === "SVR12" && !completionResult.trim()) {
      setModalError("Для контроля УВО-12 обязательно укажите результат ПЦР.");
      return;
    }
    setBusy(true);
    setModalError("");
    try {
      await post(`/api/plan-items/${completionItem.id}/complete`, { result: completionResult.trim() || null });
      setCompletionItem(null);
      setMessage("Результат сохранён; событие отмечено выполненным.");
      await load();
    } catch (err) {
      setModalError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function encounter() {
    if (!patient) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await post<{ draft_conclusion: string }>(`/api/patients/${patient.id}/encounters`, {
        complaints,
        conclusion: conclusion || null,
      });
      setDraft(result.draft_conclusion);
      setMessage("Запись приёма сохранена. Будущие контрольные события находятся в плане пациента.");
      await load();
    } catch (err) {
      const detail = (err as Error).message;
      if (detail.includes("уже сохранена")) {
        setMessage("Приём за сегодня уже сохранён. Повторная запись не создана.");
        await load();
      } else {
        setError(detail);
      }
    } finally {
      setBusy(false);
    }
  }

  function openTherapy() {
    if (!patient) return;
    setTherapyForm({
      regimen: patient.therapy_regimen ?? "",
      therapy_start: patient.therapy_start ?? localDateInput(),
      therapy_end: patient.therapy_end ?? "",
    });
    setModalError("");
    setTherapyOpen(true);
  }

  async function submitTherapy(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!patient) return;
    if (!therapyForm.regimen.trim()) {
      setModalError("Укажите схему терапии.");
      return;
    }
    if (therapyForm.therapy_end && therapyForm.therapy_end < therapyForm.therapy_start) {
      setModalError("Дата окончания не может быть раньше даты начала.");
      return;
    }
    setBusy(true);
    setModalError("");
    try {
      await post(`/api/patients/${patient.id}/therapy`, {
        regimen: therapyForm.regimen.trim(),
        therapy_start: therapyForm.therapy_start,
        therapy_end: therapyForm.therapy_end || null,
      });
      setTherapyOpen(false);
      setMessage(therapyForm.therapy_end
        ? "Окончание терапии сохранено. В плане появятся контрольные точки УВО-12 и УВО-24."
        : "Сведения о начатой терапии сохранены.");
      await load();
    } catch (err) {
      setModalError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function toggleConsent() {
    if (!patient) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await post(`/api/patients/${patient.id}/consent`, {
        consent_notifications: !patient.consent_notifications,
        preferred_channel: patient.preferred_channel,
      });
      setMessage(patient.consent_notifications
        ? "Согласие отозвано; сообщения в очереди отменены."
        : "Согласие на уведомления сохранено.");
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!patient) {
    return <div className="drawer-overlay" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <aside className="patient-drawer" role="dialog" aria-modal="true" aria-label="Карточка пациента">
        <button type="button" className="icon-button drawer-close" onClick={onClose} aria-label="Закрыть карточку"><Icon name="close" /></button>
        {loading ? <div className="empty-state"><span className="loading-spinner" />Загружаем карточку…</div> : <Feedback error={error || "Не удалось загрузить пациента"} />}
        {!loading && <button className="button button-secondary" onClick={() => void load()}>Повторить загрузку</button>}
      </aside>
    </div>;
  }

  const encounterSavedToday = patient.encounters?.some((visit) => visit.visit_date.slice(0, 10) === localDateInput()) ?? false;
  const openPlanItems = patient.plan.filter((item) => item.status === "PLANNED" || item.status === "OVERDUE").length;

  return (
    <div className="drawer-overlay" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <aside className="patient-drawer" role="dialog" aria-modal="true" aria-label={`Карточка пациента ${patient.full_name}`}>
        <div className="drawer-topline"><span className="eyebrow">Карточка пациента</span><button type="button" className="icon-button drawer-close" onClick={onClose} aria-label="Закрыть карточку"><Icon name="close" /></button></div>
        {loading && <div className="drawer-loading"><span className="loading-spinner" />Обновляем данные…</div>}
        <div className="patient-header">
          <div className="patient-avatar">{initials(patient.full_name)}</div>
          <div className="patient-heading-copy"><p className="eyebrow">{patient.diagnosis_code} · {patient.nosology}</p><h2>{patient.full_name}</h2>
            <p>{patient.fibrosis_stage}{patient.cirrhosis ? " · цирроз" : ""}{patient.genotype ? ` · генотип ${patient.genotype}` : ""}</p></div>
        </div>
        <div className="patient-status-row">
          <span className={`status-pill status-${patient.status.toLowerCase()}`}>{STATUS_LABELS[patient.status] ?? patient.status}</span>
          <ZoneBadge zone={patient.zone} />
          <span className="meta-chip"><Icon name="calendar" />На наблюдении с {fmtDate(patient.enrolled_at)}</span>
        </div>
        <p className="status-explainer">Статус — этап терапии и наблюдения. Цвет зоны — срочность по датам плана.</p>
        <div className="patient-facts">
          <div><span>Дата рождения</span><b>{fmtDate(patient.birth_date)}</b></div>
          <div><span>СНИЛС</span><b>{patient.snils ?? "Не указан"}</b></div>
          <div><span>Телефон</span><b>{patient.phone ?? "Не указан"}</b></div>
          <div><span>Открытые события</span><b>{openPlanItems}</b></div>
        </div>
        {(patient.therapy_regimen || patient.svr12_achieved !== null && patient.svr12_achieved !== undefined) && <div className="therapy-summary">
          <div className="therapy-summary-icon"><Icon name="activity" /></div><div><b>Терапия и контроль</b>
            {patient.therapy_regimen && <p>{patient.therapy_regimen}{patient.therapy_start ? ` · с ${fmtDate(patient.therapy_start)}` : ""}{patient.therapy_end ? ` по ${fmtDate(patient.therapy_end)}` : ""}</p>}
            {patient.svr12_achieved !== null && patient.svr12_achieved !== undefined && <p>УВО-12: <strong>{patient.svr12_achieved ? "достигнут" : "не достигнут"}</strong></p>}
          </div>
        </div>}
        {canConsent && <label className="consent-control"><input type="checkbox" checked={patient.consent_notifications} disabled={busy}
          onChange={() => void toggleConsent()} /><span><b>Согласие на уведомления</b><small>{patient.consent_notifications ? `Канал: ${patient.preferred_channel}` : "Не получено — сообщения не ставятся в очередь"}</small></span></label>}
        <Feedback error={error} message={message} />

        <section className="drawer-section">
          <div className="section-heading"><div><p className="eyebrow">Клинический маршрут</p><h3>План наблюдения</h3></div><span className="section-count">{patient.plan.length} событий</span></div>
          <p className="section-description">Новые будущие контрольные точки после приёма — ожидаемая часть непрерывного наблюдения.</p>
          {patient.plan.length === 0 ? <div className="empty-inline">Для пациента пока нет событий плана.</div> : <div className="table-scroll plan-table-scroll"><table className="data-table plan-table">
            <thead><tr><th>Событие</th><th>Срок</th><th>Статус</th><th>Действие</th></tr></thead>
            <tbody>{patient.plan.map((item) => (
              <tr key={item.id} className={item.status === "OVERDUE" ? "row-overdue" : ""}>
                <td><b>{item.title}</b><span className="table-subline">{item.kind}{item.result ? ` · ${item.result}` : ""}</span>
                  {item.rule_ref && <span className="rule-note">{item.rule_ref}</span>}</td>
                <td className="date-cell">{fmtDate(item.due_date)}</td>
                <td><span className={`plan-status plan-${item.status.toLowerCase()}`}>{PLAN_STATUS_LABELS[item.status] ?? item.status}</span></td>
                <td>{canCompletePlanItem(user.role, item.kind) && item.status !== "DONE" && item.status !== "CANCELLED" &&
                  <button className="button button-small button-quiet" disabled={busy} onClick={() => openCompletion(item)}>Отметить</button>}</td>
              </tr>
            ))}</tbody>
          </table></div>}
        </section>

        {canEncounter && <section className="drawer-section encounter-section">
          <div className="section-heading"><div><p className="eyebrow">Рабочее место врача</p><h3>Запись о приёме</h3></div><span className="unsigned-tag">Без электронной подписи</span></div>
          <p className="section-description">Сохранение приёма не завершает лечение. После записи планировщик сохранит следующий цикл наблюдения.</p>
          {encounterSavedToday && <div className="notice notice-success"><Icon name="check" /><span><b>Приём за сегодня уже сохранён.</b><small>Повторная запись отключена, чтобы не сдвигать будущий план.</small></span></div>}
          <label className="field"><span>Жалобы и данные осмотра</span><textarea placeholder="Кратко зафиксируйте жалобы или данные осмотра…" value={complaints} onChange={(event) => setComplaints(event.target.value)} disabled={busy || encounterSavedToday} /></label>
          <label className="field"><span>Заключение врача</span><textarea placeholder="Введите заключение. Черновик-подсказка будет сформирован отдельно и потребует проверки…" value={conclusion} onChange={(event) => setConclusion(event.target.value)} disabled={busy || encounterSavedToday} /></label>
          <div className="encounter-actions">
            <button className="button button-primary" onClick={() => void encounter()} disabled={busy || encounterSavedToday}>
              <Icon name="check" />{busy ? "Сохраняем…" : encounterSavedToday ? "Приём сохранён сегодня" : "Сохранить приём"}
            </button>
            <button className="button button-secondary" onClick={openTherapy} disabled={busy}><Icon name="activity" />ПВТ и даты терапии</button>
          </div>
          {draft && <div className="draft-card"><div className="draft-label"><Icon name="activity" />Демонстрационный черновик · требует проверки врача</div><p>{draft}</p></div>}
        </section>}

        {patient.encounters && patient.encounters.length > 0 && <section className="drawer-section history-section">
          <div className="section-heading"><div><p className="eyebrow">Хронология</p><h3>История приёмов</h3></div><span className="section-count">{patient.encounters.length}</span></div>
          <div className="timeline">{patient.encounters.map((visit) => <article key={visit.id} className="timeline-item">
            <span className="timeline-dot" /><div><time>{fmtDate(visit.visit_date)}</time><p>{visit.conclusion ?? visit.draft_conclusion ?? "Запись без текста заключения"}</p>
              {!visit.signed && <span className="unsigned-tag">Черновик · не подписан</span>}</div>
          </article>)}</div>
        </section>}
      </aside>

      {completionItem && <Modal title="Отметить событие выполненным"
        description={`${completionItem.title} · плановая дата ${fmtDate(completionItem.due_date)}`} onClose={() => setCompletionItem(null)} busy={busy}>
        <form className="modal-form" onSubmit={submitCompletion}>
          <label className="field"><span>Результат или комментарий{completionItem.kind === "SVR12" && <i> *</i>}</span>
            <textarea data-autofocus value={completionResult} onChange={(event) => setCompletionResult(event.target.value)} disabled={busy}
              placeholder={completionItem.kind === "SVR12" ? "Например: РНК ВГС не обнаружена" : "Например: анализ выполнен, результат внесён в карту"}
              required={completionItem.kind === "SVR12"} /></label>
          {completionItem.kind === "SVR12" && <p className="field-hint">Для фиксации УВО-12 нужен однозначный результат ПЦР: обнаружена или не обнаружена РНК.</p>}
          <Feedback error={modalError} />
          <div className="modal-actions"><button type="button" className="button button-quiet" onClick={() => setCompletionItem(null)} disabled={busy}>Отмена</button>
            <button className="button button-primary" type="submit" disabled={busy}>{busy ? "Сохраняем…" : "Сохранить результат"}</button></div>
        </form>
      </Modal>}

      {therapyOpen && <Modal title="Сведения о противовирусной терапии"
        description="Эти даты формируют контрольные точки в демонстрационном плане. Схему лечения определяет врач." onClose={() => setTherapyOpen(false)} busy={busy}>
        <form className="modal-form" onSubmit={submitTherapy}>
          <label className="field"><span>Схема терапии <i>*</i></span><input data-autofocus value={therapyForm.regimen} disabled={busy}
            onChange={(event) => setTherapyForm((current) => ({ ...current, regimen: event.target.value }))}
            placeholder="Укажите назначенную схему" required maxLength={200} /></label>
          <div className="form-grid modal-form-grid">
            <label className="field"><span>Дата начала <i>*</i></span><input type="date" value={therapyForm.therapy_start} required disabled={busy}
              onChange={(event) => setTherapyForm((current) => ({ ...current, therapy_start: event.target.value }))} /></label>
            <label className="field"><span>Дата окончания</span><input type="date" value={therapyForm.therapy_end} disabled={busy}
              onChange={(event) => setTherapyForm((current) => ({ ...current, therapy_end: event.target.value }))} /></label>
          </div>
          <p className="field-hint">Оставьте дату окончания пустой, если курс продолжается. При её заполнении приложение добавит контроль УВО-12/24.</p>
          <Feedback error={modalError} />
          <div className="modal-actions"><button type="button" className="button button-quiet" onClick={() => setTherapyOpen(false)} disabled={busy}>Отмена</button>
            <button className="button button-primary" type="submit" disabled={busy}>{busy ? "Сохраняем…" : "Сохранить терапию"}</button></div>
        </form>
      </Modal>}
    </div>
  );
}

function Tasks({ onOpenPatient, refreshToken }: { onOpenPatient: (id: number) => void; refreshToken: number }) {
  const [tasks, setTasks] = useState<CareTask[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busyTaskId, setBusyTaskId] = useState<number | null>(null);
  const [selectedTask, setSelectedTask] = useState<CareTask | null>(null);
  const [outcome, setOutcome] = useState<CareOutcomeCode>("WILL_COME");
  const [comment, setComment] = useState("");
  const [modalError, setModalError] = useState("");

  const load = useCallback(async () => {
    setError("");
    setLoading(true);
    try {
      setTasks(await api<CareTask[]>("/api/care/tasks"));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { void load(); }, [load, refreshToken]);

  function openOutcome(task: CareTask) {
    setSelectedTask(task);
    setOutcome("WILL_COME");
    setComment("");
    setModalError("");
  }

  async function submitOutcome(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedTask) return;
    setBusyTaskId(selectedTask.id);
    setModalError("");
    try {
      await post(`/api/care/tasks/${selectedTask.id}/complete`, { outcome, comment: comment.trim() || null });
      setSelectedTask(null);
      await load();
    } catch (err) {
      setModalError((err as Error).message);
    } finally {
      setBusyTaskId(null);
    }
  }

  return (
    <section className="page-section">
      <PageHeading eyebrow="Care Management" title="Задачи обзвона" description="Здесь фиксируют контакт с пациентом, если контрольное событие просрочено. Звонок не закрывает медицинское событие в плане." />
      <div className="notice notice-info"><Icon name="phone" /><span><b>Как это работает</b><small>Задачи создаются при дневном пересчёте для пациентов с просрочками. Результат звонка сохраняется отдельно от визита или анализа.</small></span></div>
      <Feedback error={error} />
      <div className="table-card">
        <div className="table-card-heading"><div><h2>Открытые задачи</h2><p>{loading ? "Обновляем список…" : `${tasks.length} задач требуют внимания`}</p></div>
          <button className="button button-secondary" onClick={() => void load()} disabled={loading}><Icon name="refresh" />Обновить</button></div>
        {loading && tasks.length === 0 ? <div className="empty-state"><span className="loading-spinner" />Загружаем задачи…</div> : tasks.length === 0 ?
          <div className="empty-state"><span className="empty-icon"><Icon name="check" /></span><b>Открытых задач нет</b><span>Новые задачи появятся, если после пересчёта найдутся просроченные события.</span></div> :
          <div className="table-scroll"><table className="data-table">
            <thead><tr><th>Пациент</th><th>Причина</th><th>Приоритет</th><th>Срок звонка</th><th>Действие</th></tr></thead>
            <tbody>{tasks.map((task) => <tr key={task.id}>
              <td><button className="text-link" onClick={() => onOpenPatient(task.patient_id)}>{task.patient_name}</button></td>
              <td><b>{task.title}</b><span className="table-subline">{task.kind === "ESCALATION" ? "Эскалация" : "Связаться с пациентом"}</span></td>
              <td><span className={`priority-pill priority-${task.priority}`}>{task.priority === "high" ? "Высокий" : "Обычный"}</span></td>
              <td>{fmtDate(task.due_date)}</td>
              <td><button className="button button-small button-secondary" disabled={busyTaskId === task.id} onClick={() => openOutcome(task)}>
                Зафиксировать звонок<Icon name="arrow" /></button></td>
            </tr>)}</tbody>
          </table></div>}
      </div>
      {selectedTask && <Modal title="Зафиксировать исход звонка" description={`Пациент: ${selectedTask.patient_name}. Исход звонка не меняет статус просроченного события в плане.`} onClose={() => setSelectedTask(null)} busy={busyTaskId === selectedTask.id}>
        <form className="modal-form" onSubmit={submitOutcome}>
          <label className="field"><span>Что произошло? <i>*</i></span><select data-autofocus value={outcome} disabled={busyTaskId === selectedTask.id} onChange={(event) => setOutcome(event.target.value as CareOutcomeCode)}>
            <option value="WILL_COME">Подтвердил явку</option><option value="REFUSED">Отказался</option>
            <option value="NO_ANSWER">Не ответил</option><option value="UNREACHABLE">Не удалось дозвониться</option>
          </select></label>
          <label className="field"><span>Комментарий</span><textarea value={comment} disabled={busyTaskId === selectedTask.id} onChange={(event) => setComment(event.target.value)} placeholder="Например: согласовали удобную дату визита…" maxLength={2000} /></label>
          <Feedback error={modalError} />
          <div className="modal-actions"><button type="button" className="button button-quiet" onClick={() => setSelectedTask(null)} disabled={busyTaskId === selectedTask.id}>Отмена</button>
            <button className="button button-primary" type="submit" disabled={busyTaskId === selectedTask.id}>{busyTaskId === selectedTask.id ? "Сохраняем…" : "Сохранить исход"}</button></div>
        </form>
      </Modal>}
    </section>
  );
}

function AnalyticsView({ refreshToken }: { refreshToken: number }) {
  const [analytics, setAnalytics] = useState<Analytics | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    setError("");
    setLoading(true);
    try {
      setAnalytics(await api<Analytics>("/api/analytics/overview"));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { void load(); }, [load, refreshToken]);
  if (loading && !analytics) return <section className="page-section"><div className="empty-state"><span className="loading-spinner" />Собираем аналитику…</div></section>;
  if (!analytics) return <section className="page-section"><PageHeading eyebrow="Сводные показатели" title="Аналитика" description="Агрегированная информация о ходе диспансерного наблюдения." /><Feedback error={error || "Нет данных"} /><button className="button button-secondary" onClick={() => void load()}>Повторить загрузку</button></section>;
  const maxNosology = Math.max(1, ...Object.values(analytics.by_nosology));
  return (
    <section className="page-section">
      <PageHeading eyebrow="Сводные показатели" title="Аналитика" description="Агрегированный обзор регистра, выполнения плана и контрольных результатов." />
      <Feedback error={error} />
      <div className="stats-grid analytics-stats">
        <StatCard title="В регистре" value={String(analytics.registry_total)} hint={`${analytics.active_total} пациентов активно наблюдаются`} accent="#2d7481" />
        <StatCard title="Выполнение плана" value={pct(analytics.adherence)} hint={`Выполнено ${analytics.plan_done} · просрочено ${analytics.plan_overdue}`} accent="#418c76" />
        <StatCard title="Доля УВО-12" value={pct(analytics.svr_rate)} hint={`Проверено ${analytics.svr12_checked} · достигнуто ${analytics.svr12_achieved}`} accent="#6e62a6" />
        <StatCard title="Красная зона" value={String(analytics.zones.red)} hint="Есть просроченные события" accent="#bf6265" />
      </div>
      <div className="analytics-grid">
        <div className="table-card analytics-card"><div className="table-card-heading"><div><h2>По нозологиям</h2><p>Распределение пациентов в текущем контуре</p></div></div>
          {Object.entries(analytics.by_nosology).length ? Object.entries(analytics.by_nosology).map(([key, value]) => <div key={key} className="bar-row"><span>{key}</span><div className="bar"><div style={{ width: `${(value / maxNosology) * 100}%` }} /></div><b>{value}</b></div>) : <div className="empty-inline">Нет данных для отображения.</div>}
        </div>
        <div className="table-card analytics-card"><div className="table-card-heading"><div><h2>Нагрузка по врачам</h2><p>Число пациентов в регистре</p></div></div>
          {Object.entries(analytics.by_doctor).length ? Object.entries(analytics.by_doctor).map(([name, value]) => <div key={name} className="doctor-load"><span className="user-avatar">{initials(name)}</span><span>{name}</span><b>{value}</b></div>) : <div className="empty-inline">Нет данных для отображения.</div>}
        </div>
      </div>
      <p className="disclaimer-note">Демонстрационная аналитика. Региональные показатели требуют реальных интеграций и проверенных данных.</p>
    </section>
  );
}

function Notifications({ refreshToken }: { refreshToken: number }) {
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    setError("");
    setLoading(true);
    try {
      setItems(await api<NotificationItem[]>("/api/notifications"));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { void load(); }, [load, refreshToken]);
  return (
    <section className="page-section">
      <PageHeading eyebrow="Коммуникации" title="Уведомления" description="Демонстрационный журнал напоминаний и сообщений по пациентам." />
      <div className="notice notice-info"><Icon name="bell" /><span><b>Сообщения не отправляются пациентам</b><small>В MVP это только записи в журнале; каналы СМС, push и Госуслуги не подключены.</small></span></div>
      <Feedback error={error} />
      <div className="table-card"><div className="table-card-heading"><div><h2>Журнал сообщений</h2><p>{loading ? "Загружаем…" : `${items.length} записей`}</p></div><button className="button button-secondary" onClick={() => void load()} disabled={loading}><Icon name="refresh" />Обновить</button></div>
        {loading && items.length === 0 ? <div className="empty-state"><span className="loading-spinner" />Загружаем журнал…</div> : items.length === 0 ? <div className="empty-state"><span className="empty-icon"><Icon name="bell" /></span><b>Пока нет сообщений</b><span>Записи появятся при создании плана и выполнении дневного пересчёта.</span></div> :
          <div className="table-scroll"><table className="data-table"><thead><tr><th>Пациент</th><th>Дата</th><th>Тип</th><th>Канал</th><th>Статус</th><th>Текст</th></tr></thead>
            <tbody>{items.map((item) => <tr key={item.id}><td>№ {item.patient_id}</td><td>{fmtDate(item.scheduled_for)}</td><td>{item.kind}</td><td>{item.channel}</td>
              <td><span className={`plan-status notification-status notification-${item.status.toLowerCase()}`}>{NOTIFICATION_STATUS_LABELS[item.status] ?? item.status}</span></td><td className="notification-text">{item.text}</td></tr>)}</tbody>
          </table></div>}
      </div>
    </section>
  );
}

function Audit({ refreshToken }: { refreshToken: number }) {
  const [items, setItems] = useState<AuditItem[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    setError("");
    setLoading(true);
    try {
      setItems(await api<AuditItem[]>("/api/audit"));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { void load(); }, [load, refreshToken]);
  return (
    <section className="page-section">
      <PageHeading eyebrow="Контроль доступа" title="Журнал аудита" description="История значимых действий пользователей в текущей организации." />
      <Feedback error={error} />
      <div className="table-card"><div className="table-card-heading"><div><h2>Последние действия</h2><p>{loading ? "Загружаем…" : `${items.length} записей`}</p></div><button className="button button-secondary" onClick={() => void load()} disabled={loading}><Icon name="refresh" />Обновить</button></div>
        {loading && items.length === 0 ? <div className="empty-state"><span className="loading-spinner" />Загружаем журнал…</div> : items.length === 0 ? <div className="empty-state"><span className="empty-icon"><Icon name="audit" /></span><b>Записей пока нет</b><span>Действия появятся здесь по мере работы с приложением.</span></div> :
          <div className="table-scroll"><table className="data-table"><thead><tr><th>Дата</th><th>Пользователь</th><th>Действие</th><th>Объект</th><th>Детали</th></tr></thead>
            <tbody>{items.map((item) => <tr key={item.id}><td>{fmtDate(item.created_at)}</td><td>{item.actor}</td><td><span className="audit-action">{item.action}</span></td><td>{item.entity}</td><td>{item.details}</td></tr>)}</tbody>
          </table></div>}
      </div>
    </section>
  );
}
