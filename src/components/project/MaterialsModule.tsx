import { useRef, useState } from 'react';
import type { Material, ProjectHighlight } from '../../api/types';
import type { ProjectTabProps } from '../../pages/ProjectWorkspacePage';
import { api } from '../../api/endpoints';
import { MATERIAL_ACCEPT, MATERIAL_TYPE_LABEL, isSupportedFile, materialStatusLabel, materialType } from '../../domain/materials';
import { useToast } from '../Toast';
import { useAuth } from '../../state/AuthContext';
import { HelpTip } from '../HelpTip';
import { SummaryBar } from './SummaryBar';
import { IconEvidence, IconFile } from '../icons';

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
  /** 邮件、聊天记录这类没有文件的材料：粘进来当材料用 */
  const [pasting, setPasting] = useState(false);
  const [pasteKind, setPasteKind] = useState<'email' | 'chat' | 'other'>('email');
  const [pasteText, setPasteText] = useState('');
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

  const PASTE_KIND_LABEL: Record<'email' | 'chat' | 'other', string> = {
    email: '邮件往来',
    chat: '聊天记录',
    other: '文字材料',
  };

  /** 粘贴的文字也走同一个上传接口：存成 txt → 本地解析 → 自动整理需求 */
  const storePasted = async () => {
    const text = pasteText.trim();
    if (!text) return;
    const stamp = new Date().toLocaleDateString('zh-CN').replace(/\//g, '-');
    const file = new File([text], `${PASTE_KIND_LABEL[pasteKind]}-${stamp}.txt`, { type: 'text/plain' });
    setPasting(false);
    setPasteText('');
    await uploadFiles([file]);
  };

  /** 粘贴面板：邮件与聊天记录没有文件，粘正文进来即可当一份材料 */
  const renderPastePanel = () => (
    <section className="paste-panel">
      <label className="field">
        <span className="field__label">这是一份什么材料</span>
        <select
          className="textarea"
          value={pasteKind}
          onChange={(event) => setPasteKind(event.target.value as 'email' | 'chat' | 'other')}
        >
          <option value="email">邮件往来</option>
          <option value="chat">聊天记录</option>
          <option value="other">其他文字材料</option>
        </select>
      </label>
      <label className="field">
        <span className="field__label">正文</span>
        <textarea
          className="textarea"
          rows={6}
          placeholder="把邮件正文或聊天记录粘在这里，例如「收件人：… 主题：工期调整 正文：经研究，一期上线时间调整为 3 个月」"
          value={pasteText}
          onChange={(event) => setPasteText(event.target.value)}
        />
      </label>
      <div className="intake-inline__actions">
        <button
          type="button"
          className="btn btn--primary btn--sm"
          disabled={!pasteText.trim() || uploading}
          onClick={() => void storePasted()}
        >
          存入并分析
        </button>
        <span className="hint hint--inline">
          会存成一份材料并自动整理需求；和文件上传走的是同一条链路
        </span>
      </div>
    </section>
  );

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
  /**
   * 材料里读出来的需求：在材料页只作**事实留档**。
   * 核对与能力判断在需求确认页 —— 那边是动作视图，这边是"材料说了什么"。
   * 顺序保持材料里的抽取次序（确认与否只改标签、不改位置）；
   * 人工新增的需求不是材料事实，所以不进这一块。
   */
  const materialRequirements = requirements.filter((item) => item.source.material_id);

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
            ? `共 ${materials.length} 份 · ${totalPages} 页 · ${requirements.length} 条需求来自这些材料 · 每条都带页码，可点回原文`
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

        {/* 客户材料：收件区在上、已上传清单在下 —— 它们本来就是同一块内容 */}
        <section className="section-open" id="materials-list">
          <header className="section-open__head">
            <div className="section-open__titleline">
              <h3>
                客户材料
                <span className="fact-group__count">{materials.length}</span>
              </h3>
              <HelpTip text="文件拖到这里就能上传；读出来的结果也在这一块，逐条可点回原文核对。" />
            </div>
          </header>

          {/* 收件区：虚线框是"材料从这里进来"的固定地标，两个显式入口（文件 / 文字） */}
          <section className="material-intake">
            <div className="material-intake__hint">
              <IconFile width={18} height={18} />
              <div>
                <strong>把客户材料拖到这里</strong>
                <span className="hint">
                  PDF / Word / Excel / PPT / 图片 / OFD / 文本都能读；邮件、聊天记录这类没有文件的，点「材料输入」粘进来
                </span>
              </div>
            </div>
            <div className="material-intake__actions">
              <button
                type="button"
                className="btn btn--primary btn--sm"
                disabled={uploading}
                onClick={() => fileInput.current?.click()}
              >
                {uploading ? '上传中…' : '上传材料'}
              </button>
              <button
                type="button"
                className="btn btn--secondary btn--sm"
                onClick={() => setPasting((prev) => !prev)}
              >
                {pasting ? '取消输入' : '材料输入'}
              </button>
            </div>
          </section>
          {llm ? (
            <p
              className="hint hint--inline"
              title={llm.endpoint_host ? `模型服务地址：${llm.endpoint_host}` : undefined}
            >
              {llm.external
                ? '分析会把材料内容发送到外部 AI 服务；企业版可切换为内网部署'
                : '分析在本内网完成，材料不出内网'}
            </p>
          ) : null}
          {pasting ? renderPastePanel() : null}

          {/* 已上传的材料：只留「是什么、读得怎么样、去哪看原文」 */}
          {hasMaterials ? (
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
          ) : (
            <p className="empty-inline">还没有材料。把文件拖到上面的虚线框，或者点「上传材料」。</p>
          )}
        </section>

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

      {/* 材料里的需求：材料里读出来的要求，在这里只作事实记录（含还没确认的草稿），
          同一条需求在「需求确认」里被核对、确认、做能力判断 —— 一份事实，两个视图 */}
      {hasMaterials ? (
        <section className="section-open" id="material-requirements">
          <header className="section-open__head">
            <div className="section-open__titleline">
              <h3>
                材料里的需求
                <span className="fact-group__count">{materialRequirements.length}</span>
              </h3>
              <HelpTip text="材料里读出来的要求，在这里只作事实留档、不算数；去「需求确认」逐条核对，确认后才进入能力判断。" />
            </div>
            <div className="section-open__actions">
              <button
                type="button"
                className="link-btn"
                onClick={() => {
                  window.location.hash = `/projects/${project.id}/requirements`;
                }}
              >
                去需求确认
              </button>
            </div>
          </header>

          {materialRequirements.length === 0 ? (
            <p className="empty-inline">
              还没从材料里读出需求。点右上角的「重新提取要点」，或去需求确认页手动新增。
            </p>
          ) : (
            <ul className="highlight-list">
              {materialRequirements.map((item) => (
                <li key={item.id} className="highlight-item">
                  <div className="highlight-item__main">
                    <span className="highlight-item__value">
                      {item.title}
                      <span
                        className={`fact-req__status${
                          item.status === 'confirmed' ? ' fact-req__status--done' : ''
                        }`}
                      >
                        {item.status === 'confirmed' ? '已确认' : '草稿'}
                      </span>
                    </span>
                    {item.detail ? <p className="req-item__detail">{item.detail}</p> : null}
                    <div className="req-brief__meta">
                      <button
                        type="button"
                        className="link-btn req-brief__view"
                        title={[
                          item.source.document_name,
                          item.source.page ? `第 ${item.source.page} 页` : '',
                        ]
                          .filter(Boolean)
                          .join(' · ')}
                        onClick={() => openSource(item.source.material_id, item.source.page)}
                      >
                        <IconEvidence width={13} height={13} />
                        {[
                          materials.length > 1 ? item.source.document_name ?? '' : '',
                          item.source.page ? `第 ${item.source.page} 页` : '',
                        ]
                          .filter(Boolean)
                          .join(' · ') || '来源未标注'}
                      </button>
                      {item.priority === 'high' ? (
                        <span className="hint hint--inline">高优先级</span>
                      ) : null}
                      {item.edited ? (
                        <span className="hint hint--inline" title="人工改过：重新整理时这条会保留">
                          已人工修改
                        </span>
                      ) : null}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      ) : null}

    </div>
  );
}
