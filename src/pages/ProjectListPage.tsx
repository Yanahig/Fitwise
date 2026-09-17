import { useEffect, useState } from 'react';
import { api } from '../api/endpoints';
import type { Project } from '../api/types';
import { EmptyState } from '../components/EmptyState';
import { SkeletonRows } from '../components/Skeleton';
import { useToast } from '../components/Toast';
import { IconPlus, IconSearch } from '../components/icons';

/** 项目管理：所有项目的入口，支持搜索、切换与删除 */
export function ProjectListPage({ navigate }: { navigate: (to: string) => void }) {
  const toast = useToast();
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [query, setQuery] = useState('');
  /** 正在删的那一行：只禁用这一行的按钮，别的行照常能开 */
  const [deletingId, setDeletingId] = useState<number | null>(null);

  useEffect(() => {
    api.projects().then(setProjects).catch(() => setProjects([]));
  }, []);

  /**
   * 删除项目：先把它带着什么一起删说清楚，再动手。
   *
   * 这是全站唯一一个"删掉就回不来"的入口（材料、需求、判断、建议、对话都在项目下面），
   * 所以确认框里要报出条数 —— 只说"确定删除吗"会让人不知道代价。
   */
  const remove = async (item: Project) => {
    const counts = item.counts;
    const effect = [
      counts?.materials ? `${counts.materials} 份材料` : '',
      counts?.requirements ? `${counts.requirements} 条需求` : '',
      counts?.matches ? `${counts.matches} 条能力结论` : '',
    ]
      .filter(Boolean)
      .join('、');
    const label = `${item.customer_name || '待识别客户'} · ${item.name || '待识别项目'}`;
    const message =
      `删除「${label}」？\n` +
      (effect ? `${effect}，以及这份售前建议与对话记录都会一起删除。\n` : '') +
      '删除后不可恢复。';
    if (!window.confirm(message)) return;

    setDeletingId(item.id);
    try {
      await api.deleteProject(item.id);
      setProjects((prev) => (prev ?? []).filter((row) => row.id !== item.id));
      // 工作台/登录页会记住"上次打开的项目"，删掉之后不能再往那儿跳
      if (window.localStorage.getItem('fitwise.lastProject') === String(item.id)) {
        window.localStorage.removeItem('fitwise.lastProject');
      }
      // 侧栏的「我的项目」是另一份列表，得让它跟着刷一次
      window.dispatchEvent(new CustomEvent('fitwise:projects-changed'));
      toast.push('已删除项目', 'success');
    } catch (error) {
      toast.push(error instanceof Error ? error.message : '删除失败', 'error');
    } finally {
      setDeletingId(null);
    }
  };

  if (projects === null) {
    return (
      <div className="page page--stack">
        <SkeletonRows count={3} />
      </div>
    );
  }

  const keyword = query.trim().toLowerCase();
  const visible = keyword
    ? projects.filter((item) =>
        `${item.customer_name}${item.name}${item.code}`.toLowerCase().includes(keyword),
      )
    : projects;

  return (
    <div className="page page--stack">
      <section className="section-open">
        <header className="section-open__head">
          <div>
            <h3>项目管理</h3>
          </div>
          <button type="button" className="btn btn--primary btn--sm" onClick={() => navigate('/')}>
            <IconPlus width={14} height={14} />
            新建分析
          </button>
        </header>

        <label className="search-field" style={{ maxWidth: 320 }}>
          <IconSearch width={15} height={15} />
          <input
            className="search-field__input"
            placeholder="搜索客户或项目"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>

        {visible.length === 0 ? (
          <EmptyState
            icon={<IconPlus width={26} height={26} />}
            title={projects.length ? '没有匹配的项目' : '还没有项目'}
            description={
              projects.length
                ? '换个关键词试试。'
                : '去首页新建分析，上传客户材料即可。'
            }
          />
        ) : (
          <div className="list-shell">
            {visible.map((item) => {
              const counts = item.counts;
              return (
                <div key={item.id} className="list-row">
                  <div className="list-row__main">
                    <span className="list-row__title">{item.customer_name || '待识别客户'}</span>
                    <span className="list-row__sub">
                      {item.name || '待识别项目'}
                      {item.owner_name ? ` · 负责人 ${item.owner_name}` : ''}
                    </span>
                  </div>
                  <div className="list-row__metrics">
                    <div className="list-row__metric">
                      <dt>需求</dt>
                      <dd>{counts?.requirements_confirmed ?? 0}</dd>
                    </div>
                    <div className="list-row__metric">
                      <dt>匹配</dt>
                      <dd>{counts?.matches ?? 0}</dd>
                    </div>
                    <div className="list-row__metric">
                      <dt>缺口</dt>
                      <dd>{counts?.matches_none ?? 0}</dd>
                    </div>
                  </div>
                  <div className="list-row__actions">
                    <button
                      type="button"
                      className="btn btn--ghost btn--sm"
                      onClick={() => {
                        window.localStorage.setItem('fitwise.lastProject', String(item.id));
                        navigate(`/projects/${item.id}/materials`);
                      }}
                    >
                      打开
                    </button>
                    <button
                      type="button"
                      className="btn btn--danger btn--sm"
                      disabled={deletingId === item.id}
                      onClick={() => void remove(item)}
                    >
                      {deletingId === item.id ? '删除中…' : '删除'}
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
