import { useCallback, useEffect, useState } from "react";
import { api, getToken, post, setToken } from "./api";
import { PatientRow, StatCard, ZoneBadge } from "./components";
import type { Analytics, CareTask, Patient, User, Zone } from "./types";
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

const canManagePatients = (role: string) => ["doctor", "head", "nurse", "admin"].includes(role);
const canConductEncounter = (role: string) => ["doctor", "head", "admin"].includes(role);
const canCompletePlanItem = (role: string, kind: string) =>
  ["doctor", "head", "nurse", "admin"].includes(role) &&
  !(role === "nurse" && ["VISIT", "SVR12"].includes(kind));
const canRunDailyJob = (role: string) => ["head", "nurse", "admin"].includes(role);

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

  if (booting) return <div className="center">Загрузка…</div>;
  if (!user) return <Login onLogin={setUser} />;
  return <Shell user={user} onLogout={() => { setToken(null); setUser(null); }} />;
}

function Login({ onLogin }: { onLogin: (u: User) => void }) {
  const [email, setEmail] = useState("doctor@gepa.local");
  const [password, setPassword] = useState("doctor123");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
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
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        <div className="logo">🧭 ГепаНавигатор</div>
        <p className="muted">Диспансерное наблюдение больных хроническими гепатитами · модуль ГИС ЭЗ РТ</p>
        <label>E-mail<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
        <label>Пароль<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required /></label>
        {error && <div className="error" role="alert">{error}</div>}
        <button className="primary" type="submit" disabled={busy}>{busy ? "Входим…" : "Войти"}</button>
        <div className="demo-box">
          <b>Демо-доступ:</b> doctor@gepa.local / doctor123 · head@gepa.local / head12345 ·
          nurse@gepa.local / nurse1234 · analyst@gepa.local / analyst123 · admin@gepa.local / admin12345
        </div>
      </form>
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
      setJobMsg(`Дневной пересчёт завершён: отмечено просрочек — ${result.overdue_marked}, записей напоминаний — ${result.reminders_created}, задач обзвона — ${result.care_tasks_created}.`);
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
  return (
    <div className="shell">
      <header>
        <div className="logo">🧭 ГепаНавигатор</div>
        <nav>
          {showClinicalViews && <button className={view === "worklist" ? "active" : ""} onClick={() => setView("worklist")}>Рабочее место</button>}
          {showTasks && <button className={view === "tasks" ? "active" : ""} onClick={() => setView("tasks")}>Задачи обзвона</button>}
          <button className={view === "analytics" ? "active" : ""} onClick={() => setView("analytics")}>Аналитика</button>
          {showNotifications && <button className={view === "notifications" ? "active" : ""} onClick={() => setView("notifications")}>Уведомления</button>}
          {(user.role === "head" || user.role === "admin") && (
            <button className={view === "audit" ? "active" : ""} onClick={() => setView("audit")}>Аудит</button>
          )}
        </nav>
        <div className="userbox">
          <div>{user.full_name}<div className="p-sub">{ROLE_LABELS[user.role] ?? user.role} · {user.org}</div></div>
          {canRunDailyJob(user.role) && <button onClick={runDaily} disabled={jobBusy} title="Пересчёт просрочек, очередь напоминаний и эскалация">
            {jobBusy ? "Пересчитываем…" : "▶ Дневной job"}
          </button>}
          <button onClick={onLogout}>Выйти</button>
        </div>
      </header>
      {(jobMsg || jobError) && <div className={jobError ? "jobmsg error" : "jobmsg"} role={jobError ? "alert" : "status"}>{jobError || jobMsg}</div>}
      <main>
        {view === "worklist" && showClinicalViews && <Worklist
          onOpen={setSelectedPatientId}
          refreshToken={refreshToken}
          canCreate={canManagePatients(user.role)}
        />}
        {view === "tasks" && showTasks && <Tasks
          onOpenPatient={setSelectedPatientId}
          refreshToken={refreshToken}
        />}
        {view === "analytics" && <AnalyticsView refreshToken={refreshToken} />}
        {view === "notifications" && showNotifications && <Notifications refreshToken={refreshToken} />}
        {view === "audit" && (user.role === "head" || user.role === "admin") && <Audit refreshToken={refreshToken} />}
      </main>
      {selectedPatientId !== null && <PatientCard
        patientId={selectedPatientId}
        user={user}
        onClose={() => setSelectedPatientId(null)}
      />}
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
      if (zone) rows = rows.filter((p) => p.zone === zone);
      if (search) rows = rows.filter((p) => p.full_name.toLowerCase().includes(search.toLowerCase()));
      setPatients(rows);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [search, zone]);
  useEffect(() => { void load(); }, [load, refreshToken]);

  return (
    <section>
      <h1>Рабочее место врача — пациенты на наблюдении</h1>
      {summary && (
        <div className="stats">
          <StatCard title="Красная зона" value={String(summary.red)} hint={ZONE_META.red.hint} accent={ZONE_META.red.color} />
          <StatCard title="Контроль УВО" value={String(summary.purple)} hint={ZONE_META.purple.hint} accent={ZONE_META.purple.color} />
          <StatCard title="Запланировано" value={String(summary.yellow)} hint={ZONE_META.yellow.hint} accent={ZONE_META.yellow.color} />
          <StatCard title="Всё выполнено" value={String(summary.green)} hint={ZONE_META.green.hint} accent={ZONE_META.green.color} />
        </div>
      )}
      <div className="toolbar">
        <input placeholder="Поиск по ФИО…" value={search} onChange={(e) => setSearch(e.target.value)} />
        <select value={zone} onChange={(e) => setZone(e.target.value)} aria-label="Фильтр по зоне">
          <option value="">Все зоны</option>
          {Object.entries(ZONE_META).map(([key, meta]) => <option key={key} value={key}>{meta.label}</option>)}
        </select>
        {canCreate && <button className="primary" onClick={() => setShowForm((open) => !open)}>
          {showForm ? "Закрыть форму" : "+ Пациент в регистр"}
        </button>}
      </div>
      {showForm && canCreate && <NewPatient onCreated={() => { setShowForm(false); void load(); }} />}
      {error && <div className="error" role="alert">{error} <button onClick={() => void load()}>Повторить</button></div>}
      {loading && patients.length === 0 ? <p className="muted">Загружаем список…</p> : (
        <table className="grid">
          <thead><tr><th>Пациент</th><th>Диагноз</th><th>Статус</th><th>Зона</th><th>Ближайшее событие</th></tr></thead>
          <tbody>{patients.map((patient) => <PatientRow key={patient.id} patient={patient} onOpen={(p) => onOpen(p.id)} />)}</tbody>
        </table>
      )}
      {!loading && patients.length === 0 && !error && <p className="muted">Пациенты не найдены.</p>}
    </section>
  );
}

function NewPatient({ onCreated }: { onCreated: () => void }) {
  const [form, setForm] = useState<NewPatientForm>({
    full_name: "", birth_date: "", sex: "", snils: "", oms: "", phone: "",
    consent_notifications: false, preferred_channel: "sms", diagnosis_code: "B18.2",
    nosology: "HCV", fibrosis_stage: "F1", cirrhosis: false,
  });
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const update = <K extends keyof NewPatientForm>(key: K, value: NewPatientForm[K]) =>
    setForm((current) => ({ ...current, [key]: value }));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
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
      <h3>Постановка на диспансерное наблюдение</h3>
      <div className="form-grid">
        <label>ФИО<input value={form.full_name} onChange={(e) => update("full_name", e.target.value)} required minLength={3} maxLength={160} /></label>
        <label>Дата рождения<input type="date" value={form.birth_date} onChange={(e) => update("birth_date", e.target.value)} required /></label>
        <label>Пол<select value={form.sex} onChange={(e) => update("sex", e.target.value as NewPatientForm["sex"])} required>
          <option value="">Выберите</option><option value="F">Женский</option><option value="M">Мужской</option>
        </select></label>
        <label>СНИЛС<input value={form.snils} onChange={(e) => update("snils", e.target.value)} placeholder="112-233-445 95" /></label>
        <label>Полис ОМС<input value={form.oms} onChange={(e) => update("oms", e.target.value)} placeholder="16 цифр, необязательно" /></label>
        <label>Телефон<input type="tel" value={form.phone} onChange={(e) => update("phone", e.target.value)} /></label>
        <label>МКБ-10<input value={form.diagnosis_code} onChange={(e) => update("diagnosis_code", e.target.value)} required /></label>
        <label>Нозология<select value={form.nosology} onChange={(e) => update("nosology", e.target.value as NewPatientForm["nosology"])}>
          <option value="HCV">Гепатит C</option><option value="HBV">Гепатит B</option><option value="HDV">Гепатит D</option><option value="MIXED">Сочетанная инфекция</option>
        </select></label>
        <label>Фиброз<select value={form.fibrosis_stage} onChange={(e) => update("fibrosis_stage", e.target.value as NewPatientForm["fibrosis_stage"])}>
          {["F0", "F1", "F2", "F3", "F4"].map((stage) => <option key={stage} value={stage}>{stage}</option>)}
        </select></label>
        <label className="check"><input type="checkbox" checked={form.cirrhosis} onChange={(e) => update("cirrhosis", e.target.checked)} /> Цирроз печени</label>
        <label className="check"><input type="checkbox" checked={form.consent_notifications} onChange={(e) => update("consent_notifications", e.target.checked)} /> Получено согласие на уведомления</label>
        <label>Канал уведомлений<select value={form.preferred_channel} disabled={!form.consent_notifications}
          onChange={(e) => update("preferred_channel", e.target.value as NewPatientForm["preferred_channel"])}>
          <option value="sms">СМС (демо)</option><option value="push">Push (демо)</option><option value="gosuslugi">Госуслуги (демо)</option>
        </select></label>
      </div>
      {error && <div className="error" role="alert">{error}</div>}
      <button className="primary" type="submit" disabled={saving}>{saving ? "Сохраняем…" : "Создать и сгенерировать план по КР"}</button>
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
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
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

  async function complete(itemId: number) {
    const result = window.prompt("Введите результат (например: «РНК ВГС не обнаружена» или значение анализа)");
    if (result === null) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await post(`/api/plan-items/${itemId}/complete`, { result });
      setMessage("Событие отмечено выполненным, план обновлён.");
      await load();
    } catch (err) {
      setError((err as Error).message);
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
      setMessage("Приём сохранён, план наблюдения обновлён.");
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function therapy() {
    if (!patient) return;
    const regimen = window.prompt("Схема ПВТ", patient.therapy_regimen ?? "Софосбувир/Велпатасвир 12 нед");
    if (regimen === null || !regimen.trim()) return;
    const startDefault = patient.therapy_start ?? new Date().toISOString().slice(0, 10);
    const therapyStart = window.prompt("Дата начала терапии (ГГГГ-ММ-ДД)", startDefault);
    if (therapyStart === null || !therapyStart.trim()) return;
    const therapyEnd = window.prompt("Дата окончания (ГГГГ-ММ-ДД); оставьте пустым, если терапия продолжается", patient.therapy_end ?? "");
    if (therapyEnd === null) return;

    setBusy(true);
    setError("");
    setMessage("");
    try {
      await post(`/api/patients/${patient.id}/therapy`, {
        regimen: regimen.trim(),
        therapy_start: therapyStart.trim(),
        therapy_end: therapyEnd.trim() || null,
      });
      setMessage(therapyEnd.trim()
        ? "Терапия завершена: назначены контрольные точки УВО-12 и УВО-24."
        : "Пациент отмечен как проходящий терапию.");
      await load();
    } catch (err) {
      setError((err as Error).message);
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
    return <div className="drawer-overlay" onClick={onClose}><div className="drawer" onClick={(e) => e.stopPropagation()}>
      <button className="close" onClick={onClose}>✕</button>
      {loading ? <p>Загрузка карточки…</p> : <div className="error" role="alert">{error || "Не удалось загрузить пациента"} <button onClick={() => void load()}>Повторить</button></div>}
    </div></div>;
  }

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div className="drawer" onClick={(e) => e.stopPropagation()}>
        <button className="close" onClick={onClose} aria-label="Закрыть карточку">✕</button>
        <h2>{patient.full_name}</h2>
        <div className="muted">{patient.diagnosis_code} · {patient.nosology} · фиброз {patient.fibrosis_stage}{patient.cirrhosis ? " · цирроз" : ""}{patient.genotype ? ` · генотип ${patient.genotype}` : ""}</div>
        <div className="card-meta">
          <span>Статус: <b>{STATUS_LABELS[patient.status] ?? patient.status}</b></span><ZoneBadge zone={patient.zone} />
          <span>СНИЛС: {patient.snils ?? "—"}</span><span>Телефон: {patient.phone ?? "—"}</span>
          <span>На учёте с {fmtDate(patient.enrolled_at)} ({patient.enrollment_trigger})</span>
          {patient.therapy_regimen && <span>ПВТ: {patient.therapy_regimen}</span>}
          {patient.svr12_achieved !== null && patient.svr12_achieved !== undefined && <span>УВО-12: <b>{patient.svr12_achieved ? "достигнут" : "не достигнут"}</b></span>}
        </div>
        {canConsent && <label className="check"><input type="checkbox" checked={patient.consent_notifications} disabled={busy}
          onChange={() => void toggleConsent()} /> Согласие на уведомления ({patient.preferred_channel})</label>}

        <h3>Индивидуальный план наблюдения по КР</h3>
        <table className="grid compact">
          <thead><tr><th>Событие</th><th>Срок</th><th>Статус</th><th>Основание</th><th></th></tr></thead>
          <tbody>
            {patient.plan.map((item) => (
              <tr key={item.id} className={item.status === "OVERDUE" ? "row-red" : ""}>
                <td>{item.title}<div className="p-sub">{item.kind}{item.result ? ` · результат: ${item.result}` : ""}</div></td>
                <td>{fmtDate(item.due_date)}</td>
                <td>{PLAN_STATUS_LABELS[item.status] ?? item.status}</td>
                <td className="rule">{item.rule_ref}</td>
                <td>{canCompletePlanItem(user.role, item.kind) && item.status !== "DONE" && item.status !== "CANCELLED" &&
                  <button disabled={busy} onClick={() => void complete(item.id)}>Выполнено</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {canEncounter && <>
          <h3>Провести приём</h3>
          <textarea placeholder="Жалобы / данные осмотра (голосовой ввод не подключён в MVP)…" value={complaints} onChange={(e) => setComplaints(e.target.value)} disabled={busy} />
          <textarea placeholder="Заключение врача (черновик; электронная подпись в MVP не подключена)…" value={conclusion} onChange={(e) => setConclusion(e.target.value)} disabled={busy} />
          <div className="actions">
            <button className="primary" onClick={() => void encounter()} disabled={busy}>{busy ? "Сохраняем…" : "Завершить приём"}</button>
            <button onClick={() => void therapy()} disabled={busy}>ПВТ: назначить / завершить</button>
          </div>
          {draft && <div className="draft"><b>Черновик заключения (шаблон, требует проверки врача):</b><br />{draft}</div>}
        </>}
        {loading && <div className="muted" role="status">Обновляем карточку…</div>}
        {error && <div className="error" role="alert">{error}</div>}
        {message && <div className="ok" role="status">{message}</div>}

        {patient.encounters && patient.encounters.length > 0 && <>
          <h3>История приёмов</h3>
          {patient.encounters.map((visit) => (
            <div key={visit.id} className="encounter"><b>{fmtDate(visit.visit_date)}</b> — {visit.conclusion ?? visit.draft_conclusion ?? "—"}</div>
          ))}
        </>}
      </div>
    </div>
  );
}

function Tasks({ onOpenPatient, refreshToken }: { onOpenPatient: (id: number) => void; refreshToken: number }) {
  const [tasks, setTasks] = useState<CareTask[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busyTaskId, setBusyTaskId] = useState<number | null>(null);
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

  async function complete(task: CareTask) {
    const outcome = window.prompt("Исход обзвона: WILL_COME | REFUSED | NO_ANSWER | UNREACHABLE", "WILL_COME");
    if (outcome === null) return;
    setBusyTaskId(task.id);
    setError("");
    try {
      await post(`/api/care/tasks/${task.id}/complete`, { outcome: outcome.trim(), comment: "" });
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusyTaskId(null);
    }
  }
  return (
    <section>
      <h1>Care Management — задачи обзвона и эскалации</h1>
      <p className="muted">После пропуска срока система формирует задачу, а сотрудник фиксирует результат звонка.</p>
      {error && <div className="error" role="alert">{error} <button onClick={() => void load()}>Повторить</button></div>}
      {loading && tasks.length === 0 ? <p className="muted">Загружаем задачи…</p> : <table className="grid">
        <thead><tr><th>Пациент</th><th>Задача</th><th>Приоритет</th><th>Срок</th><th></th></tr></thead>
        <tbody>{tasks.map((task) => (
          <tr key={task.id}>
            <td><button className="link" onClick={() => onOpenPatient(task.patient_id)}>{task.patient_name}</button></td>
            <td>{task.title}<div className="p-sub">{task.kind}</div></td><td>{task.priority}</td><td>{fmtDate(task.due_date)}</td>
            <td><button disabled={busyTaskId === task.id} onClick={() => void complete(task)}>
              {busyTaskId === task.id ? "Сохраняем…" : "Зафиксировать исход"}
            </button></td>
          </tr>))}
        </tbody>
      </table>}
      {!loading && tasks.length === 0 && !error && <p className="muted">Открытых задач нет.</p>}
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
  if (loading && !analytics) return <p>Загрузка аналитики…</p>;
  if (!analytics) return <section><h1>Аналитика</h1><div className="error" role="alert">{error || "Нет данных"} <button onClick={() => void load()}>Повторить</button></div></section>;
  const maxNosology = Math.max(1, ...Object.values(analytics.by_nosology));
  return (
    <section>
      <h1>Аналитика — охват, выполнение плана, УВО</h1>
      {error && <div className="error" role="alert">{error}</div>}
      <div className="stats">
        <StatCard title="В регистре / активно" value={`${analytics.registry_total} / ${analytics.active_total}`} hint="Пациенты в текущем контуре данных" />
        <StatCard title="Выполнение плана" value={pct(analytics.adherence)} hint={`Выполнено ${analytics.plan_done}, просрочено ${analytics.plan_overdue}`} accent="#1a9e6b" />
        <StatCard title="Доля УВО-12" value={pct(analytics.svr_rate)} hint={`Проверено ${analytics.svr12_checked}, достигнуто ${analytics.svr12_achieved}`} accent="#7b4fd0" />
        <StatCard title="Красная зона" value={String(analytics.zones.red)} hint="Требуется внимание / обзвон" accent="#d93636" />
      </div>
      <h3>По нозологиям</h3>
      {Object.entries(analytics.by_nosology).map(([key, value]) => (
        <div key={key} className="bar-row"><span>{key}</span><div className="bar"><div style={{ width: `${(value / maxNosology) * 100}%` }} /></div><b>{value}</b></div>
      ))}
      <h3>Нагрузка по врачам</h3>
      {Object.entries(analytics.by_doctor).map(([key, value]) => <p key={key}>{key}: <b>{value}</b> пациентов</p>)}
      <p className="muted">Демонстрационная аналитика в рамках текущего контура; региональные KPI требуют реальных интеграций и данных.</p>
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
    <section>
      <h1>Коммуникации — журнал уведомлений</h1>
      <p className="muted">Это очередь/журнал демо-уведомлений. Реальные СМС, push и Госуслуги здесь не отправляются.</p>
      {error && <div className="error" role="alert">{error} <button onClick={() => void load()}>Повторить</button></div>}
      {loading && items.length === 0 ? <p className="muted">Загружаем уведомления…</p> : <table className="grid">
        <thead><tr><th>Пациент ID</th><th>Дата</th><th>Тип</th><th>Канал</th><th>Статус</th><th>Текст</th></tr></thead>
        <tbody>{items.map((item) => <tr key={item.id}>
          <td>{item.patient_id}</td><td>{fmtDate(item.scheduled_for)}</td><td>{item.kind}</td><td>{item.channel}</td>
          <td>{NOTIFICATION_STATUS_LABELS[item.status] ?? item.status}</td><td>{item.text}</td>
        </tr>)}</tbody>
      </table>}
      {!loading && items.length === 0 && !error && <p className="muted">Записей уведомлений пока нет.</p>}
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
    <section>
      <h1>Журнал аудита</h1>
      {error && <div className="error" role="alert">{error} <button onClick={() => void load()}>Повторить</button></div>}
      {loading && items.length === 0 ? <p className="muted">Загружаем журнал…</p> : <table className="grid">
        <thead><tr><th>Когда</th><th>Кто</th><th>Действие</th><th>Объект</th><th>Детали</th></tr></thead>
        <tbody>{items.map((item) => <tr key={item.id}>
          <td>{fmtDate(item.created_at)}</td><td>{item.actor}</td><td>{item.action}</td><td>{item.entity}</td><td>{item.details}</td>
        </tr>)}</tbody>
      </table>}
      {!loading && items.length === 0 && !error && <p className="muted">Записей аудита пока нет.</p>}
    </section>
  );
}
