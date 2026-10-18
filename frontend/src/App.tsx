import { useCallback, useEffect, useState } from "react";
import { api, getToken, patch, post, setToken } from "./api";
import { PatientRow, StatCard, ZoneBadge } from "./components";
import type { Analytics, CareTask, Patient, User, Zone } from "./types";
import { ROLE_LABELS, STATUS_LABELS, ZONE_META, fmtDate, pct } from "./utils";

type View = "worklist" | "tasks" | "analytics" | "audit" | "notifications";

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [booting, setBooting] = useState(true);

  useEffect(() => {
    if (!getToken()) { setBooting(false); return; }
    api<User>("/api/auth/me").then(setUser).catch(() => setToken(null)).finally(() => setBooting(false));
  }, []);

  if (booting) return <div className="center">Загрузка…</div>;
  if (!user) return <Login onLogin={setUser} />;
  return <Shell user={user} onLogout={() => { setToken(null); setUser(null); }} />;
}

function Login({ onLogin }: { onLogin: (u: User) => void }) {
  const [email, setEmail] = useState("doctor@gepa.local");
  const [password, setPassword] = useState("doctor123");
  const [error, setError] = useState("");
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    try {
      const data = await post<{ access_token: string; user: User }>("/api/auth/login", { email, password });
      setToken(data.access_token);
      onLogin(data.user);
    } catch (err) { setError((err as Error).message); }
  }
  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        <div className="logo">🧭 ГепаНавигатор</div>
        <p className="muted">Диспансерное наблюдение больных хроническими гепатитами · модуль ГИС ЭЗ РТ</p>
        <label>E-mail<input value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
        <label>Пароль<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required /></label>
        {error && <div className="error" role="alert">{error}</div>}
        <button className="primary" type="submit">Войти</button>
        <div className="demo-box">
          <b>Демо-доступ:</b> doctor@gepa.local / doctor123 · head@gepa.local / head12345 ·
          nurse@gepa.local / nurse1234 · analyst@gepa.local / analyst123 · admin@gepa.local / admin12345
        </div>
      </form>
    </div>
  );
}

function Shell({ user, onLogout }: { user: User; onLogout: () => void }) {
  const [view, setView] = useState<View>("worklist");
  const [selected, setSelected] = useState<Patient | null>(null);
  const [jobMsg, setJobMsg] = useState("");
  async function runDaily() {
    try {
      const r = await post<{ overdue_marked: number; reminders_created: number; care_tasks_created: number }>("/api/jobs/run-daily");
      setJobMsg(`Job: просрочек отмечено ${r.overdue_marked}, напоминаний ${r.reminders_created}, задач обзвона ${r.care_tasks_created}`);
    } catch (e) { setJobMsg((e as Error).message); }
  }
  return (
    <div className="shell">
      <header>
        <div className="logo">🧭 ГепаНавигатор</div>
        <nav>
          <button className={view === "worklist" ? "active" : ""} onClick={() => setView("worklist")}>Рабочее место</button>
          <button className={view === "tasks" ? "active" : ""} onClick={() => setView("tasks")}>Задачи обзвона</button>
          <button className={view === "analytics" ? "active" : ""} onClick={() => setView("analytics")}>Аналитика</button>
          <button className={view === "notifications" ? "active" : ""} onClick={() => setView("notifications")}>Уведомления</button>
          {(user.role === "head" || user.role === "admin") && (
            <button className={view === "audit" ? "active" : ""} onClick={() => setView("audit")}>Аудит</button>
          )}
        </nav>
        <div className="userbox">
          <div>{user.full_name}<div className="p-sub">{ROLE_LABELS[user.role] ?? user.role} · {user.org}</div></div>
          {(user.role === "head" || user.role === "admin" || user.role === "nurse") && (
            <button onClick={runDaily} title="Пересчёт просрочек, напоминания, эскалация">▶ Дневной job</button>
          )}
          <button onClick={onLogout}>Выйти</button>
        </div>
      </header>
      {jobMsg && <div className="jobmsg">{jobMsg}</div>}
      <main>
        {view === "worklist" && <Worklist onOpen={setSelected} />}
        {view === "tasks" && <Tasks onOpenPatient={async (id) => setSelected(await api<Patient>(`/api/patients/${id}`))} />}
        {view === "analytics" && <AnalyticsView />}
        {view === "notifications" && <Notifications />}
        {view === "audit" && <Audit />}
      </main>
      {selected && <PatientCard patientId={selected.id} onClose={() => setSelected(null)} />}
    </div>
  );
}

function Worklist({ onOpen }: { onOpen: (p: Patient) => void }) {
  const [patients, setPatients] = useState<Patient[]>([]);
  const [summary, setSummary] = useState<Record<Zone, number> | null>(null);
  const [search, setSearch] = useState("");
  const [zone, setZone] = useState("");
  const [error, setError] = useState("");
  const [showForm, setShowForm] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await api<{ summary: Record<Zone, number>; patients: Patient[] }>("/api/worklist");
      setSummary(data.summary);
      let rows = data.patients;
      if (zone) rows = rows.filter((p) => p.zone === zone);
      if (search) rows = rows.filter((p) => p.full_name.toLowerCase().includes(search.toLowerCase()));
      setPatients(rows);
    } catch (e) { setError((e as Error).message); }
  }, [search, zone]);
  useEffect(() => { load(); }, [load]);

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
          {Object.entries(ZONE_META).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </select>
        <button className="primary" onClick={() => setShowForm(!showForm)}>+ Пациент в регистр</button>
      </div>
      {showForm && <NewPatient onCreated={() => { setShowForm(false); load(); }} />}
      {error && <div className="error">{error}</div>}
      <table className="grid">
        <thead><tr><th>Пациент</th><th>Диагноз</th><th>Статус</th><th>Зона</th><th>Ближайшее событие</th></tr></thead>
        <tbody>{patients.map((p) => <PatientRow key={p.id} patient={p} onOpen={onOpen} />)}</tbody>
      </table>
      {patients.length === 0 && <p className="muted">Пациенты не найдены.</p>}
    </section>
  );
}

function NewPatient({ onCreated }: { onCreated: () => void }) {
  const [f, setF] = useState({ full_name: "", birth_date: "1990-01-01", snils: "", phone: "", diagnosis_code: "B18.2", nosology: "HCV", fibrosis_stage: "F1", cirrhosis: false });
  const [error, setError] = useState("");
  const set = (k: string, v: unknown) => setF({ ...f, [k]: v });
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    try { await post("/api/patients", f); onCreated(); } catch (err) { setError((err as Error).message); }
  }
  return (
    <form className="form-card" onSubmit={submit}>
      <h3>Постановка на диспансерный учёт</h3>
      <div className="form-grid">
        <label>ФИО<input value={f.full_name} onChange={(e) => set("full_name", e.target.value)} required /></label>
        <label>Дата рождения<input type="date" value={f.birth_date} onChange={(e) => set("birth_date", e.target.value)} required /></label>
        <label>СНИЛС<input value={f.snils} onChange={(e) => set("snils", e.target.value)} placeholder="112-233-445 95" /></label>
        <label>Телефон<input value={f.phone} onChange={(e) => set("phone", e.target.value)} /></label>
        <label>МКБ-10<input value={f.diagnosis_code} onChange={(e) => set("diagnosis_code", e.target.value)} /></label>
        <label>Нозология<select value={f.nosology} onChange={(e) => set("nosology", e.target.value)}><option>HCV</option><option>HBV</option><option>HDV</option><option>MIXED</option></select></label>
        <label>Фиброз<select value={f.fibrosis_stage} onChange={(e) => set("fibrosis_stage", e.target.value)}>{["F0", "F1", "F2", "F3", "F4"].map((s) => <option key={s}>{s}</option>)}</select></label>
        <label className="check"><input type="checkbox" checked={f.cirrhosis} onChange={(e) => set("cirrhosis", e.target.checked)} /> Цирроз (скрининг ГЦР каждые 6 мес)</label>
      </div>
      {error && <div className="error">{error}</div>}
      <button className="primary" type="submit">Создать и сгенерировать план по КР</button>
    </form>
  );
}

function PatientCard({ patientId, onClose }: { patientId: number; onClose: () => void }) {
  const [p, setP] = useState<Patient | null>(null);
  const [complaints, setComplaints] = useState("");
  const [conclusion, setConclusion] = useState("");
  const [draft, setDraft] = useState("");
  const [msg, setMsg] = useState("");
  const load = useCallback(async () => setP(await api<Patient>(`/api/patients/${patientId}`)), [patientId]);
  useEffect(() => { load(); }, [load]);
  if (!p) return <div className="drawer">Загрузка карточки…</div>;

  async function complete(itemId: number) {
    const result = window.prompt("Результат (например: ПЦР — РНК не обнаружена; АЛТ 22)") ?? "";
    await post(`/api/plan-items/${itemId}/complete`, { result });
    setMsg("Событие отмечено выполненным, план пересчитан.");
    load();
  }
  async function encounter() {
    const r = await post<{ draft_conclusion: string }>(`/api/patients/${p!.id}/encounters`, { complaints, conclusion: conclusion || null });
    setDraft(r.draft_conclusion);
    setMsg("Приём проведён: визит закрыт, назначен следующий цикл наблюдения по КР.");
    load();
  }
  async function therapy() {
    const regimen = window.prompt("Схема ПВТ", "Софосбувир/Велпатасвир 12 нед");
    if (!regimen) return;
    const end = window.prompt("Дата окончания терапии (ГГГГ-ММ-ДД), пусто — терапия продолжается", "");
    await post(`/api/patients/${p!.id}/therapy`, { regimen, therapy_start: new Date().toISOString().slice(0, 10), therapy_end: end || null });
    setMsg(end ? "Терапия завершена: создан критический контроль УВО-12 (+12 недель)." : "Пациент переведён на терапию.");
    load();
  }
  async function toggleConsent() {
    const r = await post<Patient>(`/api/patients/${p!.id}/consent`, { consent_notifications: !p!.consent_notifications, preferred_channel: p!.preferred_channel });
    setP({ ...p!, consent_notifications: r.consent_notifications });
  }
  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div className="drawer" onClick={(e) => e.stopPropagation()}>
        <button className="close" onClick={onClose}>✕</button>
        <h2>{p.full_name}</h2>
        <div className="muted">{p.diagnosis_code} · {p.nosology} · фиброз {p.fibrosis_stage}{p.cirrhosis ? " · цирроз" : ""}{p.genotype ? ` · генотип ${p.genotype}` : ""}</div>
        <div className="card-meta">
          <span>Статус: <b>{STATUS_LABELS[p.status] ?? p.status}</b></span><ZoneBadge zone={p.zone} />
          <span>СНИЛС: {p.snils ?? "—"}</span><span>Телефон: {p.phone ?? "—"}</span>
          <span>На учёте с {fmtDate(p.enrolled_at)} ({p.enrollment_trigger})</span>
          {p.therapy_regimen && <span>ПВТ: {p.therapy_regimen}</span>}
          {p.svr12_achieved !== null && p.svr12_achieved !== undefined && <span>УВО-12: <b>{p.svr12_achieved ? "достигнут" : "не достигнут"}</b></span>}
        </div>
        <label className="check"><input type="checkbox" checked={p.consent_notifications} onChange={toggleConsent} /> Согласие на уведомления ({p.preferred_channel})</label>

        <h3>Индивидуальный план наблюдения по КР</h3>
        <table className="grid compact">
          <thead><tr><th>Событие</th><th>Срок</th><th>Статус</th><th>Основание</th><th></th></tr></thead>
          <tbody>
            {p.plan.map((i) => (
              <tr key={i.id} className={i.status === "OVERDUE" ? "row-red" : ""}>
                <td>{i.title}<div className="p-sub">{i.kind}{i.result ? ` · результат: ${i.result}` : ""}</div></td>
                <td>{fmtDate(i.due_date)}</td><td>{i.status}</td><td className="rule">{i.rule_ref}</td>
                <td>{i.status !== "DONE" && i.status !== "CANCELLED" && <button onClick={() => complete(i.id)}>Выполнено</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <h3>Провести приём</h3>
        <textarea placeholder="Жалобы / данные осмотра (в проде — голосовой ввод SpeechKit)…" value={complaints} onChange={(e) => setComplaints(e.target.value)} />
        <textarea placeholder="Заключение врача (можно оставить пустым — будет черновик AI-ассистента)…" value={conclusion} onChange={(e) => setConclusion(e.target.value)} />
        <div className="actions">
          <button className="primary" onClick={encounter}>Завершить приём</button>
          <button onClick={therapy}>ПВТ: назначить / завершить</button>
        </div>
        {draft && <div className="draft"><b>Черновик заключения (AI-ассистент):</b><br />{draft}</div>}
        {msg && <div className="ok">{msg}</div>}

        {p.encounters && p.encounters.length > 0 && (
          <>
            <h3>История приёмов</h3>
            {p.encounters.map((e) => (
              <div key={e.id} className="encounter"><b>{fmtDate(e.visit_date)}</b> — {e.conclusion ?? e.draft_conclusion ?? "—"}</div>
            ))}
          </>
        )}
      </div>
    </div>
  );
}

function Tasks({ onOpenPatient }: { onOpenPatient: (id: number) => void }) {
  const [tasks, setTasks] = useState<CareTask[]>([]);
  const load = useCallback(async () => setTasks(await api<CareTask[]>("/api/care/tasks")), []);
  useEffect(() => { load(); }, [load]);
  async function complete(t: CareTask) {
    const outcome = window.prompt("Исход обзвона: WILL_COME | REFUSED | NO_ANSWER | UNREACHABLE", "WILL_COME");
    if (!outcome) return;
    try { await post(`/api/care/tasks/${t.id}/complete`, { outcome, comment: "" }); load(); }
    catch (e) { alert((e as Error).message); }
  }
  return (
    <section>
      <h1>Care Management — задачи обзвона и эскалации</h1>
      <p className="muted">Маршрут эскалации: пациент не пришёл → напоминание → обзвон → уведомление заведующему. Задачи по красной зоне создаёт дневной job.</p>
      <table className="grid">
        <thead><tr><th>Пациент</th><th>Задача</th><th>Приоритет</th><th>Срок</th><th></th></tr></thead>
        <tbody>{tasks.map((t) => (
          <tr key={t.id}>
            <td><button className="link" onClick={() => onOpenPatient(t.patient_id)}>{t.patient_name}</button></td>
            <td>{t.title}<div className="p-sub">{t.kind}</div></td><td>{t.priority}</td><td>{fmtDate(t.due_date)}</td>
            <td><button onClick={() => complete(t)}>Зафиксировать исход</button></td>
          </tr>))}
        </tbody>
      </table>
      {tasks.length === 0 && <p className="muted">Открытых задач нет.</p>}
    </section>
  );
}

function AnalyticsView() {
  const [a, setA] = useState<Analytics | null>(null);
  useEffect(() => { api<Analytics>("/api/analytics/overview").then(setA); }, []);
  if (!a) return <p>Загрузка…</p>;
  const maxNos = Math.max(1, ...Object.values(a.by_nosology));
  return (
    <section>
      <h1>Аналитика — охват, приверженность, УВО</h1>
      <div className="stats">
        <StatCard title="В регистре / активно" value={`${a.registry_total} / ${a.active_total}`} hint="Пациентов с B18.* на диспансерном наблюдении" />
        <StatCard title="Приверженность" value={pct(a.adherence)} hint={`Выполнено ${a.plan_done}, просрочено ${a.plan_overdue}`} accent="#1a9e6b" />
        <StatCard title="Доля УВО-12" value={pct(a.svr_rate)} hint={`Проверено ${a.svr12_checked}, достигнуто ${a.svr12_achieved}`} accent="#7b4fd0" />
        <StatCard title="Красная зона" value={String(a.zones.red)} hint="Требуется эскалация / обзвон" accent="#d93636" />
      </div>
      <h3>По нозологиям</h3>
      {Object.entries(a.by_nosology).map(([k, v]) => (
        <div key={k} className="bar-row"><span>{k}</span><div className="bar"><div style={{ width: `${(v / maxNos) * 100}%` }} /></div><b>{v}</b></div>
      ))}
      <h3>Нагрузка по врачам</h3>
      {Object.entries(a.by_doctor).map(([k, v]) => <p key={k}>{k}: <b>{v}</b> пациентов</p>)}
      <p className="muted">Уровни дашбордов: врач → заведующий/главврач МО → Минздрав РТ (в проде — Yandex DataLens поверх этого API).</p>
    </section>
  );
}

function Notifications() {
  const [items, setItems] = useState<{ id: number; patient_id: number; channel: string; kind: string; text: string; status: string; scheduled_for: string }[]>([]);
  useEffect(() => { api<typeof items>("/api/notifications").then(setItems); }, []);
  return (
    <section>
      <h1>Коммуникации с пациентом — журнал уведомлений</h1>
      <p className="muted">Каналы: СМС / push / Госуслуги. Без согласия пациента уведомления не отправляются (152-ФЗ) — статус SKIPPED_NO_CONSENT.</p>
      <table className="grid">
        <thead><tr><th>Пациент ID</th><th>Тип</th><th>Канал</th><th>Статус</th><th>Текст</th></tr></thead>
        <tbody>{items.map((n) => <tr key={n.id}><td>{n.patient_id}</td><td>{n.kind}</td><td>{n.channel}</td><td>{n.status}</td><td>{n.text}</td></tr>)}</tbody>
      </table>
    </section>
  );
}

function Audit() {
  const [items, setItems] = useState<{ id: number; actor: string; action: string; entity: string; details: string; created_at: string }[]>([]);
  useEffect(() => { api<typeof items>("/api/audit").then(setItems); }, []);
  return (
    <section>
      <h1>Журнал аудита (блок 8)</h1>
      <table className="grid">
        <thead><tr><th>Когда</th><th>Кто</th><th>Действие</th><th>Объект</th><th>Детали</th></tr></thead>
        <tbody>{items.map((x) => <tr key={x.id}><td>{fmtDate(x.created_at)}</td><td>{x.actor}</td><td>{x.action}</td><td>{x.entity}</td><td>{x.details}</td></tr>)}</tbody>
      </table>
    </section>
  );
}
