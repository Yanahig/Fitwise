import { useEffect } from 'react';
import { AppShell } from './components/AppShell';
import { DashboardPage } from './pages/DashboardPage';
import { LoginPage } from './pages/LoginPage';
import { ProjectWorkspacePage } from './pages/ProjectWorkspacePage';
import { ProjectListPage } from './pages/ProjectListPage';
import { useHashRoute } from './router/useHashRoute';
import { AuthProvider, useAuth } from './state/AuthContext';
import { ToastProvider } from './components/Toast';

function Routes() {
  const { path, segments, navigate } = useHashRoute();
  const { user, ready } = useAuth();

  useEffect(() => {
    if (ready && !user && path !== '/login') {
      window.location.hash = '/login';
    }
  }, [ready, user, path]);

  if (!ready) {
    return (
      <div className="splash">
        <div className="splash__box">
          <strong>Fitwise</strong>
          <span className="muted">正在加载工作台…</span>
        </div>
      </div>
    );
  }

  if (!user) return <LoginPage />;

  if (segments[0] === 'projects' && segments[1]) {
    const projectId = Number(segments[1]);
    const tab = segments[2] ?? 'overview';
    return (
      <AppShell
        path={path}
        navigate={navigate}
        title="项目"
        bare
      >
        <ProjectWorkspacePage projectId={projectId} tab={tab} navigate={navigate} />
      </AppShell>
    );
  }

  if (segments[0] === 'projects') {
    return (
      <AppShell path={path} navigate={navigate} title="项目管理">
        <ProjectListPage navigate={navigate} />
      </AppShell>
    );
  }

  return (
    <AppShell path={path} navigate={navigate} title="工作台">
      <DashboardPage navigate={navigate} />
    </AppShell>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <ToastProvider>
        <Routes />
      </ToastProvider>
    </AuthProvider>
  );
}
