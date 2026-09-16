import { useEffect, useState } from 'react';
import type { Match, Project } from '../../api/types';
import { api } from '../../api/endpoints';
import type { CapabilityDoc } from '../../api/types';
import { useToast } from '../Toast';
import { IconClose, IconEvidence } from '../icons';

export type ModuleKey = 'materials' | 'requirements' | 'judgement';

/** 三个功能的中文名：Agent 面板的「正在看」也读这一份，避免各写一套 */
export const MODULE_LABELS: Record<ModuleKey, string> = {
  materials: '材料解析',
  requirements: '需求确认',
  judgement: '售前建议',
};

const MODULES: { key: ModuleKey; label: string }[] = [
  { key: 'materials', label: MODULE_LABELS.materials },
  { key: 'requirements', label: MODULE_LABELS.requirements },
  { key: 'judgement', label: MODULE_LABELS.judgement },
];

/**
 * 三个模块共用的项目信息栏：项目名 + 模块切换 + 一句话状态 + 材料与依据入口。
 * 这里只放「现在什么情况」，分数与依据分别在售前建议页和证据抽屉里。
 */
export function ProjectContextBar({
  project,
  matches,
  active,
  onSwitch,
  onRenamed,
}: {
  project: Project;
  matches: Match[];
  active: ModuleKey;
  onSwitch: (key: ModuleKey) => void;
  /** 改名后让工作台重新拉一次项目（名称会出现在面包屑与各页文案里） */
  onRenamed?: () => Promise<void> | void;
}) {
  const toast = useToast();
  const [assetsOpen, setAssetsOpen] = useState(false);
  const [assetsTarget, setAssetsTarget] = useState<{ materialId?: number | null; page?: number | null }>({});
  /** 项目栏内联改名：AI 识别的名字可能不完美，这里就地纠正 */
  const [renaming, setRenaming] = useState(false);
  const [savingName, setSavingName] = useState(false);
  const [draftName, setDraftName] = useState({ customer: '', project: '' });

  const startRename = () => {
    setDraftName({ customer: project.customer_name ?? '', project: project.name ?? '' });
    setRenaming(true);
  };

  const saveRename = async () => {
    const customerName = draftName.customer.trim();
    const projectName = draftName.project.trim();
    if (!projectName) {
      toast.push('项目名称不能为空', 'error');
      return;
    }
    setSavingName(true);
    try {
      if (customerName && customerName !== (project.customer_name ?? '')) {
        await api.updateCustomer(project.customer_id, { name: customerName });
      }
      if (projectName !== (project.name ?? '')) {
        await api.updateProject(project.id, { name: projectName });
      }
      await onRenamed?.();
      setRenaming(false);
      toast.push('已更新名称', 'success');
    } catch (error) {
      toast.push(error instanceof Error ? error.message : '改名失败', 'error');
    } finally {
      setSavingName(false);
    }
  };

  // 任何 AI 判断里的「查看原文」都会广播这个事件，直接定位到材料的那一页
  useEffect(() => {
    const openAssets = (event: Event) => {
      const detail = (event as CustomEvent).detail ?? {};
      setAssetsTarget({ materialId: detail.materialId ?? null, page: detail.page ?? null });
      setAssetsOpen(true);
    };
    window.addEventListener('fitwise:open-assets', openAssets);
    return () => window.removeEventListener('fitwise:open-assets', openAssets);
  }, []);
  const moduleCounts: Record<ModuleKey, number> = {
    materials: project.materials?.length ?? 0,
    requirements: project.requirements?.length ?? 0,
    judgement: matches.length,
  };

  return (
    <>
      <header className="context-bar">
        <div className="context-bar__top">
          <div>
            {renaming ? (
              <div className="rename-row">
                <label className="field">
                  <span className="field__label">客户名称</span>
                  <input
                    className="textarea"
                    value={draftName.customer}
                    placeholder="待识别客户"
                    onChange={(event) => setDraftName({ ...draftName, customer: event.target.value })}
                  />
                </label>
                <label className="field">
                  <span className="field__label">项目名称</span>
                  <input
                    className="textarea"
                    value={draftName.project}
                    placeholder="待识别项目"
                    onChange={(event) => setDraftName({ ...draftName, project: event.target.value })}
                  />
                </label>
                <div className="section-open__actions">
                  <button
                    type="button"
                    className="btn btn--ghost btn--sm"
                    disabled={savingName}
                    onClick={() => setRenaming(false)}
                  >
                    取消
                  </button>
                  <button
                    type="button"
                    className="btn btn--primary btn--sm"
                    disabled={savingName}
                    onClick={() => void saveRename()}
                  >
                    {savingName ? '保存中…' : '保存'}
                  </button>
                </div>
              </div>
            ) : (
              <h1 className="context-bar__title">
                {project.customer_name || '待识别客户'} · {project.name || '待识别项目'}
                <button type="button" className="link-btn context-bar__rename" onClick={startRename}>
                  改名
                </button>
              </h1>
            )}
            {/* 项目状态常驻在右侧 Agent 面板，这里不再重复一遍 */}
          </div>
          <button type="button" className="btn btn--ghost btn--sm" onClick={() => setAssetsOpen(true)}>
            <IconEvidence width={14} height={14} />
            材料与依据
          </button>
        </div>
        {/* 这里原本是「项目信息：时间线 + 决策链」，已删：
            时间线的留痕作用被对话里的回执卡与批准记录取代；决策链来自客户档案联系人，
            AI 既不读也不写，在演示里还会与材料里的「决策链」要点打架。
            联系人仍在客户档案页，历史仍在工作台最近动态。 */}

        <nav className="context-bar__tabs" aria-label="分析模块">
          {MODULES.map((module) => (
            <button
              key={module.key}
              type="button"
              className={`context-tab${active === module.key ? ' context-tab--active' : ''}`}
              aria-current={active === module.key ? 'page' : undefined}
              onClick={() => onSwitch(module.key)}
            >
              {module.label}
              {moduleCounts[module.key] > 0 ? (
                <span className="context-tab__count">{moduleCounts[module.key]}</span>
              ) : null}
            </button>
          ))}
        </nav>
      </header>

      {assetsOpen ? (
        <AssetsDrawer
          project={project}
          target={assetsTarget}
          onClose={() => {
            setAssetsOpen(false);
            setAssetsTarget({});
          }}
        />
      ) : null}
    </>
  );
}

/** 材料与依据：不是第四个功能，是所有结论的证据层 */
function AssetsDrawer({
  project,
  target,
  onClose,
}: {
  project: Project;
  target: { materialId?: number | null; page?: number | null };
  onClose: () => void;
}) {
  const [docs, setDocs] = useState<CapabilityDoc[] | null>(null);
  const [caseCount, setCaseCount] = useState<number | null>(null);
  const [pageText, setPageText] = useState<{ file: string; page: number; text: string } | null>(null);
  const materials = project.materials ?? [];

  useEffect(() => {
    if (!target.materialId) return;
    let cancelled = false;
    void api
      .materialPreview(target.materialId, target.page ?? undefined)
      .then((data) => {
        if (cancelled) return;
        setPageText({
          file: data.material.filename,
          page: target.page ?? data.chunks[0]?.page ?? 1,
          text: data.chunks.map((chunk) => chunk.text).join('\n\n'),
        });
      })
      .catch(() => setPageText(null));
    return () => {
      cancelled = true;
    };
  }, [target.materialId, target.page]);

  if (docs === null) {
    void api.knowledgeDocs().then(setDocs);
    void api.knowledgeCases().then((items) => setCaseCount(items.length));
  }

  return (
    <div className="drawer" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="drawer__panel" onClick={(event) => event.stopPropagation()}>
        <header className="drawer__head">
          <div>
            <h4>材料与依据</h4>
            <p className="cell-sub">所有结论的来源，可逐条核对</p>
          </div>
          <button type="button" className="btn btn--ghost btn--sm" onClick={onClose}>
            <IconClose width={14} height={14} />
            关闭
          </button>
        </header>
        <div className="drawer__body">
          {pageText ? (
            <section className="source-view">
              <h5 className="asset-group">
                正在查看原文：{pageText.file} · 第 {pageText.page} 页
              </h5>
              <blockquote className="source-view__text">{pageText.text.slice(0, 1200)}</blockquote>
            </section>
          ) : null}
          <section>
            <h5 className="asset-group">客户材料（{materials.length}）</h5>
            {materials.length === 0 ? (
              <p className="hint">还没有上传客户材料。</p>
            ) : (
              <ul className="asset-list">
                {materials.map((item) => (
                  <li key={item.id}>
                    <span className="asset-tag asset-tag--customer">客户材料</span>
                    <span className="asset-list__name">{item.filename}</span>
                    <span className="hint hint--inline">
                      {item.page_count ? `${item.page_count} 页 · ` : ''}
                      {item.status === 'parsed' ? '已读取' : item.status === 'failed' ? '读取失败' : '处理中'}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section>
            <h5 className="asset-group">
              企业知识（{(docs?.length ?? 0) + (caseCount ? caseCount : 0)} 份）
            </h5>
            <ul className="asset-list">
              {(docs ?? []).map((doc) => (
                <li key={doc.id}>
                  <span className="asset-tag asset-tag--knowledge">企业知识</span>
                  <span className="asset-list__name">{doc.title}</span>
                  <span className="hint hint--inline">{doc.doc_type}</span>
                </li>
              ))}
              {caseCount ? (
                <li>
                  <span className="asset-tag asset-tag--knowledge">企业知识</span>
                  <span className="asset-list__name">历史成功案例 {caseCount} 个</span>
                </li>
              ) : null}
            </ul>
          </section>
        </div>
      </div>
    </div>
  );
}
