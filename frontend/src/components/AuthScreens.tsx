import { FormEvent, useState } from "react";

import { APIError } from "../api";
import logo from "../assets/fix-logo.jpg";

export function LoadingScreen() {
  return (
    <main className="loading-screen">
      <img className="brand-logo brand-logo--loading" src={logo} alt="MRDN" />
      <div className="spinner" aria-label="Загрузка" />
    </main>
  );
}

interface LoginScreenProps {
  onLogin: (login: string, password: string) => Promise<void>;
  externalError: string | null;
}

export function LoginScreen({ onLogin, externalError }: LoginScreenProps) {
  const [loginValue, setLoginValue] = useState("");
  const [password, setPassword] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(externalError);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSubmitting(true);
    setError(null);
    try {
      await onLogin(loginValue.trim(), password);
    } catch (caughtError) {
      setError(
        caughtError instanceof APIError
          ? "Проверь логин и пароль"
          : "Сервис временно недоступен",
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="login-layout">
      <section className="login-story">
        <div className="brand-lockup">
          <img className="brand-logo" src={logo} alt="MRDN" />
          <span>FIX BY MRDN</span>
        </div>
        <div className="story-copy">
          <p className="eyebrow eyebrow--light">CURATOR WORKSPACE</p>
          <h1>РАЗБОР.<br />СИСТЕМА.<br />ПРОГРЕСС.</h1>
          <p>
            Единое рабочее пространство для проверки торговых работ, обратной связи
            и контроля учебного процесса.
          </p>
        </div>
      </section>
      <section className="login-panel">
        <form className="login-card" onSubmit={handleSubmit}>
          <div>
            <p className="eyebrow">FIX BY MRDN</p>
            <h2>ВХОД В СИСТЕМУ</h2>
            <p className="muted">
              Используйте учётную запись куратора или администратора.
            </p>
          </div>
          <label>
            <span>Логин</span>
            <input
              autoComplete="username"
              value={loginValue}
              onChange={(event) => setLoginValue(event.target.value)}
              placeholder="curator"
              required
            />
          </label>
          <label>
            <span>Пароль</span>
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="••••••••"
              required
            />
          </label>
          {error && <div className="form-error">{error}</div>}
          <button className="primary-button" disabled={isSubmitting}>
            {isSubmitting ? "Входим…" : "Войти в кабинет"}
          </button>
        </form>
      </section>
    </main>
  );
}
