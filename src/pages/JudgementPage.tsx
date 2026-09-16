import type { Match, MatchBasis, Priority, Project } from '../api/types';
import { actionLabel } from '../domain/openQuestions';
import { BasisList } from '../components/project/BasisList';
import { SummaryBar } from '../components/project/SummaryBar';
import type { SummaryLine } from '../components/project/SummaryBar';
import { IconRoute, IconTarget, IconUsers } from '../components/icons';

type RiskLevel = 'high' | 'medium' | 'low';

interface RiskItem {
  level: RiskLevel;
  title: string;
  detail: string;
  mitigation: string;
  /** 这条风险依据哪几条判断，以及判断背后的证据（后端按需求标题校验出来的） */
  requirement_ids?: number[];
  basis?: MatchBasis[];
}

/** 风险分区顺序：高 → 中 → 低 */
const RISK_ORDER: Record<RiskLevel, number> = { high: 0, medium: 1, low: 2 };

/**
 * 售前建议（MVP 核心输出三）：回答「能不能做」与「下一步怎么办」。
 *
 * 版面顺序就是信息流：结论条（三句概括）→ 能不能做（逐条判断，由外面作为 detail 传进来）
 * → 风险提示 → 行动建议。风险与行动的每条都挂着它依据的那几条判断，再往下才是原文页码。
 */
export function JudgementPage({
  project,
  matches,
  detail,
  onRerun,
  busy = false,
  canRun = true,
}: {
  project: Project;
  matches: Match[];
  /** 「能不能做」那一块（逐条判断），由项目工作台作为 slot 传进来 —— 结论文案在下面要用它的计数 */
  detail?: React.ReactNode;
  onRerun?: () => void;
  busy?: boolean;
  canRun?: boolean;
}) {
  if (matches.length === 0) {
    // 空态和「材料解析 / 需求确认」同一套骨架：保留结论条，内容区用 intake-inline 提示块
    const parsedCount = project.counts?.materials_parsed ?? project.materials?.length ?? 0;
    const confirmedCount = project.counts?.requirements_confirmed ?? 0;
    const missingStep =
      parsedCount === 0
        ? { label: '去材料解析', target: 'materials' }
        : confirmedCount === 0
          ? { label: '去需求确认', target: 'requirements' }
          : null;
    const sub = !parsedCount
      ? '先在「客户材料」上传材料；读完会自动整理成需求，确认之后我才能逐条判断。'
      : !confirmedCount
        ? '需求还没确认。确认之后我才能对着企业内部资料逐条判断能不能做。'
        : '需求已确认，可以逐条判断能不能做了。';
    return (
      <div className="page page--stack">
        <SummaryBar tone="info" verdict="还没有判断结论" sub={sub} />
        <section className="intake-inline">
          <header className="intake-inline__head">
            <h3>还没有判断结论</h3>
            <p className="hint">{sub}</p>
          </header>
          <div className="intake-inline__actions">
            {missingStep ? (
              <button
                type="button"
                className="btn btn--secondary btn--sm"
                onClick={() => {
                  window.location.hash = `/projects/${project.id}/${missingStep.target}`;
                }}
              >
                {missingStep.label}
              </button>
            ) : null}
            {onRerun ? (
              <button
                type="button"
                className="btn btn--primary btn--sm"
                disabled={busy || !canRun}
                onClick={onRerun}
              >
                {busy ? '判断中…' : '开始能力判断'}
              </button>
            ) : null}
          </div>
        </section>
      </div>
    );
  }

  const solution = project.solution;
  const gaps = matches.filter((item) => item.status === 'none');
  const unknown = matches.filter((item) => item.status === 'unknown');
  const matchScore = Math.round(
    (((project.counts?.matches_full ?? 0) + (project.counts?.matches_partial ?? 0) * 0.5) /
      (project.counts?.matches || 1)) *
      100,
  );
  const caseCount = new Set(matches.flatMap((item) => item.case_ids)).size;

  const verdict = gaps.length
    ? '谨慎推进：有条件地继续'
    : unknown.length
      ? '可以先推进，但需要先补齐信息'
      : '建议重点推进';
  const verdictTone = gaps.length ? 'warn' : unknown.length ? 'info' : 'ok';

  const confirmations = [
    ...gaps.flatMap((item) => item.confirmations),
    ...unknown.flatMap((item) => item.confirmations),
  ].filter((item, index, list) => item && list.indexOf(item) === index);

  /* ---------------- 风险提示 ---------------- */

  const derivedRisks: RiskItem[] = [...gaps, ...unknown].map((item) => ({
    level: item.status === 'none' ? 'high' : 'medium',
    title: item.requirement?.title ?? '',
    detail: item.condition || item.headline,
    mitigation: item.confirmations[0] ?? '需要与客户确认后重新判断',
  }));

  const risks: RiskItem[] = (solution?.risks?.length ? solution.risks : derivedRisks)
    .slice()
    .sort((a, b) => RISK_ORDER[a.level] - RISK_ORDER[b.level]);
  /** 按等级分区：高风险默认展开，中低风险默认折叠 */

  /* ---------------- 行动建议 ---------------- */

  /**
   * 问题池按「问谁」分流：需求阶段的问题自带 owner，方案阶段的问题分成对客 / 内部两拨。
   * 两个页面用的是同一个问题池 —— 需求确认页回答"我们还不知道什么"，这里回答"谁去问"。
   * 对客清单先放需求阶段的信息缺口（每条都有 why 说明为什么重要），再接方案阶段的问题，
   * 数量收敛到 12 条，避免一次抛太多问题给客户。
   */
  const openQuestions = project.open_questions ?? [];
  const customerQuestions = [
    ...openQuestions
      .filter((item) => (item.owner || '客户') !== '内部')
      .map((item) => item.question),
    ...(solution?.ask_customer ?? []),
    ...confirmations,
  ].filter((item, index, list) => item && list.indexOf(item) === index);
  const toCustomer = customerQuestions.slice(0, 12);

  /** 内部问题 = 方案里带责任方的问题 + 需求阶段标了"内部"的问题（后者还没指派到人） */
  const toInternal: { question: string; owner: string }[] = [
    ...(solution?.ask_internal ?? []),
    ...openQuestions
      .filter((item) => (item.owner || '客户') === '内部')
      .map((item) => ({ question: item.question, owner: '' })),
  ].filter(
    (item, index, list) => item.question && list.findIndex((row) => row.question === item.question) === index,
  );

  const toSales = solution?.next_actions ?? [];

  const boundaries = [
    gaps.length
      ? `能力缺口（${gaps
          .slice(0, 2)
          .map((item) => item.requirement?.title)
          .join('、')}）确认前，不承诺对应功能的交付时间与准确率`
      : '',
    unknown.length ? '还没依据的条目先按「待补依据」对客沟通，不做正面承诺' : '',
    // 赢单可能性不再作为结论输出：这个字段没有 AI 来源，只有人工/种子值
  ].filter(Boolean);

  const priorityLabel: Record<Priority, string> = { high: '优先', medium: '常规', low: '可选' };

  /** 结论条上的三句概括：各自指向下面那一块，点一下就跳过去 —— 它同时是这一页的目录 */
  const fullCount = matches.filter((item) => item.status === 'full').length;
  const partialCount = matches.filter((item) => item.status === 'partial').length;
  const highRiskCount = risks.filter((item) => item.level === 'high').length;
  const nextActionText = toSales[0]?.action ?? toCustomer[0] ?? '还没有下一步建议，先做一轮能力判断';
  const summaryLines: SummaryLine[] = [
    {
      label: '需求判断',
      text: `${matches.length} 条需求里，${fullCount} 条完全支持、${partialCount} 条要先确认前提、${gaps.length} 条暂不支持${
        unknown.length ? `、${unknown.length} 条待补依据` : ''
      }`,
      target: 'judgement-detail',
    },
    {
      label: '风险',
      text: `${risks.length} 条风险，其中 ${highRiskCount} 条高影响`,
      // 点一下 = 把「能不能做」切到高风险视图（风险没有独立板块，只有这一条视图）
      onClick: () => window.dispatchEvent(new CustomEvent('fitwise:focus-high-risk')),
    },
    {
      label: '下一步',
      // 概括行只给一句能看懂的，完整内容在下面的行动建议里
      text: nextActionText.length > 42 ? `${nextActionText.slice(0, 42)}…` : nextActionText,
      target: 'judgement-actions',
    },
  ];
  return (
    <div className="page page--stack">
      {/* 结论条：三页共用同一个组件，骨架完全一致 */}
      <SummaryBar
        tone={verdictTone}
        verdict={verdict}
        sub={`基于 ${matches.length} 项需求 · ${project.counts?.materials_parsed ?? 0} 份客户材料 · ${caseCount} 个历史案例 · 匹配度 ${matchScore}%`}
        subHint="能力匹配度：完全支持的需求算 1 分、部分支持算 0.5 分，除以已判断的需求条数。"
        lines={summaryLines}
        action={
          onRerun
            ? {
                label: busy ? '判断中…' : matches.length ? '重新判断' : '开始能力判断',
                onClick: onRerun,
                disabled: busy || !canRun,
              }
            : undefined
        }
        secondary={{
          label: '去行动建议',
          onClick: () =>
            document.getElementById('judgement-actions')?.scrollIntoView({ behavior: 'smooth', block: 'start' }),
        }}
      />

      {detail ? (
        <div id="judgement-detail">{detail}</div>
      ) : null}

      {/* 一类：行动建议 —— 按对象分三类。风险没有独立板块：挂在哪条需求上就展开在「能不能做」里 */}
      <section className="section-open" id="judgement-actions">
        <header className="section-open__head">
          <div>
            <h3>
              <IconRoute width={16} height={16} />
              行动建议
              <span className="fact-group__count">
                {toCustomer.length + toInternal.length + toSales.length}
              </span>
            </h3>
          </div>
        </header>

        <div className="action-groups">
          <section className="action-group">
            <div className="action-group__head">
              <span className="action-group__icon">
                <IconUsers width={15} height={15} />
              </span>
              <h4>要问客户</h4>
              <span className="action-group__tail">
                <span className="action-group__count">{toCustomer.length}</span>
              </span>
            </div>
            <ul className="action-group__list">
              {/* 每条左侧带小标题：一眼看出要确认的是哪一类事 */}
              {toCustomer.map((item) => (
                <li key={item}>
                  <span className="action-group__tag">{actionLabel(item)}</span>
                  <span className="action-group__text">{item}</span>
                </li>
              ))}
              {toCustomer.length === 0 ? <li className="action-group__rest">暂无</li> : null}
            </ul>
          </section>

          <section className="action-group">
            <div className="action-group__head">
              <span className="action-group__icon">
                <IconTarget width={15} height={15} />
              </span>
              <h4>要问内部</h4>
              <span className="action-group__tail">
                <span className="action-group__count">{toInternal.length}</span>
              </span>
            </div>
            <ul className="action-group__list">
              {toInternal.map((item) => (
                <li key={item.question}>
                  <span className="action-group__tag">{actionLabel(item.question)}</span>
                  <span className="action-group__text">
                    {item.question}
                    {item.owner ? <em className="action-group__owner">{item.owner}</em> : null}
                  </span>
                </li>
              ))}
              {toInternal.length === 0 ? <li className="action-group__rest">暂无</li> : null}
            </ul>
          </section>

          <section className="action-group">
            <div className="action-group__head">
              <span className="action-group__icon">
                <IconRoute width={15} height={15} />
              </span>
              <h4>要同步销售</h4>
              <span className="action-group__tail">
                <span className="action-group__count">{toSales.length}</span>
              </span>
            </div>
            <ul className="action-group__list">
              {toSales.map((item) => (
                <li key={item.action}>
                  <span className="action-group__tag">{actionLabel(item.action)}</span>
                  <span className="action-group__text">
                    {item.action}
                    <em className="action-group__owner">
                      {item.owner}
                      {item.due ? ` · ${item.due}` : ''}
                      {item.priority ? ` · ${priorityLabel[item.priority]}` : ''}
                    </em>
                    <BasisList basis={item.basis} materials={project.materials ?? []} />
                  </span>
                </li>
              ))}
              {toSales.length === 0 ? <li className="action-group__rest">暂无</li> : null}
            </ul>
            {/* 没有承诺边界就不占位：能力缺口与待补依据都没有时，这一块没有可说的内容 */}
            {boundaries.length ? (
              <div className="action-group__promise">
                <span className="action-group__promise-title">承诺边界</span>
                <ul>
                  {boundaries.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </section>
        </div>
      </section>
    </div>
  );
}
