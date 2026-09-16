import { useRef, useState } from 'react';
import type { Material, ProjectHighlight } from '../../api/types';
import type { ProjectTabProps } from '../../pages/ProjectWorkspacePage';
import { api } from '../../api/endpoints';
import { MATERIAL_ACCEPT, MATERIAL_TYPE_LABEL, isSupportedFile, materialStatusLabel, materialType } from '../../domain/materials';
import { useToast } from '../Toast';
import { useAuth } from '../../state/AuthContext';
import { HelpTip } from '../HelpTip';
import { SummaryBar } from './SummaryBar';
import { IconEvidence } from '../icons';

function shortDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? ''
    : date.toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' });
}

/**
 * 材料解析：客户材料的读取结果。
 *
 * 材料页是收件的地方：显式上传入口在这里（同时也支持把文件拖到页面任意位置）。
 * 右侧 Agent 只负责对话与提问，不再承担收件台的角色（见 docs/agent-core-design.md）。
 * 这一页放：材料清单（状态、查看原文、失败重试）与项目要点（每条带来源页码，可编辑、可忽略）。
 *
 * 版面原则：一屏只留「收到了什么、读得怎么样、下一步做什么」，
 * 其余解释收进 HelpTip 与「···」菜单。
 */
export function MaterialsModule({ project, refresh, runTask, job, busy }: ProjectTabProps) {
  const toast = useToast();
  const { meta } = useAuth();
  const fileInput = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [draftValue, setDraftValue] = useState('');
  const [savingFacts, setSavingFacts] = useState(false);

  const materials = project.materials ?? [];
  const llm = meta?.integrations?.llm;

  /** 上传交给后端既有的 intake 端点；解析与整理由服务端接着跑 */
  const uploadFiles = async (files: File[]) => {
    const supported = files.filter(isSupportedFile);
    const rejected = files.length - supported.length;
    if (rejected) toast.push(`有 ${rejected} 个文件格式不支持，已跳过`, 'error');
    if (!supported.length) return;
    setUploading(true);
    try {
      for (const file of supported) {
        await api.uploadMaterial(project.id, file);
      }
      toast.push(`已交给 Fitwise：${supported.map((file) => file.name).join('、')}`, 'success');
      refresh();
    } catch (error) {
      toast.push(error instanceof Error ? `上传失败：${error.message}` : '上传失败', 'error');
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = '';
    }
  };

  const requirements = project.requirements ?? [];
  const parsed = materials.filter((item) => item.status === 'parsed');
  const failed = materials.filter((item) => item.status === 'failed');
  const totalPages = materials.reduce((sum, item) => sum + (item.page_count || 0), 0);
  const highlights = project.highlights ?? [];
  const visibleHighlights = highlights.filter((item) => !item.ignored);
  const ignoredCount = highlights.length - visibleHighlights.length;
  /**
   * 要点按内容分类分区：顺序固定（从「这是什么项目」到「交付环境」再到「决策链」），
   * 便于扫读；分区标题已经说明分类，条目上不再重复标签。
   */
  const FACT_LABEL_ORDER = [
    '客户与项目',
    '建设范围',
    '工期口径',
    '关键时间点',
    '交付环境',
    '预算',
    '决策链',
    '其他要点',
  ];
  const factGroups = FACT_LABEL_ORDER.map((label) => ({
    label,
    items: highlights
      .map((item, index) => ({ item, index }))
      .filter(({ item }) => {
        if (item.ignored) return false;
        // 万一出现没见过的标签，归到「其他要点」，不让它静默消失
        const key = FACT_LABEL_ORDER.includes(item.label) ? item.label : '其他要点';
        return key === label;
      }),
  })).filter((group) => group.items.length > 0);
  const hasMaterials = materials.length > 0;
  const requirementCountOf = (materialId: number) =>
    requirements.filter((item) => item.source.material_id === materialId).length;

  const retry = async (material: Material) => {
    try {
      await api.reparseMaterial(material.id);
      toast.push('已重新读取', 'success');
      await refresh();
    } catch (error) {
      toast.push(error instanceof Error ? error.message : '重新读取失败', 'error');
    }
  };

  const remove = async (material: Material) => {
    // 说清会连带删掉什么：草稿需求跟着材料走，已确认的需求是人工基线，必须留住
    const fromThis = requirements.filter((item) => item.source.material_id === material.id);
    const drafts = fromThis.filter((item) => item.status === 'draft').length;
    const kept = fromThis.length - drafts;
    const effect = [
      drafts ? `由它抽取的 ${drafts} 条待确认需求会一起删除。` : '',
      kept ? `已确认的 ${kept} 条需求会保留。` : '',
    ]
      .filter(Boolean)
      .join('');
    if (!window.confirm(`删除「${material.filename}」？${effect || '删除后不再作为判断依据。'}`)) return;
    try {
      await api.deleteMaterial(material.id);
      toast.push('已删除');
      await refresh();
    } catch (error) {
      toast.push(error instanceof Error ? error.message : '删除失败', 'error');
    }
  };

  const openSource = (materialId?: number | null, page?: number | null) => {
    if (!materialId) return;
    window.dispatchEvent(
      new CustomEvent('fitwise:open-assets', { detail: { materialId, page: page ?? 1 } }),
    );
  };

  const saveHighlights = async (next: ProjectHighlight[], message: string) => {
    setSavingFacts(true);
    try {
      await api.updateHighlights(project.id, next);
      toast.push(message, 'success');
      await refresh();
    } catch (error) {
      toast.push(error instanceof Error ? error.message : '保存失败', 'error');
    } finally {
      setSavingFacts(false);
      setEditingIndex(null);
    }
  };

  const materialIdByName = (filename?: string) =>
    materials.find((item) => item.filename === filename)?.id ?? null;

  return (
    <div className="page page--stack">
      {/* 材料页的收件入口：显式按钮（拖拽到页面任意位置同样有效，由右侧 Agent 的全局拖拽处理） */}
      <input
        ref={fileInput}
        type="file"
        multiple
        hidden
        accept={MATERIAL_ACCEPT}
        onChange={(event) => {
          void uploadFiles(Array.from(event.target.files ?? []));
        }}
      />
      {/* 结论条：和另外两个功能页同一套骨架（一句结论 + 概括行 + 数字 + 主动作） */}
      <SummaryBar
        tone={failed.length ? 'warn' : hasMaterials ? 'ok' : 'info'}
        verdict={
          !hasMaterials
            ? '还没有客户材料'
            : failed.length
              ? `${failed.length} 份材料没读出来`
              : `${parsed.length} 份材料都读完了，摘出 ${visibleHighlights.length} 条项目要点`
        }
        sub={
          hasMaterials
            ? `共 ${materials.length} 份 · ${totalPages} 页 · ${requirements.length} 条需求来自这些材料 · 原文由 TextIn 解析`
            : '材料交给右侧 Agent 上传，读出来的结果会出现在这里'
        }
        lines={[
          {
            label: '材料',
            text: hasMaterials
              ? `${materials.length} 份 · ${totalPages} 页 · ${
                  failed.length
                    ? `${failed.length} 份读取失败`
                    : parsed.length < materials.length
                      ? `${materials.length - parsed.length} 份读取中`
                      : '全部已读取'
                }`
              : '还没有材料',
            target: 'materials-list',
          },
          {
            label: '项目要点',
            text: visibleHighlights.length
              ? `${visibleHighlights.length} 条，分 ${factGroups.length} 类${
                  factGroups[0] ? `（${factGroups[0].label}最多：${factGroups[0].items.length} 条）` : ''
                }`
              : '还没有摘出要点',
            target: 'project-facts',
          },
          {
            label: '下一步',
            text: requirements.length
              ? `去需求确认，逐条核对这 ${requirements.length} 条`
              : '先整理出需求，再逐条核对',
            href: `/projects/${project.id}/requirements`,
          },
        ]}
        action={
          hasMaterials
            ? requirements.length
              ? {
                  label: busy ? '处理中…' : '重新提取要点',
                  onClick: () => void runTask(() => api.extractRequirements(project.id), '项目要点提取'),
                  disabled: busy || parsed.length === 0,
                }
              : {
                  label: busy ? '处理中…' : '提取要点',
                  onClick: () => void runTask(() => api.extractRequirements(project.id), '项目要点提取'),
                  disabled: busy || parsed.length === 0,
                }
            : undefined
        }
        secondary={
          // 左侧放本页功能；右侧固定是「去下一页」——三页统一
          hasMaterials
            ? {
                label: '去需求确认',
                onClick: () => {
                  window.location.hash = `/projects/${project.id}/requirements`;
                },
              }
            : undefined
        }
      />

        {/* 材料清单：只留「是什么、读得怎么样、去哪看原文」 */}
        {hasMaterials ? (
          <section className="section-open" id="materials-list">
            <header className="section-open__head">
              <div className="section-open__titleline">
                <h3>
                  客户材料
                  <span className="fact-group__count">{materials.length}</span>
                </h3>
                <HelpTip text="上传入口在这一页；读出来的结果也在这里，逐条可查看原文。" />
              </div>
              <div className="section-open__actions">
                <button
                  type="button"
                  className="link-btn"
                  disabled={uploading}
                  onClick={() => fileInput.current?.click()}
                >
                  {uploading ? '上传中…' : '上传材料'}
                </button>
              </div>
            </header>
            <ul className="asset-list material-list">
            {materials.map((item) => (
              <li
                key={item.id}
                title={`${item.filename} · ${shortDate(item.created_at)} 上传 · ${requirementCountOf(
                  item.id,
                )} 条需求来自这份材料`}
              >
                <span className="asset-tag asset-tag--customer">
                  {MATERIAL_TYPE_LABEL[materialType(item)] ?? '其他材料'}
                </span>
                <span className="asset-list__name">{item.filename}</span>
                <span className="hint hint--inline">
                  {item.page_count ? `${item.page_count} 页 · ` : ''}
                  {materialStatusLabel(item.status)}
                  {item.status === 'failed' && item.parse_error
                    ? `（${item.parse_error.slice(0, 40)}）`
                    : ''}
                </span>
                {item.summary ? (
                  <span className="material-item__summary">{item.summary}</span>
                ) : null}
                {/* 动作行放在条目底部，和需求确认的条目一致 */}
                <span className="section-open__actions material-item__actions">
                  <button type="button" className="link-btn" onClick={() => openSource(item.id, 1)}>
                    <IconEvidence width={13} height={13} />
                    查看原文
                  </button>
                  <details className="card-menu">
                    <summary aria-label="更多操作">···</summary>
                    <div className="card-menu__body">
                      {item.status === 'failed' ? (
                        <button type="button" className="link-btn" onClick={() => void retry(item)}>
                          重新读取
                        </button>
                      ) : null}
                      <button type="button" className="link-btn" onClick={() => void remove(item)}>
                        删除
                      </button>
                    </div>
                  </details>
                </span>
              </li>
            ))}
            </ul>
            {llm ? (
              <p className="hint hint--inline">
                {llm.external
                  ? `分析会把材料内容发送到外部模型服务（${llm.endpoint_host ?? llm.provider}）；企业版可切换为内网模型部署`
                  : `分析在本内网模型上完成（${llm.endpoint_host ?? llm.provider}）`}
              </p>
            ) : null}
          </section>
        ) : (
          <div className="material-empty">
            <p className="hint">
              把客户材料拖到页面任意位置，或者点下面的「选择文件」——招标文件、答疑澄清、纪要、Excel 都行，
              PDF 扫描件也能读。读完后材料与项目要点出现在这里，需求会自动整理到「需求确认」。
            </p>
            <div className="intake-inline__actions">
              <button
                type="button"
                className="btn btn--primary btn--sm"
                disabled={uploading}
                onClick={() => fileInput.current?.click()}
              >
                {uploading ? '上传中…' : '选择文件上传'}
              </button>
              <span className="hint hint--inline">支持 PDF / Word / Excel / PPT / 图片 / OFD / 文本</span>
            </div>
            {llm ? (
              <p className="hint hint--inline">
                {llm.external
                  ? `分析会把材料内容发送到外部模型服务（${llm.endpoint_host ?? llm.provider}）`
                  : `分析在本内网模型上完成（${llm.endpoint_host ?? llm.provider}）`}
                {' · '}企业版可切换为内网模型部署
              </p>
            ) : null}
          </div>
        )}

      {/* 项目要点：只摘事实，不进确认流程 */}
      {hasMaterials ? (
        <section className="section-open" id="project-facts">
          <header className="section-open__head">
            <div className="section-open__titleline">
              <h3>
                项目要点
                <span className="fact-group__count">{visibleHighlights.length}</span>
              </h3>
              <HelpTip text="材料里明确写着的事实，每条都能点回原文核对。" />
            </div>
            <div className="section-open__actions">
              {ignoredCount ? (
                <button
                  type="button"
                  className="link-btn"
                  disabled={savingFacts}
                  onClick={() =>
                    void saveHighlights(
                      highlights.map((item) => ({ ...item, ignored: false })),
                      '已恢复',
                    )
                  }
                >
                  恢复已忽略的 {ignoredCount} 条
                </button>
              ) : null}
            </div>
          </header>

          {job ? (
            <p className="hint hint--inline">
              Fitwise 正在处理 {job.done}/{job.total}
              {job.current ? `：${job.current}` : ''}
            </p>
          ) : null}

          {visibleHighlights.length === 0 ? (
            <p className="empty-inline">
              还没有项目要点，点右上角的「提取要点」。
            </p>
          ) : (
            <div className="fact-groups">
              {factGroups.map((group) => (
                <section key={group.label} className="fact-group">
                  <h4 className="fact-group__head">
                    {group.label}
                    <span className="fact-group__count">{group.items.length}</span>
                  </h4>
                  <ul className="highlight-list">
                    {group.items.map(({ item, index }) => (
                      <li key={`${item.label}-${index}`} className="highlight-item">
                    {editingIndex === index ? (
                      <div className="highlight-item__edit">
                        <input
                          className="textarea"
                          value={draftValue}
                          autoFocus
                          onChange={(event) => setDraftValue(event.target.value)}
                        />
                        <div className="req-item__actions">
                          <button
                            type="button"
                            className="btn btn--primary btn--sm"
                            disabled={!draftValue.trim() || savingFacts}
                            onClick={() =>
                              void saveHighlights(
                                highlights.map((fact, factIndex) =>
                                  factIndex === index
                                    ? { ...fact, value: draftValue.trim(), edited: true }
                                    : fact,
                                ),
                                '已更新',
                              )
                            }
                          >
                            保存
                          </button>
                          <button
                            type="button"
                            className="link-btn"
                            onClick={() => {
                              setEditingIndex(null);
                            }}
                          >
                            取消
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div className="highlight-item__main">
                        <span className="highlight-item__value">{item.value}</span>
                        <div className="req-brief__meta">
                          <button
                            type="button"
                            className="link-btn"
                            title={[
                              item.source_material_name,
                              item.source_page ? `第 ${item.source_page} 页` : '',
                            ]
                              .filter(Boolean)
                              .join(' · ')}
                            onClick={() =>
                              openSource(materialIdByName(item.source_material_name), item.source_page)
                            }
                          >
                            <IconEvidence width={13} height={13} />
                            {[
                              materials.length > 1 ? item.source_material_name ?? '' : '',
                              item.source_page ? `第 ${item.source_page} 页` : '',
                            ]
                              .filter(Boolean)
                              .join(' · ') ||
                              item.source_material_name ||
                              '来源未标注'}
                          </button>
                          {item.edited ? (
                            <span className="asset-tag asset-tag--inferred">人工修正</span>
                          ) : null}
                          <details className="card-menu">
                            <summary aria-label="更多操作">···</summary>
                            <div className="card-menu__body">
                              <button
                                type="button"
                                className="link-btn"
                                onClick={() => {
                                  setEditingIndex(index);
                                  setDraftValue(item.value);
                                }}
                              >
                                编辑
                              </button>
                              <button
                                type="button"
                                className="link-btn"
                                disabled={savingFacts}
                                onClick={() =>
                                  void saveHighlights(
                                    highlights.map((fact, factIndex) =>
                                      factIndex === index ? { ...fact, ignored: true } : fact,
                                    ),
                                    '已忽略',
                                  )
                                }
                              >
                                忽略
                              </button>
                            </div>
                          </details>
                        </div>
                      </div>
                    )}
                      </li>
                    ))}
                  </ul>
                </section>
              ))}
            </div>
          )}
        </section>
      ) : null}

    </div>
  );
}
