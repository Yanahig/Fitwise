import { useEffect, useState } from 'react';
import { api } from '../../api/endpoints';
import type { Match, MatchStatus, Project } from '../../api/types';
import { MATCH_STATUS_META, STATUS_ORDER } from '../../domain/status';
import { Chip, StatusBadge } from '../badges';
import { IconCheck, IconEvidence, IconQuestion, IconTarget } from '../icons';

/** 取证轨迹的步骤名 → 人话 */
const TRACE_STEP_LABEL: Record<string, string> = {
  recall: '查资料',
  judge: '核对',
  guardrail: '核查',
  decide: '结论',
};

/**
 * 一条需求的判断详情：为什么这样判断、相关产品能力、依据与取证过程、人工修正。
 *
 * 它跟着需求卡片走 —— 结论和它的依据在同一张卡上，不再单独占一个板块。
 */
export function MatchDetail({
  project,
  match,
  onReviewed,
}: {
  project: Project;
  match: Match;
  /** 人工修正之后让外层刷新一次（卡片上的结论要跟着变） */
  onReviewed?: () => void | Promise<void>;
}) {
  const [detail, setDetail] = useState<Match | null>(null);
  const [review, setReview] = useState<{ status: MatchStatus; note: string }>({
    status: match.status,
    note: '',
  });

  useEffect(() => {
    let cancelled = false;
    setDetail(null);
    setReview({ status: match.status, note: '' });
    void api
      .match(match.id)
      .then((data) => {
        if (!cancelled) setDetail(data);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [match.id, match.status]);

  if (!detail) {
    return <p className="empty-inline">加载中…</p>;
  }

  return (
    <div className="detail">
      <div className="detail__judge">
        <h4>
          <IconTarget width={18} height={18} />
          为什么这样判断？
        </h4>
        {/* 需求全文放在这里：卡片上只留标题，篇幅可控，信息不丢 */}
        {detail.requirement?.detail ? (
          <p className="detail__requirement">客户原话：{detail.requirement.detail}</p>
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
            <span className="confidence">核查有提示，结论已按更保守的口径给出</span>
          ) : null}
          {detail.self_check?.reasons?.some((item) => item.code === 'llm_fallback') ? (
            <span className="confidence">本次未用 AI，按既定规则给出</span>
          ) : null}
        </div>
        {detail.self_check?.reasons?.length ? (
          <div className="detail__flags">
            <div className="flag-block flag-block--gap">
              <h5>核查提示</h5>
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
                      <span className="evidence-type">{TRACE_STEP_LABEL[step.step] ?? step.step}</span>
                      {step.fallback_used ? <span className="evidence-item__page">规则回退</span> : null}
                      {step.flagged ? <span className="evidence-item__page">自检标记</span> : null}
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
              {/* 前提要去问谁、完整清单长什么样，都在售前建议的「要问谁」里 ——
                  问题池只有一个家，这里给一个整块入口，不逐条硬匹配 */}
              {(project.open_questions ?? []).length ? (
                <button
                  type="button"
                  className="flag-block__link flag-block__link--block"
                  onClick={() =>
                    window.dispatchEvent(
                      new CustomEvent('fitwise:open-project-tab', {
                        detail: { tab: 'judgement', anchor: 'judgement-actions' },
                      }),
                    )
                  }
                >
                  这些前提要去问谁，在售前建议的「要问谁」里 · 去看全部
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
            onChange={(event) => setReview({ ...review, status: event.target.value as MatchStatus })}
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
              await onReviewed?.();
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
  );
}
