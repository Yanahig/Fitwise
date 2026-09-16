import type { MatchStatus, Priority } from '../api/types';

export interface MatchStatusMeta {
  label: string;
  /** 表格中的短标签，例如 “需确认” */
  shortLabel: string;
  description: string;
  tone: 'success' | 'warning' | 'danger' | 'neutral';
}

export const MATCH_STATUS_META: Record<MatchStatus, MatchStatusMeta> = {
  full: {
    label: '完全支持',
    shortLabel: '完全支持',
    description: '产品现成能做，也有做过类似项目的经验，可以直接写进方案。',
    tone: 'success',
  },
  partial: {
    label: '部分支持',
    shortLabel: '部分支持',
    description: '能做一部分，但有前提条件（比如语言范围、处理量、准确率），要先确认。',
    tone: 'warning',
  },
  none: {
    label: '暂不支持',
    shortLabel: '暂不支持',
    description: '现在没有现成能力，只能走定制开发，或者和客户谈替代方案。',
    tone: 'danger',
  },
  unknown: {
    label: '信息不足，待补依据',
    shortLabel: '待补依据',
    description: '客户材料或我们自己的资料里找不到足够依据，先不给结论 —— 补齐依据或问清客户，再下判断。',
    tone: 'neutral',
  },
};

/**
 * 四档的统一顺序：**越靠前越需要人管** —— 待补依据（没依据）→ 暂不支持（能力缺口）
 * → 部分支持（有前提）→ 完全支持（可直接写进方案）。
 *
 * 筛选胶囊、判断条目列表、工作台图例共用这一份顺序，页面从头到尾读起来是同一条线。
 */
export const STATUS_ORDER: MatchStatus[] = ['unknown', 'none', 'partial', 'full'];

/** 排序权重，与 STATUS_ORDER 一一对应（列表排序用，避免每次 indexOf） */
export const STATUS_RANK: Record<MatchStatus, number> = {
  unknown: 0,
  none: 1,
  partial: 2,
  full: 3,
};

export const PRIORITY_META: Record<Priority, { label: string; tone: 'high' | 'medium' | 'low' }> = {
  high: { label: '高', tone: 'high' },
  medium: { label: '中', tone: 'medium' },
  low: { label: '低', tone: 'low' },
};

/** 条目左侧的优先级小徽标：需求确认与判断条目共用同一套写法 */
export const PRIORITY_TAG: Record<Priority, string> = { high: 'P0', medium: 'P1', low: 'P2' };

export function countByStatus(statuses: MatchStatus[]): Record<MatchStatus, number> {
  const initial: Record<MatchStatus, number> = { full: 0, partial: 0, none: 0, unknown: 0 };
  for (const status of statuses) initial[status] += 1;
  return initial;
}
