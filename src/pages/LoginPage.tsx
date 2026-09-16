import { useState } from 'react';
import { useAuth } from '../state/AuthContext';
import { IconLayers, IconSpark } from '../components/icons';

const ACCOUNTS = [
  { email: 'presales@fitwise.local', label: '售前（张岚）' },
  { email: 'engineer@fitwise.local', label: '技术专家（陈默）' },
  { email: 'admin@fitwise.local', label: '管理员' },
];

export function LoginPage() {
  const { login } = useAuth();
  const [email, setEmail] = useState('presales@fitwise.local');
  const [password, setPassword] = useState('fitwise123');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const signIn = async (nextEmail: string, nextPassword: string) => {
    setBusy(true);
    setError(null);
    try {
      await login(nextEmail, nextPassword);
      window.location.hash = '/';
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : '登录失败');
    } finally {
      setBusy(false);
    }
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    await signIn(email, password);
  };

  return (
    <div className="login">
      <form className="login__card" onSubmit={submit}>
        <div className="login__brand">
          <span className="brand__mark" aria-hidden="true">
            <IconLayers width={22} height={22} />
          </span>
          <div>
            <h1>Fitwise</h1>
            <p>售前决策助手 · 材料解析 × 需求确认 × 售前建议</p>
          </div>
        </div>

        <p className="login__promise">把客户材料交给我，30 分钟出「要什么 · 能不能做 · 下一步」初稿。</p>

        {error ? <p className="inline-error">{error}</p> : null}

        <button
          type="button"
          className="btn btn--primary btn--block btn--lg"
          disabled={busy}
          onClick={() => void signIn('presales@fitwise.local', 'fitwise123')}
        >
          {busy ? '进入中…' : '一键进入演示（售前 张岚）'}
        </button>

        <details className="legacy-details">
          <summary>用其他账号登录</summary>
          <label className="field">
            <span className="field__label">邮箱</span>
            <input
              className="textarea"
              type="email"
              value={email}
              autoComplete="username"
              onChange={(event) => setEmail(event.target.value)}
            />
          </label>
          <label className="field">
            <span className="field__label">密码</span>
            <input
              className="textarea"
              type="password"
              value={password}
              autoComplete="current-password"
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          <button type="submit" className="btn btn--secondary btn--block btn--sm" disabled={busy}>
            登录
          </button>

          <div className="login__accounts">
            <p className="section-subtitle">
              <IconSpark width={14} height={14} /> 演示账号（密码均为 fitwise123）
            </p>
            {ACCOUNTS.map((account) => (
              <button
                key={account.email}
                type="button"
                className="example-chip"
                onClick={() => {
                  setEmail(account.email);
                  setPassword('fitwise123');
                }}
              >
                {account.label}
              </button>
            ))}
          </div>
        </details>
      </form>
    </div>
  );
}
