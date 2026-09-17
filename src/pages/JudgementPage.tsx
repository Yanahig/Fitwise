import type { Match, Priority, Project } from '../api/types';
import { buildActionGroups, promiseBoundaries } from '../domain/actions';
import type { ActionRow } from '../domain/actions';
import { RISK_LEVEL_LABEL, RISK_LEVELS } from '../domain/risk';
import type { RiskLevel, SolutionRisk } from '../domain/risk';
import { BasisList } from '../components/project/BasisList';
import { SummaryBar } from '../components/project/SummaryBar';
import type { SummaryLine } from '../components/project/SummaryBar';
import { HelpTip } from '../components/HelpTip';
import { IconAlert, IconRoute, IconTarget, IconUsers } from '../components/icons';

/** 风险分区顺序：高 → 中 → 低 */
const RISK_ORDER: Record<RiskLevel, number> = { high: 0, medium: 1, low: 2 };

/**
 * 售前建议：回答「这个项目现在什么结论、还剩什么事没定」。
 *
 * 逐条判断在能力匹配页的需求卡上：这一页只放三块 ——
 * 结论（整体判断与匹配度）、风险（判断的后果）、要问谁（问题池按对象分组的执行视图）。
 */
export function JudgementPage({
  project,
  matches,
  onGenerate,
  busy = false,
}: {
  project: Project;
  matches: Match[];
  /** 生成 / 重新生成售前建议：风险、行动建议都由它产出 */
  onGenerate?: () => void;
  busy?: boolean;
}) {
  const requirementsHref = `/projects/${project.id}/requirements`;

  if (matches.length === 0) {
    // 空态和「材料解析 / 能力匹配」同一套骨架：保留结论条，内容区用 intake-inline 提示块
    const parsedCount = project.counts?.materials_parsed ?? project.materials?.length ?? 0;
    const confirmedCount = project.counts?.requirements_confirmed ?? 0;
    const missingStep =
      parsedCount === 0
        ? { label: '去材料解析', target: 'materials' }
        : confirmedCount === 0
          ? { label: '去材料解析确认', target: 'materials' }
          : null;
    const sub = !parsedCount
      ? '先在「材料解析」上传材料；读完会自动整理成需求，确认之后我才能逐条判断。'
      : !confirmedCount
        ? '需求还没确认。去「材料解析」逐条确认（每条下面有客户原文那一句），确认后会自动做能力匹配。'
        : '需求已确认，把能力匹配跑一遍就能出建议了。';
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
            ) : (
              // 已经确认过、只是还没匹配：去能力匹配页对没结论的条目「补一次判断」
              <button
                type="button"
                className="btn btn--primary btn--sm"
                onClick={() => {
                  window.location.hash = requirementsHref;
                }}
              >
                去能力匹配补判断
              </button>
            )}
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

  /* ---------------- 风险：判断的后果 ---------------- */

  const derivedRisks: SolutionRisk[] = [...gaps, ...unknown].map((item) => ({
    level: item.status === 'none' ? 'high' : 'medium',
    title: item.requirement?.title ?? '',
    detail: item.condition || item.headline,
    mitigation: item.confirmations[0] ?? '需要与客户确认后重新判断',
    requirement_ids: [item.requirement_id],
  }));

  const risks: SolutionRisk[] = (solution?.risks?.length ? solution.risks : derivedRisks)
    .slice()
    .sort((a, b) => RISK_ORDER[a.level] - RISK_ORDER[b.level]);
  const highRiskCount = risks.filter((item) => item.level === 'high').length;

  /* ---------------- 要问谁：还没定的事按对象分组 ---------------- */

  const actions = buildActionGroups(project, matches);
  const boundaries = promiseBoundaries(matches);
  const priorityLabel: Record<Priority, string> = { high: '优先', medium: '常规', low: '可选' };

  const openRequirement = (requirementId: number) =>
    window.dispatchEvent(
      new CustomEvent('fitwise:open-project-tab', {
        detail: { tab: 'requirements', anchor: `requirement-${requirementId}` },
      }),
    );

  /**
   * 结论条上的三句概括：各自指向下面那一块 —— 它同时是这一页的目录。
   * 「需求判断」那一句不在这里：逐条结论跟着需求卡走（能力匹配页）。
   * 「待澄清」回答"还剩多少事"，「下一步」回答"先办哪一件、谁办、什么时候" ——
   * 所以后者的文本要短（先取动作的第一个短句），责任人与日期跟在后面，
   * 这样 30 个字的概括行里也放得下，点一下直接落到那一条动作上。
   */
  const nextAction = actions.sales[0];
  const shortActionText = (text: string) => {
    const head = text.split(/[：:，,]/)[0].trim();
    return head.length >= 6 ? head : text;
  };
  const nextStepText = nextAction
    ? `${shortActionText(nextAction.text)}${
        [nextAction.owner, nextAction.due?.slice(5)].filter(Boolean).length
          ? `（${[nextAction.owner, nextAction.due?.slice(5)].filter(Boolean).join(' · ')}）`
          : ''
      }`
    : actions.customer.length
      ? `先问客户：${shortActionText(actions.customer[0].text)}`
      : '还没有下一步建议，先生成一份建议';
  /** 待澄清统计跟着「要问谁」走：能力匹配页只在清单底下留一行入口，这里才是它的家 */
  const openQuestions = project.open_questions ?? [];
  const customerQuestionCount = openQuestions.filter((item) => (item.owner || '客户') !== '内部').length;
  const summaryLines: SummaryLine[] = [
    {
      label: '风险',
      text: `${risks.length} 条风险，其中 ${highRiskCount} 条高影响`,
      target: 'advice-risks',
    },
    {
      label: '待澄清',
      text: openQuestions.length
        ? `${openQuestions.length} 处（问客户 ${customerQuestionCount} · 内部 ${
            openQuestions.length - customerQuestionCount
          }）`
        : '暂时没有待澄清问题',
      target: 'judgement-actions',
    },
    {
      label: '下一步',
      text: nextStepText,
      // 有具体动作就落到那一条上；没有动作时退回整个「要问谁」分区
      target: nextAction ? 'next-action' : 'judgement-actions',
    },
  ];

  const renderRow = (row: ActionRow, anchorId?: string) => (
    <li key={row.text} id={anchorId}>
      <span className="action-group__tag">{row.tag}</span>
      <span className="action-group__text">
        {row.text}
        {row.impact ? (
          <span
            className={`gap-lines__impact${row.impact === 'judge' ? ' gap-lines__impact--judge' : ''}`}
            title={
              row.impact === 'judge'
                ? '这条不确认，能力结论就不成立'
                : '这条不确认，只影响承诺与交付口径'
            }
          >
            {row.impact === 'judge' ? '影响判断' : '影响承诺'}
          </span>
        ) : null}
        {row.owner ? (
          <em className="action-group__owner">
            {row.owner}
            {row.due ? ` · ${row.due}` : ''}
            {row.priority ? ` · ${priorityLabel[row.priority as Priority] ?? ''}` : ''}
          </em>
        ) : null}
        {row.basis?.length ? (
          <BasisList basis={row.basis} materials={project.materials ?? []} />
        ) : null}
      </span>
    </li>
  );

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
          onGenerate
            ? {
                label: busy ? '生成中…' : solution ? '重新生成建议' : '生成建议',
                onClick: onGenerate,
                disabled: busy,
              }
            : undefined
        }
        secondary={{ label: '去能力匹配', onClick: () => (window.location.hash = requirementsHref) }}
      />

      {/* 风险：每条都挂着它依据的那条需求 —— 逐条结论与依据在需求卡上，这里只排优先级 */}
      <section className="section-open" id="advice-risks">
        <header className="section-open__head">
          <div className="section-open__titleline">
            <h3>
              <IconAlert width={16} height={16} />
              风险提示
              <span className="fact-group__count">{risks.length}</span>
            </h3>
            <HelpTip
              text={
                solution?.risks?.length
                  ? '风险来自能力判断：暂不支持 → 高风险，部分支持 / 待补依据 → 中风险。每条都能点回它依据的那条需求。'
                  : '还没生成建议，这里的风险按判断结果直接派生：暂不支持 → 高风险，部分支持 / 待补依据 → 中风险。生成一份建议会让它更贴项目。'
              }
            />
          </div>
        </header>

        {risks.length === 0 ? (
          <p className="empty-inline">没有识别到风险。</p>
        ) : (
          <div className="action-groups">
            {RISK_LEVELS.map((level) => {
              const items = risks.filter((risk) => risk.level === level);
              if (!items.length) return null;
              return (
                <details key={level} className="action-group" open={level === 'high'}>
                  <summary className="action-group__head">
                    <span className={`action-group__icon action-group__icon--${level}`}>
                      <IconAlert width={15} height={15} />
                    </span>
                    <h4>{RISK_LEVEL_LABEL[level]}风险</h4>
                    <span className="action-group__tail">
                      <span className="action-group__count">{items.length}</span>
                      <span className="group-chevron" aria-hidden="true" />
                    </span>
                  </summary>
                  <ul className="risk-list">
                    {items.map((risk) => (
                      <li key={risk.title} className="risk-item">
                        <p className="risk-item__title">
                          <span className={`entry__risk-tag entry__risk-tag--${risk.level}`}>
                            {RISK_LEVEL_LABEL[risk.level]}
                          </span>
                          {risk.title}
                        </p>
                        {risk.detail ? <p className="risk-item__detail">{risk.detail}</p> : null}
                        {risk.mitigation ? (
                          <p className="risk-item__fix">
                            <span>建议应对</span>
                            {risk.mitigation}
                          </p>
                        ) : null}
                        {risk.requirement_ids?.length ? (
                          <button
                            type="button"
                            className="link-btn risk-item__link"
                            onClick={() => openRequirement(risk.requirement_ids![0])}
                          >
                            看这条需求
                            {risk.requirement_ids.length > 1
                              ? `（另涉及 ${risk.requirement_ids.length - 1} 条）`
                              : ''}
                          </button>
                        ) : (
                          <span className="hint hint--inline">项目级风险，挂不到单条需求</span>
                        )}
                      </li>
                    ))}
                  </ul>
                </details>
              );
            })}
          </div>
        )}
      </section>

      {/* 要问谁：完整的问题池（需求阶段 + 方案阶段 + 判断给出的前提），按对象分组 */}
      <section className="section-open" id="judgement-actions">
        <header className="section-open__head">
          <div className="section-open__titleline">
            <h3>
              <IconRoute width={16} height={16} />
              要问谁
              <span className="fact-group__count">{actions.total}</span>
            </h3>
            <HelpTip text="还没定的事都在这三组里：要问客户、要问内部（同事 / 研发）、要同步销售。标「影响判断」的不确认，能力结论就不成立；标「影响承诺」的只影响交付口径。" />
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
                <span className="action-group__count">{actions.customer.length}</span>
              </span>
            </div>
            <ul className="action-group__list">
              {actions.customer.map((row) => renderRow(row))}
              {actions.customer.length === 0 ? <li className="action-group__rest">暂无</li> : null}
            </ul>
          </section>

          <section className="action-group">
            <div className="action-group__head">
              <span className="action-group__icon">
                <IconTarget width={15} height={15} />
              </span>
              <h4>要问内部</h4>
              <span className="action-group__tail">
                <span className="action-group__count">{actions.internal.length}</span>
              </span>
            </div>
            <ul className="action-group__list">
              {actions.internal.map((row) => renderRow(row))}
              {actions.internal.length === 0 ? <li className="action-group__rest">暂无</li> : null}
            </ul>
          </section>

          <section className="action-group">
            <div className="action-group__head">
              <span className="action-group__icon">
                <IconRoute width={15} height={15} />
              </span>
              <h4>要同步销售</h4>
              <span className="action-group__tail">
                <span className="action-group__count">{actions.sales.length}</span>
              </span>
            </div>
            <ul className="action-group__list">
              {/* 第一条挂个锚点：结论条上的「下一步」直接落到它身上（列表已按优先级 + 截止日期排） */}
              {actions.sales.map((row, index) => renderRow(row, index === 0 ? 'next-action' : undefined))}
              {actions.sales.length === 0 ? <li className="action-group__rest">暂无</li> : null}
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
