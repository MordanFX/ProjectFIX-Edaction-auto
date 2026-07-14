import { FormEvent, useEffect, useMemo, useState } from "react";

import {
  APIError,
  createStaffMember,
  getStaffMembers,
  updateStaffMember,
} from "../api";
import type { StaffCreate, StaffMember, StaffRole, StaffUpdate } from "../types";

const initialForm: StaffCreate = {
  login: "",
  password: "",
  display_name: "",
  role: "curator",
  telegram_user_id: null,
  is_active: true,
};

export function TeamSection() {
  const [members, setMembers] = useState<StaffMember[]>([]);
  const [form, setForm] = useState<StaffCreate>(initialForm);
  const [telegramIdValue, setTelegramIdValue] = useState("");
  const [editing, setEditing] = useState<StaffMember | null>(null);
  const [editForm, setEditForm] = useState<StaffUpdate | null>(null);
  const [editTelegramIdValue, setEditTelegramIdValue] = useState("");
  const [editPasswordValue, setEditPasswordValue] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [updating, setUpdating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const stats = useMemo(
    () => ({
      total: members.length,
      active: members.filter((member) => member.is_active).length,
      linked: members.filter((member) => member.telegram_user_id !== null).length,
      reviewed: members.reduce((sum, member) => sum + member.reviewed_total, 0),
    }),
    [members],
  );

  useEffect(() => {
    void loadMembers();
  }, []);

  async function loadMembers() {
    setLoading(true);
    setError(null);
    try {
      setMembers(await getStaffMembers());
    } catch (caughtError) {
      setError(messageFromError(caughtError, "Не удалось загрузить команду"));
    } finally {
      setLoading(false);
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const telegram_user_id = parseTelegramId(telegramIdValue);
      const created = await createStaffMember({
        ...form,
        login: form.login.trim(),
        display_name: form.display_name.trim(),
        telegram_user_id,
      });
      setMembers((current) => [created, ...current]);
      setForm(initialForm);
      setTelegramIdValue("");
      setNotice("Сотрудник добавлен. Теперь он может войти в панель.");
    } catch (caughtError) {
      setError(messageFromError(caughtError, "Не удалось создать сотрудника"));
    } finally {
      setSaving(false);
    }
  }

  function startEdit(member: StaffMember) {
    setEditing(member);
    setEditForm({
      display_name: member.display_name,
      role: member.role,
      telegram_user_id: member.telegram_user_id,
      is_active: member.is_active,
      password: null,
    });
    setEditTelegramIdValue(member.telegram_user_id?.toString() ?? "");
    setEditPasswordValue("");
    setError(null);
    setNotice(null);
  }

  function cancelEdit() {
    setEditing(null);
    setEditForm(null);
    setEditTelegramIdValue("");
    setEditPasswordValue("");
  }

  async function handleUpdate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editing || !editForm) {
      return;
    }
    setUpdating(true);
    setError(null);
    setNotice(null);
    try {
      const telegram_user_id = parseTelegramId(editTelegramIdValue);
      const updated = await updateStaffMember(editing.id, {
        ...editForm,
        display_name: editForm.display_name.trim(),
        telegram_user_id,
        password: editPasswordValue.trim() || null,
      });
      setMembers((current) =>
        current.map((member) => (member.id === updated.id ? updated : member)),
      );
      cancelEdit();
      setNotice("Данные сотрудника обновлены.");
    } catch (caughtError) {
      setError(messageFromError(caughtError, "Не удалось обновить сотрудника"));
    } finally {
      setUpdating(false);
    }
  }

  return (
    <>
      <section className="page-heading">
        <div>
          <p className="eyebrow">Команда</p>
          <h1>Кураторы и администраторы</h1>
          <p className="muted">
            Отдельные аккаунты для входа в веб-панель, привязка Telegram ID и
            статистика проверки работ.
          </p>
        </div>
        <button className="secondary-button" onClick={loadMembers} disabled={loading}>
          Обновить
        </button>
      </section>

      <section className="metrics-grid team-metrics">
        <article className="metric-card metric-card--accent">
          <span>Всего сотрудников</span>
          <strong>{stats.total}</strong>
          <small>Аккаунты панели</small>
        </article>
        <article className="metric-card">
          <span>Активны</span>
          <strong>{stats.active}</strong>
          <small>Могут войти в кабинет</small>
        </article>
        <article className="metric-card">
          <span>Привязаны к Telegram</span>
          <strong>{stats.linked}</strong>
          <small>Могут работать как кураторы в боте</small>
        </article>
        <article className="metric-card">
          <span>Проверено работ</span>
          <strong>{stats.reviewed}</strong>
          <small>Общая статистика команды</small>
        </article>
      </section>

      <section className="team-layout">
        <div className="team-column">
          <article className="team-panel">
            <header>
              <div>
                <p className="eyebrow">Доступ</p>
                <h2>Добавить сотрудника</h2>
              </div>
            </header>
            <form className="team-form" onSubmit={handleSubmit}>
              <label>
                <span>Имя в панели</span>
                <input
                  required
                  value={form.display_name}
                  onChange={(event) =>
                    setForm({ ...form, display_name: event.target.value })
                  }
                  placeholder="Например: Влад Стрельников"
                />
              </label>
              <label>
                <span>Логин</span>
                <input
                  required
                  minLength={3}
                  value={form.login}
                  onChange={(event) => setForm({ ...form, login: event.target.value })}
                  placeholder="vlad"
                />
              </label>
              <label>
                <span>Пароль</span>
                <input
                  required
                  minLength={8}
                  type="password"
                  value={form.password}
                  onChange={(event) =>
                    setForm({ ...form, password: event.target.value })
                  }
                  placeholder="Минимум 8 символов"
                />
              </label>
              <RoleSelect
                value={form.role}
                onChange={(role) => setForm({ ...form, role })}
              />
              <label>
                <span>Telegram ID</span>
                <input
                  inputMode="numeric"
                  value={telegramIdValue}
                  onChange={(event) => setTelegramIdValue(event.target.value)}
                  placeholder="Можно добавить позже"
                />
              </label>
              <label className="team-checkbox">
                <input
                  type="checkbox"
                  checked={form.is_active}
                  onChange={(event) =>
                    setForm({ ...form, is_active: event.target.checked })
                  }
                />
                <span>Аккаунт активен</span>
              </label>
              {error && <div className="form-error">{error}</div>}
              {notice && <div className="team-notice">{notice}</div>}
              <button className="primary-button" type="submit" disabled={saving}>
                {saving ? "Сохраняю..." : "Создать аккаунт"}
              </button>
            </form>
          </article>

          {editing && editForm && (
            <article className="team-panel team-panel--edit">
              <header>
                <div>
                  <p className="eyebrow">Редактирование</p>
                  <h2>{editing.display_name}</h2>
                </div>
              </header>
              <form className="team-form" onSubmit={handleUpdate}>
                <label>
                  <span>Имя в панели</span>
                  <input
                    required
                    value={editForm.display_name}
                    onChange={(event) =>
                      setEditForm({ ...editForm, display_name: event.target.value })
                    }
                  />
                </label>
                <RoleSelect
                  value={editForm.role}
                  onChange={(role) => setEditForm({ ...editForm, role })}
                />
                <label>
                  <span>Telegram ID</span>
                  <input
                    inputMode="numeric"
                    value={editTelegramIdValue}
                    onChange={(event) => setEditTelegramIdValue(event.target.value)}
                    placeholder="Оставь пустым, если привязки нет"
                  />
                </label>
                <label>
                  <span>Новый пароль</span>
                  <input
                    minLength={8}
                    type="password"
                    value={editPasswordValue}
                    onChange={(event) => setEditPasswordValue(event.target.value)}
                    placeholder="Не заполняй, если пароль не меняется"
                  />
                </label>
                <label className="team-checkbox">
                  <input
                    type="checkbox"
                    checked={editForm.is_active}
                    onChange={(event) =>
                      setEditForm({ ...editForm, is_active: event.target.checked })
                    }
                  />
                  <span>Аккаунт активен</span>
                </label>
                <div className="team-form__actions">
                  <button className="secondary-button" type="button" onClick={cancelEdit}>
                    Отмена
                  </button>
                  <button className="primary-button" type="submit" disabled={updating}>
                    {updating ? "Сохраняю..." : "Сохранить"}
                  </button>
                </div>
              </form>
            </article>
          )}
        </div>

        <article className="team-panel team-panel--list">
          <header>
            <div>
              <p className="eyebrow">Список</p>
              <h2>Текущая команда</h2>
            </div>
            <span>{members.length}</span>
          </header>
          {loading ? (
            <div className="team-empty">Загрузка команды...</div>
          ) : members.length ? (
            <div className="team-list">
              {members.map((member) => (
                <StaffCard key={member.id} member={member} onEdit={startEdit} />
              ))}
            </div>
          ) : (
            <div className="team-empty">Сотрудников пока нет.</div>
          )}
        </article>
      </section>
    </>
  );
}

function RoleSelect({
  value,
  onChange,
}: {
  value: StaffRole;
  onChange: (role: StaffRole) => void;
}) {
  return (
    <label>
      <span>Роль</span>
      <select value={value} onChange={(event) => onChange(event.target.value as StaffRole)}>
        <option value="curator">Куратор</option>
        <option value="admin">Администратор</option>
      </select>
    </label>
  );
}

function StaffCard({
  member,
  onEdit,
}: {
  member: StaffMember;
  onEdit: (member: StaffMember) => void;
}) {
  return (
    <div className="team-card">
      <span className="team-card__avatar">{initials(member.display_name)}</span>
      <div className="team-card__identity">
        <strong>{member.display_name}</strong>
        <small>@{member.login}</small>
      </div>
      <span className={`team-badge team-badge--${member.role}`}>
        {member.role === "admin" ? "Администратор" : "Куратор"}
      </span>
      <dl>
        <div>
          <dt>Telegram ID</dt>
          <dd>{member.telegram_user_id ?? "Не привязан"}</dd>
        </div>
        <div>
          <dt>Статус</dt>
          <dd>{member.is_active ? "Активен" : "Отключён"}</dd>
        </div>
        <div>
          <dt>Закреплено</dt>
          <dd>{member.pending_assigned}</dd>
        </div>
        <div>
          <dt>Проверено</dt>
          <dd>
            {member.reviewed_total} / принято {member.accepted_total} / доработка{" "}
            {member.revision_total}
          </dd>
        </div>
      </dl>
      <footer className="team-card__footer">
        <small>Создан: {formatDate(member.created_at)}</small>
        <button className="secondary-button" type="button" onClick={() => onEdit(member)}>
          Редактировать
        </button>
      </footer>
    </div>
  );
}

function parseTelegramId(value: string): number | null {
  if (!value.trim()) {
    return null;
  }
  const telegramId = Number(value.trim());
  if (!Number.isSafeInteger(telegramId)) {
    throw new APIError("Telegram ID должен быть числом", 422);
  }
  return telegramId;
}

function initials(name: string): string {
  const value = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
  return value || "U";
}

function formatDate(value: string): string {
  return new Date(value).toLocaleDateString("ru-RU");
}

function messageFromError(error: unknown, fallback: string): string {
  return error instanceof APIError ? error.message : fallback;
}
