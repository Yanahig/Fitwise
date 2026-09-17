import type { ReactNode } from 'react';
import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '../state/AuthContext';
import { api } from '../api/endpoints';
import type { Project } from '../api/types';
import { IconLayers, IconPlus, IconSearch } from './icons';

/** 侧栏每个项目只显示一句话状态：卡在哪一步，或者有几项缺口 */
function projectStatus(project: Project): string {
  const counts = project.counts;
  if (!counts || counts.materials === 0) return '还没有材料';
  if (counts.materials_parsed === 0) return '材料读取中';
  if (counts.requirements_confirmed === 0) return `${counts.requirements} 条需求待确认`;
  if (counts.matches === 0) return '待出售前建议';
  if (counts.matches_none > 0) return `${counts.matches_none} 项暂不支持`;
  return '售前建议已出';
}

/**
 * 界面上那行小字：这一份是从哪次构建来的（`__BUILD_ID__` 由 vite define 注入，形如
 * `local@2026-09-17T05:58:12.345Z`）。排查"你看到的还是旧版"最省事的一条 ——
 * 刷新之后时间戳没变，就说明拿到的是缓存或另一个部署，而不是新构建。
 */
function buildStamp(): string {
  const raw = __BUILD_ID__.split('@')[1] ?? '';
  const built = new Date(raw);
  if (Number.isNaN(built.getTime())) return __BUILD_ID__;
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${pad(built.getMonth() + 1)}-${pad(built.getDate())} ${pad(built.getHours())}:${pad(built.getMinutes())}`;
}

export function AppShell({
  path,
  title,
  breadcrumb,
  actions,
  bare = false,
  navigate,
  children,
}: {
  path: string;
  title: string;
  breadcrumb?: { label: string; to?: string }[];
  actions?: ReactNode;
  /** 项目页用统一 Context Bar 承载项目信息，不再重复渲染顶栏 */
  bare?: boolean;
  navigate: (to: string) => void;
  children: ReactNode;
}) {
  const { user, logout } = useAuth();
  const routeProject = /^\/projects\/(\d+)/.exec(path)?.[1];
  const storedProject = window.localStorage.getItem('fitwise.lastProject');
  const [recentProjects, setRecentProjects] = useState<Project[]>([]);
  const [query, setQuery] = useState('');

  const loadProjects = useCallback(() => {
    api
      .projects()
      .then((items) => {
        setRecentProjects(items);
        if (!routeProject && !storedProject && items.length) {
          window.localStorage.setItem('fitwise.lastProject', String(items[0].id));
        }
      })
      .catch(() => setRecentProjects([]));
  }, [routeProject, storedProject]);

  useEffect(loadProjects, [loadProjects, path]);

  /**
   * 别处改了项目集合（现在只有项目管理页的「删除」）要能让侧栏跟上。
   * 光靠 path 变化刷新不够：删完还停在同一页，侧栏会一直挂着那条已经不存在的项目。
   */
  useEffect(() => {
    window.addEventListener('fitwise:projects-changed', loadProjects);
    return () => window.removeEventListener('fitwise:projects-changed', loadProjects);
  }, [loadProjects]);

  const fallbackProject = recentProjects[0] ? String(recentProjects[0].id) : null;
  const projectId = routeProject ?? storedProject ?? fallbackProject;
  const filteredProjects = query.trim()
    ? recentProjects.filter((item) =>
        `${item.customer_name}${item.name}${item.code}`.toLowerCase().includes(query.trim().toLowerCase()),
      )
    : recentProjects;

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        跳到主要内容
      </a>
      <aside className="sidebar">
        <button type="button" className="brand" onClick={() => navigate('/')}>
          <span className="brand__mark" aria-hidden="true">
            <IconLayers width={20} height={20} />
          </span>
          <span className="brand__text">
            <strong>Fitwise</strong>
            <small>AI 售前决策助手</small>
          </span>
        </button>

        <nav className="sidebar__nav" aria-label="项目列表">
          <span className="nav-group__title">我的项目</span>
          {recentProjects.length > 4 ? (
            <label className="search-field sidebar__search">
              <IconSearch width={14} height={14} />
              <input
                className="search-field__input"
                placeholder="搜索客户或项目"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            </label>
          ) : null}
          {recentProjects.length === 0 ? (
            <p className="hint">还没有项目。</p>
          ) : (
            filteredProjects.map((item) => {
              const active = String(item.id) === projectId;
              const counts = item.counts;
              return (
                <button
                  key={item.id}
                  type="button"
                  className={`project-card${active ? ' project-card--active' : ''}`}
                  aria-current={active ? 'page' : undefined}
                  onClick={() => {
                    window.localStorage.setItem('fitwise.lastProject', String(item.id));
                    navigate(`/projects/${item.id}/materials`);
                  }}
                >
                  <span className="project-card__name">{item.customer_name}</span>
                  <span className="project-card__sub">{item.name}</span>
                  <span
                    className={`project-card__status${
                      counts?.matches_none ? ' project-card__status--warn' : ''
                    }`}
                  >
                    {projectStatus(item)}
                  </span>
                </button>
              );
            })
          )}
        </nav>

        <div className="sidebar__bottom">
          <button type="button" className="new-analysis" onClick={() => navigate('/')}>
            <IconPlus width={15} height={15} />
            新建分析
          </button>
          <button type="button" className="sidebar__link" onClick={() => navigate('/projects')}>
            <IconLayers width={15} height={15} />
            项目管理
          </button>
        </div>

        <div className="sidebar__foot">
          {user ? (
            <div className="user-box">
              <div>
                <strong>{user.name}</strong>
                <small>{user.role}</small>
              </div>
              <button type="button" className="link-btn" onClick={logout}>
                退出
              </button>
            </div>
          ) : null}
          {/* 版本戳：刷新之后它还停在旧时间，就说明看到的是缓存 */}
          <p className="sidebar__build" title={__BUILD_ID__}>
            构建 {buildStamp()}
          </p>
        </div>
      </aside>

      <div className="main">
        {bare ? null : (
          <header className="topbar">
            <div>
              {breadcrumb?.length ? (
                <nav className="breadcrumb" aria-label="面包屑">
                  {breadcrumb.map((item, index) => (
                    <span key={`${item.label}-${index}`}>
                      {item.to ? (
                        <button type="button" className="breadcrumb__link" onClick={() => navigate(item.to!)}>
                          {item.label}
                        </button>
                      ) : (
                        <span className="breadcrumb__current">{item.label}</span>
                      )}
                      {index < breadcrumb.length - 1 ? <span className="breadcrumb__sep">/</span> : null}
                    </span>
                  ))}
                </nav>
              ) : null}
              <h1 className="topbar__title">{title}</h1>
            </div>
            <div className="topbar__meta">
              {actions}
            </div>
          </header>
        )}
        <main className="content" id="main-content">
          {children}
        </main>
      </div>
    </div>
  );
}
