import { useState } from 'react';
import type { Match, MatchStatus, Priority, Requirement } from '../../api/types';
import type { ProjectTabProps } from '../../pages/ProjectWorkspacePage';
import { api } from '../../api/endpoints';
import { RISK_LEVEL_LABEL, RISK_LEVELS, risksForMatch } from '../../domain/risk';
import type { RequirementRisk } from '../../domain/risk';
import {
  MATCH_STATUS_META,
  PRIORITY_META,
  PRIORITY_TAG,
  STATUS_ORDER,
  countByStatus,
  sortByPriority,
} from '../../domain/status';
import { StatusBadge } from '../badges';
import { MatchDetail } from './MatchDetail';
import { SummaryBar } from './SummaryBar';
import type { SummaryLine } from './SummaryBar';
import { useToast } from '../Toast';
import { HelpTip } from '../HelpTip';
import {
  IconChevronDown,
  IconEvidence,
  IconPlus,
} from '../icons';

const CATEGORIES = ['部署', '产品能力', '技术', '合规', '规模', '服务'];

/** 筛选键：判断结果四档 + 风险三级，两套互斥（不做叠加，免得出现要解释的空态） */
type FilterKey = 'all' | MatchStatus | 'risk-high' | 'risk-medium' | 'risk-low';

/**
 * 能力匹配：只看已进基线的需求，以及它对应的能力结论。
 *
 * 确认这一层在「材料解析」页做（材料里读出什么、客户原文怎么写，在那里最顺手）：
 * 确认后立刻跑匹配，结果落到这一页 —— 支持情况、风险、依据都在卡片上。
 * 还没定论的事（要问客户、要问内部、要同步销售）统一在售前建议页。
 */
export function RequirementsModule({
  project,
  matches,
  refresh,
  runTask,
}: ProjectTabProps & { matches: Match[] }) {
  const [editingId, setEditingId] = useState<number | null>(null);
  const [draft, setDraft] = useState<Partial<Requirement>>({});
  const [showAdd, setShowAdd] = useState(false);
  const [filter, setFilter] = useState<FilterKey>('all');
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

  /** 这一页只看已进基线的需求：草稿在「材料解析」页确认，确认后才出现（并且立刻有结论） */
  const allRequirements = project.requirements ?? [];
  const requirements = allRequirements.filter((item) => item.status === 'confirmed');
  /** 还在材料解析页等确认的条数：结论条上要说一声，免得以为漏了 */
  const draftsLeft = allRequirements.filter((item) => item.status !== 'confirmed').length;
  const materials = project.materials ?? [];
  /**
   * 一条需求取哪份结论：**人工判定优先**。
   *
   * 正常情况下库里一条需求只有一份结论（重跑时人工判定过的会被后端跳过），
   * 但历史数据里可能同时存在"人工改的 + 之后又跑出来的 AI 结论"——
   * 这种时候界面必须显示人定的那条，否则等于 AI 把人做的承诺盖掉了。
   */
  const matchByRequirement = new Map<number, Match>();
  for (const item of matches) {
    const current = matchByRequirement.get(item.requirement_id);
    if (!current || (item.judgment_source === 'human' && current.judgment_source !== 'human')) {
      matchByRequirement.set(item.requirement_id, item);
    }
  }
  /** 去重后的结论：统计、筛选、下一步判定都读这一份，别把同一需求的两次结论算两遍 */
  const effectiveMatches = [...matchByRequirement.values()];
  const solutionRisks = project.solution?.risks ?? [];
  /** 只有一份材料时不需要在每条需求上重复文件名，页码才是要找的东西 */
  const showSourceDocName = materials.length > 1;
  const highPriority = requirements.filter((item) => item.priority === 'high').length;
  /**
   * 能力判断的分档分布：这一句从售前建议页搬过来 ——
   * 结论本来就长在这一页的卡片上，统计也该跟着结论走。
   * 只列有的档，顺序是「越靠前越需要人管」：待补依据 → 暂不支持 → 部分支持 → 完全支持。
   * 用顿号而不是「 · 」：四个档位连起来 27 个字，正好落在概括行的 30 字以内，不会被截成「…完全支…」。
   */
  const statusCounts = countByStatus(effectiveMatches.map((item) => item.status));
  const statusText = effectiveMatches.length
    ? [
        statusCounts.unknown ? `待补依据 ${statusCounts.unknown}` : '',
        statusCounts.none ? `暂不支持 ${statusCounts.none}` : '',
        statusCounts.partial ? `部分支持 ${statusCounts.partial}` : '',
        statusCounts.full ? `完全支持 ${statusCounts.full}` : '',
      ]
        .filter(Boolean)
        .join('，')
    : '还没有匹配结果';
  /** 顺序 = 优先级（P0 → P1 → P2），同一档内保持抽出来的次序 */
  const orderedRequirements = sortByPriority(requirements);
  const openJudgement = () => {
    window.location.hash = `/projects/${project.id}/judgement`;
  };
  /** 已确认但还没出结论的条数：确认过、判断没跑完（或跑失败）时会用到 */
  const unjudged = requirements.filter((item) => !matchByRequirement.has(item.id)).length;

  /**
   * 筛选：支持四档按判断结果筛，风险三级按"挂在这条需求上的风险"筛。
   * 风险用和卡片同一套规则算出来（risksForMatch），筛选数字和看到的行数必须同源。
   */
  const risksByRequirement = new Map<number, RequirementRisk[]>(
    effectiveMatches.map((item) => [item.requirement_id, risksForMatch(item, solutionRisks)]),
  );
  const riskCounts: Record<'high' | 'medium' | 'low', number> = {
    high: requirements.filter((item) =>
      risksByRequirement.get(item.id)?.some((risk) => risk.level === 'high'),
    ).length,
    medium: requirements.filter((item) =>
      risksByRequirement.get(item.id)?.some((risk) => risk.level === 'medium'),
    ).length,
    low: requirements.filter((item) =>
      risksByRequirement.get(item.id)?.some((risk) => risk.level === 'low'),
    ).length,
  };
  const riskLevel = filter.startsWith('risk-')
    ? (filter.slice('risk-'.length) as 'high' | 'medium' | 'low')
    : null;
  const statusFilter: MatchStatus | null =
    riskLevel || filter === 'all' ? null : (filter as MatchStatus);
  const visibleRequirements = riskLevel
    ? orderedRequirements.filter((item) =>
        risksByRequirement.get(item.id)?.some((risk) => risk.level === riskLevel),
      )
    : statusFilter
      ? orderedRequirements.filter((item) => matchByRequirement.get(item.id)?.status === statusFilter)
      : orderedRequirements;
  const hasRisk = requirements.some((item) => (risksByRequirement.get(item.id)?.length ?? 0) > 0);

  /**
   * 下一步：这一页是"看结果"的地方，所以下一步不在本页 ——
   * 没确认的草稿回材料解析页；有确认但没判完的，就地补判断；都判完就去售前建议。
   */
  const nextStepLine: SummaryLine = !requirements.length
    ? {
        label: '下一步',
        text: '去材料解析确认需求，确认后自动匹配',
        href: `/projects/${project.id}/materials`,
      }
    : draftsLeft
      ? {
          label: '下一步',
          text: `还有 ${draftsLeft} 条草稿在材料解析页等确认`,
          href: `/projects/${project.id}/materials`,
        }
      : unjudged
        ? { label: '下一步', text: `还有 ${unjudged} 条没出结论，点「补一次判断」`, target: 'requirements-list' }
        : {
            label: '下一步',
            text:
              statusCounts.none || statusCounts.unknown
                ? `去售前建议：${[
                    statusCounts.none ? `${statusCounts.none} 条暂不支持` : '',
                    statusCounts.unknown ? `${statusCounts.unknown} 条待补依据` : '',
                  ]
                    .filter(Boolean)
                    .join('、')}要先谈`
                : '去售前建议看风险与要问谁',
            href: `/projects/${project.id}/judgement`,
          };

  const markJudging = (id: number, on: boolean) =>
    setJudging((prev) =>
      on ? (prev.includes(id) ? prev : [...prev, id]) : prev.filter((item) => item !== id),
    );

  const toggleDetail = (id: number) =>
    setOpenDetail((prev) => (prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]));

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

  /**
   * 人工改优先级：点卡片左侧的 P0/P1/P2 就能换档。
   * 改完会立刻按新档位排序（卡片会移动到该去的位置），所以给一句提示，别让人以为点丢了。
   */
  const setPriority = async (id: number, priority: Priority) => {
    try {
      await api.updateRequirement(id, { priority });
      await refresh();
      toast.push(
        `优先级已改为 ${PRIORITY_TAG[priority]}（${PRIORITY_META[priority].label}），列表已按新顺序排列`,
        'success',
      );
    } catch (error) {
      toast.push(error instanceof Error ? error.message : '改优先级失败', 'error');
    }
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

  const renderRequirement = (item: Requirement) => {
    const match = matchByRequirement.get(item.id);
    const evidenceCount = (match?.capability_doc_ids.length ?? 0) + 1;
    const risks = risksByRequirement.get(item.id) ?? [];
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
      <li key={item.id} id={`requirement-${item.id}`} className="req-item">
        {/* 优先级胶囊本身就是入口：点一下换档（P0/P1/P2），改完列表按新档位重排 */}
        <details className="prio-menu">
          <summary
            className={`req-brief__p req-brief__p--${item.priority}`}
            title={`${PRIORITY_META[item.priority]?.label ?? '中'}优先级 · 点一下改档`}
          >
            {PRIORITY_TAG[item.priority] ?? 'P1'}
          </summary>
          <div className="prio-menu__body">
            {(['high', 'medium', 'low'] as Priority[]).map((level) => (
              <button
                key={level}
                type="button"
                className={`link-btn${level === item.priority ? ' is-current' : ''}`}
                onClick={() => void setPriority(item.id, level)}
              >
                {PRIORITY_TAG[level]} {PRIORITY_META[level].label}优先级
                {level === item.priority ? ' · 当前' : ''}
              </button>
            ))}
          </div>
        </details>
        <div className="req-brief__main">
          <span className="req-brief__title">{item.title}</span>
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
          ) : (
            <p className="hint hint--inline req-result__missing">
              这条还没有判断结论 ·{' '}
              <button type="button" className="link-btn" onClick={() => void judgeOne(item.id)}>
                补一次判断
              </button>
            </p>
          )}

          <div className="req-item__actions">
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
        tone={!requirements.length ? 'info' : statusCounts.none || statusCounts.unknown ? 'warn' : 'ok'}
        verdict={
          !requirements.length
            ? '还没有已确认的需求'
            : draftsLeft
              ? `${requirements.length} 条已进基线，另有 ${draftsLeft} 条待确认`
              : `${requirements.length} 条需求的能力结论已就绪`
        }
        sub={
          requirements.length
            ? `共 ${requirements.length} 项已确认 · 已出结论 ${effectiveMatches.length} · 来自 ${materials.length} 份客户材料`
            : draftsLeft
              ? // 空态的指引用一句话说完：结论条是唯一说这件事的地方，不另开提示块
                `有 ${draftsLeft} 条需求在「材料解析」页等着确认 —— 在那儿能直接看到客户原文那一句，点「确认」就会自动跑能力匹配`
              : materials.length
                ? '材料里还没整理出需求。去「材料解析」上传或重新提取要点。'
                : '先去「材料解析」上传客户材料，Fitwise 会自动整理出需求；确认之后在这里看能力结论。'
        }
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
          nextStepLine,
          // 待澄清的统计不在这里：问题池住在售前建议的「要问谁」里，统计跟着它走。
          // 这一页只在清单底下留一行入口（见页面底部），看结果的时候不会断线。
        ]}
        action={
          // 这一页没有"确认"动作（在材料解析页做）：没结果时指回去确认，有结果时去下一段
          requirements.length
            ? { label: '去售前建议', onClick: openJudgement }
            : {
                label: '去材料解析',
                onClick: () => {
                  window.location.hash = `/projects/${project.id}/materials`;
                },
              }
        }
      />

      <div className="req-columns">
        {/* 一份清单：不按来源分家，也不按状态重排 —— 确认后原地变基线，位置不动 */}
        <section className="section-open" id="requirements-list">
          <header className="section-open__head">
            <div className="section-open__titleline">
              <h3>
                需求
                <span className="fact-group__count">{requirements.length}</span>
              </h3>
              <HelpTip
                text={
                  '这里只列已进基线的需求（确认在「材料解析」页做），按优先级从高到低排。' +
                  'P0 = 客户写了硬性口径（必须 / 不得 / 不低于），或不做就交付不了；' +
                  'P1 = 影响方案、报价或工期的关键条件；P2 = 加分项与可选范围。' +
                  'AI 标的档位会在原文里核对，找不到硬性表述就降一档；点左侧的 P0/P1/P2 可以自己改，改完列表立刻按新顺序排。' +
                  '改一条需求的内容（··· 里的「编辑」）会重跑这一条的能力判断 —— 结论不许停在旧版本上。'
                }
              />
            </div>
            <div className="section-open__actions">
              <button type="button" className="link-btn" onClick={() => setShowAdd((prev) => !prev)}>
                <IconPlus width={13} height={13} />
                手动新增
              </button>
            </div>
          </header>

          {/* 筛选：支持四档按结论筛，风险三级按挂在这条需求上的风险筛（两套互斥，一次只看一种） */}
          <div className="filter-chips" role="group" aria-label="筛选：按判断结果，或只看某一级风险">
            <button
              type="button"
              className={`filter-chip${filter === 'all' ? ' filter-chip--active' : ''}`}
              onClick={() => setFilter('all')}
            >
              全部 {requirements.length}
            </button>
            {STATUS_ORDER.map((status) => (
              <button
                key={status}
                type="button"
                title={MATCH_STATUS_META[status].description}
                className={`filter-chip filter-chip--${status}${
                  filter === status ? ' filter-chip--active' : ''
                }`}
                disabled={statusCounts[status] === 0}
                onClick={() => setFilter(filter === status ? 'all' : status)}
              >
                <span className={`filter-chip__dot filter-chip__dot--${status}`} />
                {MATCH_STATUS_META[status].shortLabel} {statusCounts[status]}
              </button>
            ))}
            {hasRisk ? (
              <>
                <span className="filter-chips__sep" aria-hidden="true" />
                {RISK_LEVELS.map((level) => {
                  const key = `risk-${level}` as FilterKey;
                  return (
                    <button
                      key={level}
                      type="button"
                      title={`只看含${RISK_LEVEL_LABEL[level]}风险的需求`}
                      className={`filter-chip${filter === key ? ' filter-chip--active' : ''}`}
                      disabled={riskCounts[level] === 0}
                      onClick={() => setFilter(filter === key ? 'all' : key)}
                    >
                      <span className={`filter-chip__dot filter-chip__dot--risk-${level}`} />
                      {RISK_LEVEL_LABEL[level]}风险 {riskCounts[level]}
                    </button>
                  );
                })}
              </>
            ) : null}
          </div>

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
              还没有已确认的需求。在「材料解析」页逐条确认后，结论会出现在这里；也可以点上面的「手动新增」先记一条。
            </p>
          ) : visibleRequirements.length === 0 ? (
            <p className="empty-inline">这一档暂时没有条目，换个筛选看看。</p>
          ) : (
            <ul className="req-brief">
              {visibleRequirements.map((item) => renderRequirement(item))}
            </ul>
          )}
        </section>
      </div>

      {/* 待澄清的统计与入口都不在这一页：问题池只有一个家（售前建议 ·「要问谁」），
          那里的每条还带着「影响判断 / 影响承诺」标记，比在这里用猜出来的数字再报一次准。
          这一页只谈结论；要去看问题就用结论条上的「去售前建议」。 */}
    </div>
  );
}
