import type { Match, MatchBasis, Project } from '../api/types';
import { actionLabel, summarizeOpenQuestion } from './openQuestions';

/**
 * 问题池的唯一出口：还没定的事，按「问谁」分成三组。
 *
 * 能力匹配页、售前建议页、项目栏徽标都读这一份 —— 同一个数字在两处不会算出两个值。
 * 三类内容的来源：需求阶段的问题（自带 owner）、方案阶段的问题（对客 / 内部两拨）、
 * 判断给出的前提（暂不支持与待补依据的条目各自要问清的事）。
 */

export interface ActionRow {
  /** 一句话说清要确认 / 要做的事 */
  text: string;
  /** 左侧小标题：这条要问的是哪一类事（集成对接 / 验收口径…） */
  tag: string;
  owner?: string;
  /** 这条不确认会影响什么：改能力结论，还是只改承诺口径 */
  impact?: 'judge' | 'promise';
  due?: string;
  priority?: string;
  basis?: MatchBasis[];
}

export interface ActionGroups {
  customer: ActionRow[];
  internal: ActionRow[];
  sales: ActionRow[];
  /** 三组之和：项目栏上「售前建议」徽标读的就是它 */
  total: number;
  /** 判断给出的前提：对客沟通时要一起问，它们直接决定结论成不成立 */
  confirmations: string[];
}

export function buildActionGroups(project: Project, matches: Match[]): ActionGroups {
  const solution = project.solution;
  const seen = new Set<string>();
  const push = (rows: ActionRow[], row: ActionRow) => {
    const key = row.text.trim();
    if (!key || seen.has(key)) return;
    seen.add(key);
    rows.push(row);
  };

  const confirmations = [
    ...matches.filter((item) => item.status === 'none').flatMap((item) => item.confirmations),
    ...matches.filter((item) => item.status === 'unknown').flatMap((item) => item.confirmations),
  ].filter((item, index, list) => item && list.indexOf(item) === index);

  const customer: ActionRow[] = [];
  const internal: ActionRow[] = [];

  // 需求阶段的问题自带 owner：标「内部」的进内部清单，不再混进客户清单
  for (const question of project.open_questions ?? []) {
    const insight = summarizeOpenQuestion(question);
    const row: ActionRow = {
      text: question.question,
      tag: insight.label,
      owner: question.owner || '客户',
      impact: insight.affectsJudgement ? 'judge' : 'promise',
    };
    push((question.owner || '客户') === '内部' ? internal : customer, row);
  }
  for (const item of solution?.ask_customer ?? []) {
    push(customer, { text: item, tag: actionLabel(item) });
  }
  // 前提与判断绑定：结论成不成立取决于它，所以在客户清单里标「影响判断」
  for (const item of confirmations) {
    push(customer, { text: item, tag: actionLabel(item), impact: 'judge' });
  }
  for (const item of solution?.ask_internal ?? []) {
    push(internal, { text: item.question, tag: actionLabel(item.question), owner: item.owner });
  }

  const sales: ActionRow[] = (solution?.next_actions ?? []).map((item) => ({
    text: item.action,
    tag: actionLabel(item.action),
    owner: item.owner,
    due: item.due,
    priority: item.priority,
    basis: item.basis,
  }));

  return {
    customer,
    internal,
    sales,
    total: customer.length + internal.length + sales.length,
    confirmations,
  };
}

/** 承诺边界：能力缺口与待补依据在没有定论前，什么不能承诺 */
export function promiseBoundaries(matches: Match[]): string[] {
  const gaps = matches.filter((item) => item.status === 'none');
  const unknown = matches.filter((item) => item.status === 'unknown');
  return [
    gaps.length
      ? `能力缺口（${gaps
          .slice(0, 2)
          .map((item) => item.requirement?.title)
          .join('、')}）确认前，不承诺对应功能的交付时间与准确率`
      : '',
    unknown.length ? '还没依据的条目先按「待补依据」对客沟通，不做正面承诺' : '',
  ].filter(Boolean);
}
