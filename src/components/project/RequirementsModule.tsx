import { useState } from 'react';
import type { Match, Priority, Requirement } from '../../api/types';
import type { ProjectTabProps } from '../../pages/ProjectWorkspacePage';
import { api, pollJob } from '../../api/endpoints';
import { summarizeOpenQuestion } from '../../domain/openQuestions';
import { RISK_LEVEL_LABEL, risksForMatch } from '../../domain/risk';
import { PRIORITY_TAG, countByStatus } from '../../domain/status';
import { StatusBadge } from '../badges';
import { MatchDetail } from './MatchDetail';
import { SummaryBar } from './SummaryBar';
import { useToast } from '../Toast';
import { HelpTip } from '../HelpTip';
import {
  IconChevronDown,
  IconEvidence,
  IconPlus,
  IconSpark,
} from '../icons';

const CATEGORIES = ['部署', '产品能力', '技术', '合规', '规模', '服务'];

/**
 * 需求确认：把客户要什么变成一份可核对的清单，并在这里把「能不能做」一条条判掉。
 *
 * 一条主线：点「确认」= 这条需求进基线 + 立刻做能力判断，结论与风险原地长在这张卡上。
 * 还没有定论的事（要问客户、要问内部、要同步销售）统一在售前建议页 ——
 * 这一页只回答"客户要什么、这条我们能不能做"。
 */
export function RequirementsModule({
  project,
  matches,
  refresh,
  runTask,
  busy,
}: ProjectTabProps & { matches: Match[] }) {
  const [editingId, setEditingId] = useState<number | null>(null);
  const [draft, setDraft] = useState<Partial<Requirement>>({});
  const [showAdd, setShowAdd] = useState(false);
  const [confirming, setConfirming] = useState(false);
  /** 正在判断的需求：卡片上要先说"我在判"，别让人以为点漏了 */
  const [judging, setJudging] = useState<number[]>([]);
  /** 展开了依据详情的需求 */
  const [openDetail, setOpenDetail] = useState<number[]>([]);
  const [newRequirement, setNewRequirement] = useState<{
    title: string;
    detail: string;
    category: string;
    priority: Priority;
  }>({ title: '', detail: '', category: '产品能力', priority: 'medium' });
  const toast = useToast();

  const requirements = project.requirements ?? [];
  const confirmed = requirements.filter((item) => item.status === 'confirmed');
  const inferred = requirements.filter((item) => item.created_by_ai && item.status !== 'confirmed');
  const materials = project.materials ?? [];
  const parsedMaterials = materials.filter((item) => item.status === 'parsed');
  const questions = project.open_questions ?? [];
  const judgementQuestions = questions.filter((item) => summarizeOpenQuestion(item).affectsJudgement);
  const customerQuestions = questions.filter((item) => (item.owner || '客户') !== '内部').length;
  const internalQuestions = questions.length - customerQuestions;
  const matchByRequirement = new Map(matches.map((item) => [item.requirement_id, item]));
  const solutionRisks = project.solution?.risks ?? [];
  /** 只有一份材料时不需要在每条需求上重复文件名，页码才是要找的东西 */
  const showSourceDocName = materials.length > 1;
  const highPriority = requirements.filter((item) => item.priority === 'high').length;
  /**
   * 能力判断的分档分布：这一句从售前建议页搬过来 ——
   * 结论本来就长在这一页的卡片上，统计也该跟着结论走。
   * 只列有的档，顺序是「越靠前越需要人管」：待补依据 → 暂不支持 → 部分支持 → 完全支持。
   */
  const statusCounts = countByStatus(matches.map((item) => item.status));
  const statusText = matches.length
    ? [
        statusCounts.unknown ? `待补依据 ${statusCounts.unknown}` : '',
        statusCounts.none ? `暂不支持 ${statusCounts.none}` : '',
        statusCounts.partial ? `部分支持 ${statusCounts.partial}` : '',
        statusCounts.full ? `完全支持 ${statusCounts.full}` : '',
      ]
        .filter(Boolean)
        .join(' · ')
    : '确认后自动判断';
  /**
   * 顺序就是需求自己的次序（后端按抽取顺序给）。
   *
   * 不做「草稿在前、已确认在后」的分组：点「确认」之后那一条要留在原位 ——
   * 一确认就跳到列表最下方，人会当场找不到自己刚点的那条，
   * 尤其是「改一条、看一眼、再改下一条」的时候。
   */
  const orderedRequirements = requirements;
  /** 第一条还没确认的需求：结论条上的「待确认」落到它上面 */
  const firstDraftId = requirements.find((item) => item.status !== 'confirmed')?.id;
  const openJudgement = () => {
    window.location.hash = `/projects/${project.id}/judgement`;
  };
  const canSeeAdvice = requirements.length > 0;

  const markJudging = (id: number, on: boolean) =>
    setJudging((prev) =>
      on ? (prev.includes(id) ? prev : [...prev, id]) : prev.filter((item) => item !== id),
    );

  const toggleDetail = (id: number) =>
    setOpenDetail((prev) => (prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]));

  /**
   * 单条确认 = 进基线 + 立刻判断。
   * 判断在服务端跑，确认接口会返回那个任务；这里跟着它走，跑完原地刷新出结论。
   */
  const confirmOne = async (id: number) => {
    markJudging(id, true);
    try {
      const result = await api.confirmRequirements(project.id, [id]);
      await refresh();
      if (!result.job_id) {
        toast.push('已确认', 'success');
        return;
      }
      const finished = await pollJob(result.job_id);
      await refresh();
      if (finished.status === 'failed') {
        toast.push(finished.error ? `判断失败：${finished.error}` : '判断失败', 'error');
      } else {
        toast.push('已确认，判断结果就在卡片上', 'success');
      }
    } catch (error) {
      toast.push(error instanceof Error ? error.message : '确认失败', 'error');
    } finally {
      markJudging(id, false);
    }
  };

  const confirmAll = async () => {
    setConfirming(true);
    try {
      const result = await api.confirmRequirements(project.id);
      await refresh();
      if (result.job_id) {
        toast.push(`已确认 ${result.confirmed} 条，正在判断`, 'success');
        await pollJob(result.job_id);
        await refresh();
        toast.push('判断完成，结果在每条需求上', 'success');
      } else {
        toast.push(`已确认 ${result.confirmed} 条需求`, 'success');
      }
    } catch (error) {
      toast.push(error instanceof Error ? error.message : '确认失败', 'error');
    } finally {
      setConfirming(false);
    }
  };

  /** 早先确认过、但还没出结论的需求：补一次判断，不用整批重跑 */
  const judgeOne = async (id: number) => {
    markJudging(id, true);
    try {
      await runTask(() => api.runMatching(project.id, [id]), '能力判断');
    } finally {
      markJudging(id, false);
    }
  };

  const removeRequirement = async (id: number) => {
    await api.deleteRequirement(id);
    await refresh();
    toast.push('已移除');
  };

  const saveEdit = async () => {
    if (editingId === null) return;
    const target = requirements.find((item) => item.id === editingId);
    await api.updateRequirement(editingId, draft);
    setEditingId(null);
    setDraft({});
    await refresh();
    toast.push('已更新', 'success');
    // 内容改了，旧结论就过期了：已确认的需求自动重跑这一条，不让卡片继续挂着上一版结论
    if (target?.status === 'confirmed') {
      markJudging(editingId, true);
      try {
        await runTask(() => api.runMatching(project.id, [editingId]), '能力判断');
      } finally {
        markJudging(editingId, false);
      }
    }
  };

  const addRequirement = async () => {
    await api.createRequirement(project.id, newRequirement);
    setNewRequirement({ title: '', detail: '', category: '产品能力', priority: 'medium' });
    setShowAdd(false);
    await refresh();
    toast.push('已添加', 'success');
  };

  const renderRequirement = (item: Requirement, tone: 'confirmed' | 'draft', anchorId?: string) => {
    const match = matchByRequirement.get(item.id);
    const evidenceCount = (match?.capability_doc_ids.length ?? 0) + 1;
    const risks = match ? risksForMatch(match, solutionRisks) : [];
    const isJudging = judging.includes(item.id);
    const detailOpen = openDetail.includes(item.id);

    if (editingId === item.id) {
      return (
        <li key={item.id} className="req-item req-item--editing">
          <div className="edit-stack">
            <input
              className="textarea"
              value={draft.title ?? item.title}
              onChange={(event) => setDraft({ ...draft, title: event.target.value })}
            />
            <textarea
              className="textarea"
              rows={2}
              value={draft.detail ?? item.detail}
              onChange={(event) => setDraft({ ...draft, detail: event.target.value })}
            />
            <div className="create-form__grid">
              <select
                className="textarea"
                value={draft.category ?? item.category}
                onChange={(event) => setDraft({ ...draft, category: event.target.value })}
              >
                {CATEGORIES.map((category) => (
                  <option key={category}>{category}</option>
                ))}
              </select>
              <select
                className="textarea"
                value={draft.priority ?? item.priority}
                onChange={(event) =>
                  setDraft({ ...draft, priority: event.target.value as Requirement['priority'] })
                }
              >
                <option value="high">高优先级</option>
                <option value="medium">中优先级</option>
                <option value="low">低优先级</option>
              </select>
            </div>
            <div className="req-item__actions">
              <button type="button" className="btn btn--primary btn--sm" onClick={() => void saveEdit()}>
                保存
              </button>
              <button
                type="button"
                className="link-btn"
                onClick={() => {
                  setEditingId(null);
                  setDraft({});
                }}
              >
                取消
              </button>
            </div>
          </div>
        </li>
      );
    }

    return (
      <li
        key={item.id}
        id={`requirement-${item.id}`}
        className={`req-item${tone === 'draft' ? ' req-item--draft' : ''}`}
      >
        {/* 第一条草稿的锚点：结论条上的「待确认」点一下就落到这里 */}
        {anchorId ? <span id={anchorId} className="anchor-mark" aria-hidden="true" /> : null}
        <span className={`req-brief__p req-brief__p--${item.priority}`}>
          {PRIORITY_TAG[item.priority] ?? 'P1'}
        </span>
        <div className="req-brief__main">
          <span className="req-brief__title">
            {item.title}
            {/* 状态就在标题上：这份清单只按"草稿/已进基线"区分 */}
            {tone === 'draft' ? <span className="req-brief__draft">草稿</span> : null}
          </span>
          {item.detail ? (
            <p className="req-item__detail" title={item.detail}>
              {item.detail}
            </p>
          ) : null}
          <div className="req-brief__meta">
            <span className="hint hint--inline">依据 {evidenceCount} 条</span>
            <button
              type="button"
              className="link-btn req-brief__view"
              title={[
                item.source.document_name,
                item.source.page ? `第 ${item.source.page} 页` : '',
              ]
                .filter(Boolean)
                .join(' · ')}
              onClick={() =>
                window.dispatchEvent(
                  new CustomEvent('fitwise:open-assets', {
                    detail: { materialId: item.source.material_id, page: item.source.page },
                  }),
                )
              }
            >
              <IconEvidence width={13} height={13} />
              {[
                showSourceDocName && item.source.document_name ? item.source.document_name : '',
                item.source.page ? `第 ${item.source.page} 页` : '',
              ]
                .filter(Boolean)
                .join(' · ') || '人工录入'}
            </button>
            {item.edited ? (
              <span className="hint hint--inline" title="人工改过内容：重新整理需求时这条会保留">
                已人工修改
              </span>
            ) : null}
          </div>

          {/* 结论区：确认之后原地出结果 —— 支持情况 + 风险情况，依据在同一张卡里展开 */}
          {match ? (
            <div className={`req-result req-result--${match.status}`}>
              <div className="req-result__head">
                <StatusBadge status={match.status} size="sm" />
                <span className="req-result__headline">{match.headline}</span>
                <button
                  type="button"
                  className="link-btn req-result__more"
                  aria-expanded={detailOpen}
                  onClick={() => toggleDetail(item.id)}
                >
                  {detailOpen ? '收起依据' : '依据与详情'}
                  <IconChevronDown
                    width={15}
                    height={15}
                    className={`basis-cell__chevron${detailOpen ? ' basis-cell__chevron--open' : ''}`}
                  />
                </button>
              </div>
              {risks.length ? (
                <ul className="req-result__risks">
                  {risks.map((risk) => (
                    <li key={risk.title} className={`req-result__risk req-result__risk--${risk.level}`}>
                      <span className={`entry__risk-tag entry__risk-tag--${risk.level}`}>
                        {RISK_LEVEL_LABEL[risk.level]}风险
                      </span>
                      <span className="req-result__risk-title">{risk.title}</span>
                      {risk.mitigation ? (
                        <span className="req-result__risk-fix">建议应对：{risk.mitigation}</span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              ) : null}
              {detailOpen ? (
                <div className="req-result__detail">
                  <MatchDetail project={project} match={match} onReviewed={refresh} />
                </div>
              ) : null}
            </div>
          ) : isJudging ? (
            <p className="req-result req-result--pending">正在判断这条需求能不能做…</p>
          ) : tone === 'confirmed' ? (
            <p className="hint hint--inline req-result__missing">
              这条还没有判断结论 ·{' '}
              <button type="button" className="link-btn" onClick={() => void judgeOne(item.id)}>
                补一次判断
              </button>
            </p>
          ) : null}

          <div className="req-item__actions">
            {tone === 'draft' ? (
              <button
                type="button"
                className="btn btn--primary btn--sm"
                disabled={isJudging}
                onClick={() => void confirmOne(item.id)}
              >
                {isJudging ? '判断中…' : '确认'}
              </button>
            ) : null}
            <details className="card-menu">
              <summary aria-label="更多操作">···</summary>
              <div className="card-menu__body">
                <button
                  type="button"
                  className="link-btn"
                  onClick={() => {
                    setEditingId(item.id);
                    setDraft({});
                  }}
                >
                  编辑
                </button>
                <button type="button" className="link-btn" onClick={() => void removeRequirement(item.id)}>
                  删除
                </button>
              </div>
            </details>
          </div>
        </div>
      </li>
    );
  };

  return (
    <div className="page page--stack">
      {/* 结论条：和另外两个功能页同一套骨架（一句结论 + 概括行 + 数字 + 主动作） */}
      <SummaryBar
        tone={inferred.length ? 'warn' : confirmed.length ? 'ok' : 'info'}
        verdict={
          !requirements.length
            ? '还没有整理出需求'
            : inferred.length
              ? `${confirmed.length} 条已确认，${inferred.length} 条等你确认`
              : `${requirements.length} 条需求已全部确认`
        }
        sub={`共 ${requirements.length} 项 · 已确认 ${confirmed.length} · 已出结论 ${matches.length} · 来自 ${materials.length} 份客户材料`}
        lines={[
          {
            label: '需求',
            text: `${requirements.length} 条（高优先级 ${highPriority} 条）`,
            target: 'requirements-list',
          },
          {
            label: '能力判断',
            text: statusText,
            target: 'requirements-list',
          },
          {
            label: '待澄清',
            // 问题池搬去售前建议页：这一句是入口，点一下就过去
            text: questions.length
              ? `${questions.length} 处（问客户 ${customerQuestions} · 内部 ${internalQuestions}），在售前建议`
              : '暂时没有待澄清问题',
            href: `/projects/${project.id}/judgement`,
          },
        ]}
        action={
          inferred.length
            ? {
                label: confirming ? '确认中…' : `全部确认（${inferred.length}）`,
                onClick: () => void confirmAll(),
                disabled: confirming,
              }
            : undefined
        }
        // 左边永远是本页功能（全部确认），右边永远是「去下一段」——没有待确认时左侧就空着
        secondary={canSeeAdvice ? { label: '查看建议', onClick: openJudgement } : undefined}
      />

      {materials.length === 0 ? (
        <section className="intake-inline">
          <header className="intake-inline__head">
            <h3>还没有客户材料</h3>
            <p className="hint">
              去「材料解析」上传客户材料，Fitwise 会自动整理成这份需求清单；你只需要逐条确认。
            </p>
          </header>
          <div className="intake-inline__actions">
            <button
              type="button"
              className="btn btn--secondary btn--sm"
              onClick={() => {
                window.location.hash = `/projects/${project.id}/materials`;
              }}
            >
              去材料解析
            </button>
          </div>
        </section>
      ) : null}

      <div className="req-columns">
        {/* 一份清单：不按来源分家，也不按状态重排 —— 确认后原地变基线，位置不动 */}
        <section className="section-open" id="requirements-list">
          <header className="section-open__head">
            <div className="section-open__titleline">
              <h3>
                需求
                <span className="fact-group__count">{requirements.length}</span>
              </h3>
              <HelpTip text="客户材料里读出来的要求都在这一份清单里。带「草稿」标记的还没确认；点「确认」后这条进基线，并且立刻对着企业内部资料判断能不能做 —— 结论、风险与依据都留在这一张卡上。" />
            </div>
            <div className="section-open__actions">
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                disabled={busy || parsedMaterials.length === 0}
                onClick={() => void runTask(() => api.extractRequirements(project.id), '需求整理')}
              >
                <IconSpark width={14} height={14} />
                {busy ? '整理中…' : '重新整理需求'}
              </button>
              <button type="button" className="link-btn" onClick={() => setShowAdd((prev) => !prev)}>
                <IconPlus width={13} height={13} />
                手动新增
              </button>
            </div>
          </header>

          {showAdd ? (
            <div className="create-form">
              <div className="create-form__grid">
                <label className="field">
                  <span className="field__label">需求标题 *</span>
                  <input
                    className="textarea"
                    value={newRequirement.title}
                    onChange={(event) => setNewRequirement({ ...newRequirement, title: event.target.value })}
                  />
                </label>
                <label className="field">
                  <span className="field__label">分类</span>
                  <select
                    className="textarea"
                    value={newRequirement.category}
                    onChange={(event) =>
                      setNewRequirement({ ...newRequirement, category: event.target.value })
                    }
                  >
                    {CATEGORIES.map((category) => (
                      <option key={category}>{category}</option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span className="field__label">优先级</span>
                  <select
                    className="textarea"
                    value={newRequirement.priority}
                    onChange={(event) =>
                      setNewRequirement({ ...newRequirement, priority: event.target.value as Priority })
                    }
                  >
                    <option value="high">高</option>
                    <option value="medium">中</option>
                    <option value="low">低</option>
                  </select>
                </label>
              </div>
              <label className="field">
                <span className="field__label">需求描述</span>
                <textarea
                  className="textarea"
                  rows={2}
                  value={newRequirement.detail}
                  onChange={(event) => setNewRequirement({ ...newRequirement, detail: event.target.value })}
                />
              </label>
              <div className="mode-panel__actions">
                <button
                  type="button"
                  className="btn btn--primary btn--sm"
                  disabled={!newRequirement.title.trim()}
                  onClick={() => void addRequirement()}
                >
                  保存
                </button>
                <span className="hint hint--inline">手动新增的直接算作已确认。</span>
              </div>
            </div>
          ) : null}

          {requirements.length === 0 ? (
            <p className="empty-inline">
              还没有需求。把材料交给 Fitwise 后会自动整理；也可以点上面的「手动新增」先记一条。
            </p>
          ) : (
            <ul className="req-brief">
              {orderedRequirements.map((item) =>
                renderRequirement(
                  item,
                  item.status === 'confirmed' ? 'confirmed' : 'draft',
                  // 第一条草稿留个锚点：结论条上的「待确认」点一下就落到这里
                  item.id === firstDraftId ? 'requirements-draft' : undefined,
                ),
              )}
            </ul>
          )}
        </section>
      </div>

      {/* 这一页不再列待澄清问题：问题池只有一个家（售前建议 · 要问谁），
          否则同一条问题会在两页各说一遍，还容易两处口径不一致 */}
      {questions.length ? (
        <p className="hint hint--inline">
          还有 {questions.length} 处待澄清（其中 {judgementQuestions.length} 处会改变能力结论）
          <button type="button" className="link-btn" onClick={openJudgement}>
            去售前建议看「要问谁」
          </button>
        </p>
      ) : null}
    </div>
  );
}
