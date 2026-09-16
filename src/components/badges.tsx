import type { MatchStatus } from '../api/types';
import { MATCH_STATUS_META } from '../domain/status';
import { IconCheck, IconAlert, IconQuestion, IconClose } from './icons';

export function StatusBadge({ status, size = 'md' }: { status: MatchStatus; size?: 'sm' | 'md' }) {
  const meta = MATCH_STATUS_META[status];
  const Icon = status === 'full' ? IconCheck : status === 'partial' ? IconAlert : status === 'none' ? IconClose : IconQuestion;
  /* 含义不做常驻说明：鼠标停在标签上出气泡 */
  return (
    <span
      className={`status-badge status-badge--${meta.tone} status-badge--${size}`}
      title={`${meta.label}：${meta.description}`}
    >
      <Icon width={size === 'sm' ? 14 : 16} height={size === 'sm' ? 14 : 16} />
      {/* 徽标用短标签；完整说法（如「信息不足，待补依据」）留给说明与下拉选项 */}
      {meta.shortLabel}
    </span>
  );
}

export function Chip({ children, tone = 'default' }: { children: React.ReactNode; tone?: 'default' | 'accent' }) {
  return <span className={`chip chip--${tone}`}>{children}</span>;
}
