import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { api } from '../api/endpoints';
import { session } from '../api/client';
import type { Meta, User } from '../api/types';

interface AuthState {
  user: User | null;
  meta: Meta | null;
  ready: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(session.user as User | null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const bootstrap = async () => {
      if (!session.token) {
        setReady(true);
        return;
      }
      try {
        const [me, metaPayload] = await Promise.all([api.me(), api.meta()]);
        if (cancelled) return;
        setUser(me);
        setMeta(metaPayload);
      } catch {
        session.clear();
        setUser(null);
      } finally {
        if (!cancelled) setReady(true);
      }
    };
    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const result = await api.login(email, password);
    session.save(result.token, result.user);
    setUser(result.user);
    setMeta(await api.meta());
  }, []);

  const logout = useCallback(() => {
    session.clear();
    setUser(null);
    window.location.hash = '/login';
  }, []);

  const value = useMemo(() => ({ user, meta, ready, login, logout }), [user, meta, ready, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth 必须在 AuthProvider 内使用');
  return context;
}
