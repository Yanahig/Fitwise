import { HelpTip } from '../HelpTip';

/** 概括行每句限制字数：一句一行，太长会折行；完整内容就在下面的分区里 */
const SUMMARY_LIMIT = 30;

function trim(text: string): string {
  return text.length > SUMMARY_LIMIT ? `${text.slice(0, SUMMARY_LIMIT)}…` : text;
}

export interface SummaryLine {
  label: string;
  text: string;
  /** 点这一句跳到下面的分区（锚点 id） */
  target?: string;
  /** 或者跳到另一页（hash 路由） */
  href?: string;
  /** 或者就地触发一个动作（例如把「能不能做」切到高风险视图） */
  onClick?: () => void;
}

/**
 * 三个功能页共用的结论条：一句结论 + 依据行 + 概括行（可点）+ 数字 + 主动作。
 *
 * 它是"这一页的答案"和"目录"：结论在上、数字在右，概括行各自指向下面的分区。
 * 三页用同一个组件，是为了让用户在三个页面上看到的骨架完全一致 —— 只有内容不同。
 */
export function SummaryBar({
  tone = 'info',
  verdict,
  sub,
  lines = [],
  metrics = [],
  metricsHint,
  subHint,
  action,
  extra,
  secondary,
}: {
  tone?: 'ok' | 'info' | 'warn';
  verdict: string;
  sub?: string;
  lines?: SummaryLine[];
  metrics?: { value: string; label: string }[];
  metricsHint?: string;
  /** 依据行末尾的口径说明（不影响高度，鼠标悬停才展开） */
  subHint?: string;
  action?: { label: string; onClick: () => void; disabled?: boolean };
  /** 本页的第二个动作（例如「复制建议」），排在主动作右边、下页跳转左边 */
  extra?: { label: string; onClick: () => void };
  /** 右侧固定是「去下一页 / 下一段」 */
  secondary?: { label: string; onClick: () => void };
}) {
  const go = (line: SummaryLine) => {
    if (line.onClick) {
      line.onClick();
      return;
    }
    if (line.href) {
      window.location.hash = line.href;
      return;
    }
    if (line.target) {
      document.getElementById(line.target)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };

  return (
    <section className={`verdict verdict--${tone}`}>
      <div>
        <h2 className="verdict__title">{verdict}</h2>
        {sub ? (
          <p className="verdict__sub">
            {sub}
            {subHint ? <HelpTip text={subHint} /> : null}
          </p>
        ) : null}
        {lines.length ? (
          <ul className="verdict__summary">
            {lines.map((line) => (
              <li key={line.label}>
                <button
                  type="button"
                  className="verdict__summary-item"
                  disabled={!line.target && !line.href && !line.onClick}
                  onClick={() => go(line)}
                >
                  <span className="verdict__summary-label">{line.label}</span>
                  <span className="verdict__summary-text" title={line.text}>
                    {trim(line.text)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
      <div className="verdict__side">
        {metrics.length ? (
          <div className="verdict__metrics">
            {metrics.map((metric) => (
              <div key={metric.label}>
                <span className="metric__value">{metric.value}</span>
                <span className="metric__label">{metric.label}</span>
              </div>
            ))}
            {metricsHint ? <HelpTip text={metricsHint} /> : null}
          </div>
        ) : null}
        <div className="section-open__actions">
          {action ? (
            <button
              type="button"
              className="btn btn--primary btn--sm"
              disabled={action.disabled}
              onClick={action.onClick}
            >
              {action.label}
            </button>
          ) : null}
          {extra ? (
            <button type="button" className="btn btn--secondary btn--sm" onClick={extra.onClick}>
              {extra.label}
            </button>
          ) : null}
          {secondary ? (
            <button type="button" className="btn btn--ghost btn--sm" onClick={secondary.onClick}>
              {secondary.label}
            </button>
          ) : null}
        </div>
      </div>
    </section>
  );
}
