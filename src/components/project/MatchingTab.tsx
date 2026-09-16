import { useState } from 'react';
import { api } from '../../api/endpoints';
import type { Match, MatchStatus } from '../../api/types';
import type { ProjectTabProps } from '../../pages/ProjectWorkspacePage';
import { MATCH_STATUS_META, STATUS_ORDER } from '../../domain/status';
import { RISK_LEVEL_LABEL, risksOfRequirement, topRiskOf } from '../../domain/risk';
import { Chip, StatusBadge } from '../badges';
import { IconCheck, IconChevronDown, IconEvidence, IconQuestion, IconTarget } from '../icons';

/** 取证轨迹的步骤名 → 人话 */
const TRACE_STEP_LABEL: Record<string, string> = {
  recall: '检索',
  judge: '判断',
  guardrail: '自检',
  decide: '降级决策',
};

export function MatchingTab({
  project,
  refresh,
  job,
  matches,
  expandRisk = false,
  emptyLabel,
}: ProjectTabProps & {
  matches: Match[];
  /** 正在看风险筛选：所有相关风险正文默认展开，不用再点一次 */
  expandRisk?: boolean;
  /** 筛出来是空的时候，说明"这一档没有"，而不是"还没有判断结果" */
  emptyLabel?: string;
}) {
  const [expanded, setExpanded] = useState<number | null>(null);
  const [detail, setDetail] = useState<Match | null>(null);
  /** 风险正文的展开状态：高风险默认展开，中低风险点标记才展开（就地展开，不跳走） */
  const [riskToggle, setRiskToggle] = useState<Record<number, boolean>>({});
  const [review, setReview] = useState<{ status: MatchStatus; note: string }>({ status: 'full', note: '' });

  const solutionRisks = project.solution?.risks ?? [];
  /** 朴素罗列：筛选在 MatchingModule 里做完，这里只负责画 */
  const visible = matches;
  const confirmedCount = project.counts?.requirements_confirmed ?? 0;

  const openDetail = async (match: Match) => {
    if (expanded === match.id) {
      setExpanded(null);
      setDetail(null);
      return;
    }
    setExpanded(match.id);
    setDetail(await api.match(match.id));
    setReview({ status: match.status, note: '' });
  };

  return (
    <section className="panel">
      {confirmedCount === 0 ? (
        <p className="inline-notice">
          请先在「需求确认」里确认需求。当前已确认 {confirmedCount} 条。
        </p>
      ) : null}

      {job?.kind === 'matches.run' ? (
        <p className="inline-notice">
          正在判断 {job.done}/{job.total}：{job.current || '准备中…'}
        </p>
      ) : null}

      {matches.length === 0 ? (
        <p className="empty-inline">{emptyLabel ?? '还没有判断结果。'}</p>
      ) : (
        <>
          {/* 朴素罗列：一行需求、一行判断（结论 + 原文 + 依据），没有卡片框与徽标 */}
          <ul className="entry-list">
            {visible.map((match) => {
              const relatedRisks = risksOfRequirement(solutionRisks, match.requirement_id);
              const topRisk = topRiskOf(relatedRisks);
              /** 高风险默认开；看风险筛选时全开；点标记则就地反选 */
              const riskOpen = riskToggle[match.id] ?? (topRisk?.level === 'high' || expandRisk);
              return (
              <li
                key={match.id}
                id={`judgement-entry-${match.requirement_id}`}
                className={`entry entry--${match.status}${expanded === match.id ? ' entry--expanded' : ''}`}
              >
                <div
                  className="entry__head"
                  tabIndex={0}
                  role="button"
                  aria-expanded={expanded === match.id}
                  onClick={() => void openDetail(match)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault();
                      void openDetail(match);
                    }
                  }}
                >
                  <div className="entry__main">
                    {/* 状态标签放到标题行左侧：先看结论分档，再看需求 */}
                    <StatusBadge status={match.status} />
                    <span className="entry__title">{match.requirement?.title}</span>
                  </div>
                  {/* 匹配关系一行：结论 + 材料原文链接 + 依据入口 */}
                  <div className="entry__verdict">
                    <span className="entry__headline">{match.headline}</span>
                    <button
                      type="button"
                      className="link-btn"
                      title={[
                        match.requirement?.source.document_name,
                        match.requirement?.source.page ? `第 ${match.requirement.source.page} 页` : '',
                      ]
                        .filter(Boolean)
                        .join(' · ')}
                      onClick={(event) => {
                        event.stopPropagation();
                        window.dispatchEvent(
                          new CustomEvent('fitwise:open-assets', {
                            detail: {
                              materialId: match.requirement?.source.material_id,
                              page: match.requirement?.source.page ?? 1,
                            },
                          }),
                        );
                      }}
                    >
                      <IconEvidence width={13} height={13} />
                      原文
                      {match.requirement?.source.page ? ` 第 ${match.requirement.source.page} 页` : ''}
                    </button>
                    <span className="entry__basis">
                      {match.capability_doc_ids.length} 条依据
                      {match.case_ids.length ? ` · ${match.case_ids.length} 个案例` : ''}
                      <IconChevronDown
                        width={16}
                        height={16}
                        className={`basis-cell__chevron${
                          expanded === match.id ? ' basis-cell__chevron--open' : ''
                        }`}
                      />
                    </span>
                    {topRisk ? (
                      <button
                        type="button"
                        className={`entry__risk entry__risk--${topRisk.level}`}
                        onClick={(event) => {
                          event.stopPropagation();
                          setRiskToggle((prev) => ({ ...prev, [match.id]: !riskOpen }));
                        }}
                      >
                        {RISK_LEVEL_LABEL[topRisk.level]}风险
                        <IconChevronDown
                          width={14}
                          height={14}
                          className={`basis-cell__chevron${riskOpen ? ' basis-cell__chevron--open' : ''}`}
                        />
                      </button>
                    ) : null}
                  </div>
                </div>
                {/* 风险正文就地展开：高风险默认开，中低风险点标记才开 —— 不用跳到别的块 */}
                {relatedRisks.length && riskOpen ? (
                  <div className="entry__risk-body">
                    {relatedRisks.map((risk) => (
                      <div key={risk.title} className="entry__risk-item">
                        <p className="entry__risk-title">
                          <span className={`entry__risk-tag entry__risk-tag--${risk.level}`}>
                            {RISK_LEVEL_LABEL[risk.level]}
                          </span>
                          {risk.title}
                          {(risk.requirement_ids?.length ?? 0) > 1 ? (
                            <span className="hint hint--inline">
                              另涉及 {risk.requirement_ids!.length - 1} 条需求
                            </span>
                          ) : null}
                        </p>
                        {risk.mitigation ? (
                          <p className="entry__risk-fix">建议应对：{risk.mitigation}</p>
                        ) : null}
                      </div>
                    ))}
                  </div>
                ) : null}
                {expanded === match.id ? (
                  <div className="entry__detail">
                          {!detail ? (
                            <p className="empty-inline">加载中…</p>
                          ) : (
                            <div className="detail">
                              <div className="detail__judge">
                                 <h4>
                                   <IconTarget width={18} height={18} />
                                   为什么这样判断？
                                 </h4>
                                {/* 需求全文从行内挪到这里：行内只留标题，篇幅可控，信息不丢 */}
                                {match.requirement?.detail ? (
                                  <p className="detail__requirement">
                                    客户原话：{match.requirement.detail}
                                  </p>
                                ) : null}
                                 <p>{detail.rationale}</p>
                                <div className="detail__judge-meta">
                                  <StatusBadge status={detail.status} size="sm" />
                                  <span className="muted">{MATCH_STATUS_META[detail.status].description}</span>
                                  {/* 把握度不再展示模型自报的数字，改为证据统计（见 docs/agent-core-design.md） */}
                                  <span className="confidence">
                                    证据 {detail.evidences?.length ?? 0} 条
                                    {detail.self_check?.metrics
                                      ? ` · 支持 ${detail.self_check.metrics.unique_support ?? 0} · 限制 ${detail.self_check.metrics.constraints ?? 0}`
                                      : ''}
                                  </span>
                                  {detail.self_check?.flagged ? (
                                    <span className="confidence">自检标记，已按上限降级</span>
                                  ) : null}
                                  {detail.self_check?.reasons?.some((item) => item.code === 'llm_fallback') ? (
                                    <span className="confidence">本次为规则结果</span>
                                  ) : null}
                                </div>
                                {detail.self_check?.reasons?.length ? (
                                  <div className="detail__flags">
                                    <div className="flag-block flag-block--gap">
                                      <h5>自检结果</h5>
                                      <ul>
                                        {detail.self_check.reasons.map((item) => (
                                          <li key={item.code}>{item.detail}</li>
                                        ))}
                                      </ul>
                                    </div>
                                  </div>
                                ) : null}
                              </div>

                              <div className="detail__grid">
                                <div className="detail__block">
                                  <h4>
                                    <IconCheck width={18} height={18} />
                                    相关产品能力
                                  </h4>
                                  {detail.capability_docs?.length ? (
                                    <div className="doc-card-list">
                                      {detail.capability_docs.map((doc) => (
                                        <article key={doc.id} className="doc-card">
                                          <header className="doc-card__head">
                                            <span className="doc-card__product">{doc.product}</span>
                                            <span className="doc-card__meta">
                                              {doc.doc_type} · {doc.version}
                                            </span>
                                          </header>
                                          <p className="doc-card__title">{doc.title}</p>
                                          <dl className="doc-card__facts">
                                            <div>
                                              <dt>支持范围</dt>
                                              <dd>
                                                <ul>
                                                  {doc.supported_scope.slice(0, 3).map((scope) => (
                                                    <li key={scope}>{scope}</li>
                                                  ))}
                                                </ul>
                                              </dd>
                                            </div>
                                            <div>
                                              <dt>限制条件</dt>
                                              <dd>{doc.limitations.join('；') || '未标注'}</dd>
                                            </div>
                                            <div>
                                              <dt>部署方式</dt>
                                              <dd className="chip-row">
                                                {doc.deployment.slice(0, 4).map((item) => (
                                                  <Chip key={item}>{item}</Chip>
                                                ))}
                                              </dd>
                                            </div>
                                          </dl>
                                        </article>
                                      ))}
                                    </div>
                                  ) : (
                                    <p className="empty-inline">没有找到对应的产品资料</p>
                                  )}
                                </div>

                                <div className="detail__block">
                                  <h4>
                                    <IconEvidence width={18} height={18} />
                                    判断依据（
                                    {detail.evidences?.length ?? 0} 条）
                                  </h4>
                                  {detail.cases?.length ? (
                                    <div className="match-cases">
                                      <span className="match-cases__label">相关历史案例</span>
                                      <ul className="case-mini-list">
                                        {detail.cases.map((item) => (
                                          <li key={item.id}>{item.name}</li>
                                        ))}
                                      </ul>
                                    </div>
                                  ) : null}
                                  <details className="evidence-details">
                                    <summary>展开依据</summary>
                                    <ul className="evidence-list">
                                    {detail.evidences?.map((evidence) => (
                                      <li key={evidence.id} className="evidence-item">
                                        <div className="evidence-item__head">
                                          <span className={`evidence-type evidence-type--${evidence.source_type}`}>
                                            {evidence.source_type === 'customer'
                                              ? '客户材料'
                                              : evidence.source_type === 'capability'
                                                ? '产品资料'
                                                : '历史案例'}
                                          </span>
                                          <span className="evidence-item__doc">{evidence.document_name}</span>
                                          {evidence.page ? (
                                            <span className="evidence-item__page">第 {evidence.page} 页</span>
                                          ) : null}
                                        </div>
                                        <blockquote>{evidence.excerpt}</blockquote>
                                      </li>
                                    ))}
                                    </ul>
                                  </details>
                                  {/* 取证过程：Agent 化的可见证据 —— 查了什么、模型跑得怎么样、自检怎么判的 */}
                                  {detail.trace?.length ? (
                                    <details className="evidence-details">
                                      <summary>取证过程</summary>
                                      <ul className="evidence-list">
                                        {detail.trace.map((step, index) => (
                                          <li key={`${step.step}-${index}`} className="evidence-item">
                                            <div className="evidence-item__head">
                                              <span className="evidence-type">
                                                {TRACE_STEP_LABEL[step.step] ?? step.step}
                                              </span>
                                              {step.fallback_used ? (
                                                <span className="evidence-item__page">规则回退</span>
                                              ) : null}
                                              {step.flagged ? (
                                                <span className="evidence-item__page">自检标记</span>
                                              ) : null}
                                            </div>
                                            <p>{step.detail}</p>
                                          </li>
                                        ))}
                                      </ul>
                                    </details>
                                  ) : null}
                                </div>
                              </div>

                              {detail.gaps.length || detail.confirmations.length ? (
                                <div className="detail__flags">
                                  {detail.gaps.length ? (
                                    <div className="flag-block flag-block--gap">
                                      <h5>能力缺口 / 前置条件</h5>
                                      <ul>
                                        {detail.gaps.map((gap) => (
                                          <li key={gap}>{gap}</li>
                                        ))}
                                      </ul>
                                    </div>
                                  ) : null}
                                  {detail.confirmations.length ? (
                                    <div className="flag-block flag-block--confirm">
                                      <h5>
                                        <IconQuestion width={16} height={16} />
                                        前提
                                      </h5>
                                      <ul>
                                        {detail.confirmations.map((item) => (
                                          <li key={item}>{item}</li>
                                        ))}
                                      </ul>
                                      {/* 前提与需求确认页的「待澄清问题」是同一批东西：不逐条硬匹配（措辞常对不上），
                                          给一个整块入口，想看全部就去那边 */}
                                      {(project.open_questions ?? []).length ? (
                                        <button
                                          type="button"
                                          className="flag-block__link flag-block__link--block"
                                          onClick={() =>
                                            window.dispatchEvent(
                                              new CustomEvent('fitwise:open-project-tab', {
                                                detail: { tab: 'requirements', anchor: 'pending-questions' },
                                              }),
                                            )
                                          }
                                        >
                                          这些前提和需求确认页的「待澄清问题」是同一批 · 去看全部
                                        </button>
                                      ) : null}
                                    </div>
                                  ) : null}
                                </div>
                              ) : null}

                              <div className="detail__block detail__block--wide">
                                <h4>人工修正判断</h4>
                                <p className="muted">改完后系统会记录修改人、时间与原因。</p>
                                <div className="review-form">
                                  <select
                                    className="textarea"
                                    value={review.status}
                                    onChange={(event) =>
                                      setReview({ ...review, status: event.target.value as MatchStatus })
                                    }
                                  >
                                    {STATUS_ORDER.map((status) => (
                                      <option key={status} value={status}>
                                        {MATCH_STATUS_META[status].label}
                                      </option>
                                    ))}
                                  </select>
                                  <input
                                    className="textarea"
                                    placeholder="修改原因（例如：与研发确认后韩语不支持本期交付）"
                                    value={review.note}
                                    onChange={(event) => setReview({ ...review, note: event.target.value })}
                                  />
                                  <button
                                    type="button"
                                    className="btn btn--secondary btn--sm"
                                    onClick={async () => {
                                      await api.reviewMatch(detail.id, review);
                                      setDetail(await api.match(detail.id));
                                      await refresh();
                                    }}
                                  >
                                    保存
                                  </button>
                                </div>
                                {detail.judgment_source === 'human' ? (
                                  <p className="panel__foot-note">
                                    已由 {detail.reviewed_by} 修正
                                    {detail.reviewed_at ? `（${new Date(detail.reviewed_at).toLocaleString('zh-CN')}）` : ''}
                                    {detail.review_note ? `：${detail.review_note}` : ''}
                                  </p>
                                ) : null}
                              </div>
                            </div>
                          )}
                  </div>
                ) : null}
              </li>
              );
            })}
          </ul>
        </>
      )}
    </section>
  );
}
