import { useState } from 'react';
import type { MouseEvent } from 'react';
import type { Match, MatchBasis, Priority, Project } from '../api/types';
import { EmptyState } from '../components/EmptyState';
import { useToast } from '../components/Toast';
import { BasisList } from '../components/project/BasisList';
import { SummaryBar } from '../components/project/SummaryBar';
import type { SummaryLine } from '../components/project/SummaryBar';
import { MATCH_STATUS_META, STATUS_ORDER } from '../domain/status';
import {
  IconCompass,
  IconRoute,
  IconTarget,
  IconUsers,
} from '../components/icons';

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
  const toast = useToast();
  const [copied, setCopied] = useState<string | null>(null);

  if (matches.length === 0) {
    return (
      <EmptyState
        icon={<IconCompass width={26} height={26} />}
        title="还没有判断结论"
        description={
          canRun
            ? '需求确认完成后，这里会逐条给出能不能做、风险与下一步。'
            : '先在右侧 Agent 上传客户材料，再逐条确认需求。'
        }
      >
        {onRerun ? (
          <button type="button" className="btn btn--primary" disabled={busy || !canRun} onClick={onRerun}>
            {busy ? '判断中…' : '开始能力判断'}
          </button>
        ) : null}
      </EmptyState>
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

  const copyList = async (key: string, title: string, lines: string[]) => {
    if (!lines.length) {
      toast.push('暂时没有可复制的内容', 'error');
      return;
    }
    try {
      await navigator.clipboard.writeText(
        [`【${project.customer_name} · ${project.name}】${title}`, '', ...lines.map((item, i) => `${i + 1}. ${item}`)].join(
          '\n',
        ),
      );
      setCopied(key);
      toast.push('已复制', 'success');
      window.setTimeout(() => setCopied(null), 2000);
    } catch {
      toast.push('浏览器未允许剪贴板访问', 'error');
    }
  };

  /** 折叠卡片标题里的按钮：先拦掉「点击会收起卡片」的默认行为，再复制 */
  const copyFromSummary = (
    event: MouseEvent<HTMLButtonElement>,
    key: string,
    title: string,
    lines: string[],
  ) => {
    event.preventDefault();
    event.stopPropagation();
    void copyList(key, title, lines);
  };

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

      {/* 四种结论的含义：放在结论出现的这一页，一行铺开不折叠 */}
      <section className="status-legend status-legend--inline" aria-label="判断结果说明">
        {STATUS_ORDER.map((status) => (
          <span key={status} className="status-legend__chip">
            <span className={`status-badge status-badge--${MATCH_STATUS_META[status].tone}`}>
              {MATCH_STATUS_META[status].label}
            </span>
            <span className="status-legend__hint" title={MATCH_STATUS_META[status].description}>
              {MATCH_STATUS_META[status].description}
            </span>
          </span>
        ))}
      </section>

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
            <p>和需求确认页是同一个问题池，这里按问谁分组；每组能整段复制</p>
          </div>
        </header>

        <div className="action-groups">
          <details className="action-group" open>
            <summary className="action-group__head">
              <span className="action-group__icon">
                <IconUsers width={15} height={15} />
              </span>
              <h4>要问客户</h4>
              <span className="action-group__tail">
                <span className="action-group__count">{toCustomer.length}</span>
                <button
                  type="button"
                  className="link-btn"
                  onClick={(event) =>
                    copyFromSummary(event, 'customer', '要问客户的问题', toCustomer)
                  }
                >
                  {copied === 'customer' ? '已复制' : '复制'}
                </button>
                <span className="group-chevron" aria-hidden="true" />
              </span>
            </summary>
            <ul className="action-group__list">
              {toCustomer.slice(0, 3).map((item) => (
                <li key={item}>{item}</li>
              ))}
              {toCustomer.length > 4 ? (
                  <li className="action-group__rest">还有 {toCustomer.length - 3} 条，复制后可看全部</li>
              ) : null}
              {toCustomer.length === 0 ? <li className="action-group__rest">暂无</li> : null}
            </ul>
          </details>

          <details className="action-group">
            <summary className="action-group__head">
              <span className="action-group__icon">
                <IconTarget width={15} height={15} />
              </span>
              <h4>要问内部</h4>
              <span className="action-group__tail">
                <span className="action-group__count">{toInternal.length}</span>
                <button
                  type="button"
                  className="link-btn"
                  onClick={(event) =>
                    copyFromSummary(
                      event,
                      'internal',
                      '要问内部的问题',
                      toInternal.map((item) =>
                        item.owner ? `${item.question}（${item.owner}）` : item.question,
                      ),
                    )
                  }
                >
                  {copied === 'internal' ? '已复制' : '复制'}
                </button>
                <span className="group-chevron" aria-hidden="true" />
              </span>
            </summary>
            <ul className="action-group__list">
              {toInternal.slice(0, 3).map((item) => (
                <li key={item.question}>
                  {item.question}
                  {item.owner ? <em className="action-group__owner">{item.owner}</em> : null}
                </li>
              ))}
              {toInternal.length > 4 ? (
                <li className="action-group__rest">还有 {toInternal.length - 3} 条</li>
              ) : null}
              {toInternal.length === 0 ? <li className="action-group__rest">暂无</li> : null}
            </ul>
          </details>

          <details className="action-group">
            <summary className="action-group__head">
              <span className="action-group__icon">
                <IconRoute width={15} height={15} />
              </span>
              <h4>要同步销售</h4>
              <span className="action-group__tail">
                <span className="action-group__count">{toSales.length}</span>
                <button
                  type="button"
                  className="link-btn"
                  onClick={(event) =>
                    copyFromSummary(event, 'sales', '要同步给销售的动作与边界', [
                      ...toSales.map(
                        (item) => `${item.action}（${item.owner}${item.due ? ` · ${item.due}` : ''}）`,
                      ),
                      ...boundaries.map((item) => `承诺边界：${item}`),
                    ])
                  }
                >
                  {copied === 'sales' ? '已复制' : '复制'}
                </button>
                <span className="group-chevron" aria-hidden="true" />
              </span>
            </summary>
            <ul className="action-group__list">
              {toSales.slice(0, 3).map((item) => (
                <li key={item.action}>
                  {item.action}
                  <em className="action-group__owner">
                    {item.owner}
                    {item.due ? ` · ${item.due}` : ''}
                    {item.priority ? ` · ${priorityLabel[item.priority]}` : ''}
                  </em>
                  <BasisList basis={item.basis} materials={project.materials ?? []} />
                </li>
              ))}
              {toSales.length > 4 ? (
                <li className="action-group__rest">还有 {toSales.length - 3} 条</li>
              ) : null}
              {toSales.length === 0 ? <li className="action-group__rest">暂无</li> : null}
            </ul>
            <div className="action-group__promise">
              <span className="action-group__promise-title">承诺边界</span>
              <ul>
                {boundaries.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          </details>
        </div>
      </section>
    </div>
  );
}
