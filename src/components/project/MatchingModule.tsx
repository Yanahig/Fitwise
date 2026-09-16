import { useEffect, useState } from 'react';
import type { Match } from '../../api/types';
import type { ProjectTabProps } from '../../pages/ProjectWorkspacePage';
import { MATCH_STATUS_META, STATUS_ORDER, countByStatus } from '../../domain/status';
import { STATUS_RANK } from '../../domain/status';
import type { MatchStatus } from '../../api/types';
import {
  RISK_LEVELS,
  RISK_LEVEL_LABEL,
  requirementIdsOfLevel,
  riskRankOfRequirement,
  unplacedRisks,
} from '../../domain/risk';
import { MatchingTab } from './MatchingTab';

/**
 * 售前建议里的「能不能做」：只回答一件事 —— 已确认的客户需求与现有能力的匹配关系。
 *
 * 一条需求一行：需求 → 判断结论 → 原文链接 → 依据。不铺卡片、不做多视角切换。
 * 上面一排筛选胶囊干两件事：按判断结果看，或者只看某一级风险（纯风险视图）。
 * 风险正文长在条目里，所以这里不再另开「风险提示」板块。
 */

/** 筛选键：判断结果四档 + 风险三级，两套互斥（不做叠加，免得出现要解释的空态） */
type FilterKey = 'all' | MatchStatus | 'risk-high' | 'risk-medium' | 'risk-low';

export function MatchingModule({ project, matches, refresh, runTask, job, busy }: ProjectTabProps & { matches: Match[] }) {
  const counts = countByStatus(matches.map((item) => item.status));
  const [filter, setFilter] = useState<FilterKey>('all');
  const solutionRisks = project.solution?.risks ?? [];
  const idsByLevel = {
    high: requirementIdsOfLevel(solutionRisks, 'high'),
    medium: requirementIdsOfLevel(solutionRisks, 'medium'),
    low: requirementIdsOfLevel(solutionRisks, 'low'),
  };
  const riskLevel = filter.startsWith('risk-')
    ? (filter.slice('risk-'.length) as 'high' | 'medium' | 'low')
    : null;
  const statusFilter: MatchStatus | null =
    riskLevel || filter === 'all' ? null : (filter as MatchStatus);

  /** 筛选栏上的数字 = 筛出来的行数，两处必须是同一个口径 */
  const riskCounts: Record<'high' | 'medium' | 'low', number> = {
    high: matches.filter((item) => idsByLevel.high.has(item.requirement_id)).length,
    medium: matches.filter((item) => idsByLevel.medium.has(item.requirement_id)).length,
    low: matches.filter((item) => idsByLevel.low.has(item.requirement_id)).length,
  };
  const wideRisks = unplacedRisks(solutionRisks);

  /**
   * 默认排序：待补依据 → 暂不支持 → 部分支持 → 完全支持；同一档里先排风险高的，其余保持后端给的顺序。
   * 目的很直接 —— 打开页面第一条就是最需要人管的那条，不用自己找。
   */
  const ordered = matches
    .map((match, index) => ({ match, index }))
    .sort(
      (a, b) =>
        STATUS_RANK[a.match.status] - STATUS_RANK[b.match.status] ||
        riskRankOfRequirement(solutionRisks, a.match.requirement_id) -
          riskRankOfRequirement(solutionRisks, b.match.requirement_id) ||
        a.index - b.index,
    )
    .map((item) => item.match);

  /** 筛选只改变"看哪几条"，不改变排序：三种视图读到的次序是同一个 */
  const visible = riskLevel
    ? ordered.filter((item) => idsByLevel[riskLevel].has(item.requirement_id))
    : statusFilter
      ? ordered.filter((item) => item.status === statusFilter)
      : ordered;

  // 结论条上的「风险」那句点一下 = 直接切到高风险视图：列表就在下面，不另开板块
  useEffect(() => {
    const focusHighRisk = () => {
      setFilter('risk-high');
      document.getElementById('can-do')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };
    window.addEventListener('fitwise:focus-high-risk', focusHighRisk);
    return () => window.removeEventListener('fitwise:focus-high-risk', focusHighRisk);
  }, []);

  return (
    <section className="section-open" id="can-do">
      <header className="section-open__head">
        <div className="section-open__titleline">
          <h3>
            能不能做
            <span className="fact-group__count">{matches.length} 条</span>
          </h3>
          <p>已确认的客户需求 ↔ 现有能力，每条都能点回材料原文与依据</p>
        </div>
      </header>

      {/* 概括栏同时是筛选条：前半段按判断结果分档，后半段按风险等级看纯风险视图 */}
      <div className="filter-chips" role="group" aria-label="筛选：按判断结果，或只看某一级风险">
        <button
          type="button"
          className={`filter-chip${filter === 'all' ? ' filter-chip--active' : ''}`}
          onClick={() => setFilter('all')}
        >
          全部 {matches.length}
        </button>
        {STATUS_ORDER.map((status) => (
          <button
            key={status}
            type="button"
            title={MATCH_STATUS_META[status].description}
            className={`filter-chip filter-chip--${status}${
              filter === status ? ' filter-chip--active' : ''
            }`}
            // 0 条的那一档点了也是空，直接禁掉：同一排里"能不能点"的规则保持一致
            disabled={counts[status] === 0}
            onClick={() => setFilter(filter === status ? 'all' : status)}
          >
            <span className={`filter-chip__dot filter-chip__dot--${status}`} />
            {MATCH_STATUS_META[status].shortLabel} {counts[status]}
          </button>
        ))}
        {solutionRisks.length ? (
          <>
            <span className="filter-chips__sep" aria-hidden="true" />
            {RISK_LEVELS.map((level) => {
              const key = `risk-${level}` as FilterKey;
              return (
                <button
                  key={level}
                  type="button"
                  title={`只看含${RISK_LEVEL_LABEL[level]}风险的需求；选中后风险正文直接展开`}
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

      {/* 兜底：模型偶尔会写挂不到任何需求的风险（项目级），条目里放不下，在这里列出来 */}
      {wideRisks.length ? (
        <details className="risk-wide">
          <summary>另有 {wideRisks.length} 条项目级风险（挂不到单条需求）</summary>
          <ul>
            {wideRisks.map((risk) => (
              <li key={risk.title}>
                <span className={`entry__risk-tag entry__risk-tag--${risk.level}`}>
                  {RISK_LEVEL_LABEL[risk.level]}
                </span>
                <span>{risk.title}</span>
                {risk.mitigation ? (
                  <p className="entry__risk-fix">建议应对：{risk.mitigation}</p>
                ) : null}
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      <MatchingTab
        project={project}
        matches={visible}
        refresh={refresh}
        runTask={runTask}
        job={job}
        busy={busy}
        // 选了风险筛选就是"纯风险视图"：风险正文不用再点一次才展开
        expandRisk={Boolean(riskLevel)}
        emptyLabel={filter === 'all' ? undefined : '这一档暂时没有条目，换个筛选看看。'}
      />
    </section>
  );
}
