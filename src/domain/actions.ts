import type { AskCustomerItem, Match, MatchBasis, Project, SyncSalesItem } from '../api/types';
import { actionLabel, summarizeOpenQuestion } from './openQuestions';

/**
 * 问题池的唯一出口：还没定的事，按「问谁」分成三组，外加一份执行清单。
 *
 * 能力匹配页、售前建议页、项目栏徽标都读这一份 —— 同一个数字在两处不会算出两个值。
 * 三类内容的来源：需求阶段的问题（自带 owner）、方案阶段的三份清单（对客 / 内部 / 同步销售）、
 * 判断给出的前提（不确认，能力结论就不成立）。
 *
 * 「要同步销售」是**信息**不是待办（承诺边界、报价与周期口径），数据来自 solution.sync_sales；
 * 「下一步行动」是执行清单（先办哪件、谁办、什么时候），来自 solution.next_actions。
 * 两者混在一栏里过：通用待办被当成"要同步给销售的信息"，一组里既出现"向客户发清单"、
 * 又出现"平台研发核实"。见 docs/information-hierarchy.md 第四十二轮。
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
  /** 要同步销售的那条：为什么必须同步（不同步会出什么事） */
  note?: string;
  basis?: MatchBasis[];
}

export interface ActionGroups {
  customer: ActionRow[];
  internal: ActionRow[];
  /** 要同步销售：给销售 / 商务的信息，不是待办 */
  sales: ActionRow[];
  /** 下一步行动：先办哪几件、谁办、什么时候 */
  nextActions: ActionRow[];
  /** 要问客户 + 要问内部 + 要同步销售：项目栏上「售前建议」徽标读的就是它 */
  total: number;
  /** 判断给出的前提：对客沟通时要一起问，它们直接决定结论成不成立 */
  confirmations: string[];
}

/** 动作排序权重：高 → 中 → 低；没写 priority 的按中处理 */
const ACTION_RANK: Record<string, number> = { high: 0, medium: 1, low: 2 };

/**
 * 截止时间可能是两种写法：绝对日期（2026-06-30）或相对口径（3个工作日内）。
 * 两者量纲不同，不做换算 —— 只把同类的拿来比，不同类的保持模型给的先后。
 */
const dueKey = (due: string | undefined): number | null => {
  if (!due) return null;
  const iso = due.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (iso) return Number(`${iso[1]}${iso[2]}${iso[3]}`);
  const workdays = due.match(/(\d+)\s*个?工作日/);
  return workdays ? Number(workdays[1]) : null;
};

const isIsoDate = (due: string | undefined) => Boolean(due && /^\d{4}-\d{2}-\d{2}/.test(due));

/** 展示用：日期只留 月-日；「3个工作日内」这类说法原样保留（太长就截断） */
export const dueLabel = (due: string | undefined): string => {
  if (!due) return '';
  if (isIsoDate(due)) return due.slice(5, 10);
  return due.length > 6 ? `${due.slice(0, 6)}…` : due;
};

/** 老数据的 ask_customer 是字符串数组，新数据是带 covers 的对象 —— 统一成对象再处理 */
const askCustomerRows = (items: (string | AskCustomerItem)[] | undefined): AskCustomerItem[] =>
  (items ?? [])
    .map((item) => (typeof item === 'string' ? { question: item } : item))
    .filter((item) => Boolean(item?.question?.trim()));

/**
 * 判断给出的前提：三种档位都要问，只是影响的东西不同。
 * hard = 不确认能力结论本身就不成立（暂不支持 / 待补依据），部分支持的前提只影响承诺口径。
 */
const premiseRows = (matches: Match[]) =>
  matches.flatMap((item) => {
    if (!['none', 'unknown', 'partial'].includes(item.status)) return [];
    return (item.confirmations ?? [])
      .filter(Boolean)
      .map((text) => ({
        text,
        requirementId: item.requirement_id,
        hard: item.status !== 'partial',
      }));
  });

/**
 * 模型没给 sync_sales（老数据、或模型漏写）时的兜底：从判断结果直接推。
 *
 * 与后端 `_derive_sync_sales` 同一套口径 —— 只做站得住的推导，保证这一组不会空着。
 */
function deriveSyncSales(matches: Match[]): SyncSalesItem[] {
  const rows: SyncSalesItem[] = [];
  const seen = new Set<string>();
  const push = (item: SyncSalesItem) => {
    const key = item.info.trim();
    if (!key || seen.has(key)) return;
    seen.add(key);
    rows.push(item);
  };
  for (const match of matches) {
    const title = match.requirement?.title ?? '这条需求';
    if (match.status === 'none') {
      push({
        info: `「${title}」目前没有能力依据，对客户先按暂不支持讲，不要正面承诺。`,
        to: '销售',
        why: '销售先许了口，方案与交付兜不住时只能由公司背。',
        urgency: 'high',
      });
    } else if (match.status === 'unknown') {
      push({
        info: `「${title}」的证据还没补齐，对客户先按待补依据讲，等内部确认口径后再表态。`,
        to: '销售',
        why: '结论没定就表态，后面要么改口、要么硬做。',
        urgency: 'medium',
      });
    } else if (match.status === 'partial' && match.condition) {
      push({
        info: `「${title}」的结论带前置条件：${match.condition}`,
        to: '售前负责人',
        why: '不带上这个前提对外说，会被当成无条件承诺。',
        urgency: 'medium',
      });
    }
  }
  return rows;
}

/**
 * 下一步行动的排序：先看优先级，再看截止时间（同一种写法才比，越早越前）。
 * 结论条「下一步」那一句取的就是排完序的第一条 —— 顺序必须是"最该先做的排最前"，
 * 而不是模型写出来的先后；不同写法的截止时间互不比较，保持原顺序（稳定排序）。
 */
const byPriorityThenDue = (a: ActionRow, b: ActionRow): number => {
  const rank = (row: ActionRow) => ACTION_RANK[row.priority ?? ''] ?? 1;
  if (rank(a) !== rank(b)) return rank(a) - rank(b);
  const aKey = dueKey(a.due);
  const bKey = dueKey(b.due);
  if (aKey === null || bKey === null) return 0;
  if (isIsoDate(a.due) !== isIsoDate(b.due)) return 0;
  return aKey - bKey;
};

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

  const asked = askCustomerRows(solution?.ask_customer);
  /**
   * 这一版建议的对客清单是否由模型合并过：新数据每条都带 covers（哪怕是空数组）。
   * 合并过 → 需求阶段的问题与判断前提都并进它了，前端只补它漏掉的前提；
   * 老数据（纯字符串数组）→ 仍旧三段相加，宁可有重复，也不能把问题弄丢。
   */
  const mergedByModel = asked.some((item) => Array.isArray(item.covers));
  const covered = new Set(asked.flatMap((item) => item.covers ?? []));

  const premises = premiseRows(matches);
  const customerPremises = mergedByModel
    ? premises.filter((item) => !covered.has(item.requirementId))
    : premises.filter((item) => item.hard);

  // 需求阶段的问题自带 owner：标「内部」的进内部清单，不再混进客户清单
  for (const question of project.open_questions ?? []) {
    if ((question.owner || '客户') === '内部') {
      push(internal, {
        text: question.question,
        tag: summarizeOpenQuestion(question).label,
        owner: '内部',
      });
      continue;
    }
    // 合并过对客清单之后，需求阶段的问题由 solution.ask_customer 承担，不再重复陈列
    if (mergedByModel) continue;
    const insight = summarizeOpenQuestion(question);
    push(customer, {
      text: question.question,
      tag: insight.label,
      owner: question.owner || '客户',
      impact: insight.affectsJudgement ? 'judge' : 'promise',
    });
  }

  for (const item of asked) {
    push(customer, {
      text: item.question,
      tag: actionLabel(item.question),
      impact: item.affects === 'judge' ? 'judge' : item.affects === 'promise' ? 'promise' : undefined,
    });
  }

  // 前提与判断绑定：结论成不成立取决于它，所以在客户清单里标「影响判断」
  for (const item of customerPremises) {
    const insight = summarizeOpenQuestion({ question: item.text, why: '', owner: '客户' });
    push(customer, {
      text: item.text,
      // 小标题用 actionLabel：summarizeOpenQuestion 认不出来会给「其他」，那个词放在清单里没意义
      tag: actionLabel(item.text),
      impact: item.hard || insight.affectsJudgement ? 'judge' : 'promise',
    });
  }

  for (const item of solution?.ask_internal ?? []) {
    push(internal, { text: item.question, tag: actionLabel(item.question), owner: item.owner });
  }

  // 要同步销售：给销售 / 商务的信息（模型给什么用什么，没给就按判断结果推）
  const syncRows = solution?.sync_sales?.length ? solution.sync_sales : deriveSyncSales(matches);
  const sales: ActionRow[] = syncRows.map((item) => ({
    text: item.info,
    tag: actionLabel(item.info),
    owner: `同步给 ${item.to}`,
    priority: item.urgency,
    note: item.why,
  }));

  // 下一步行动：执行清单，独立于"还没定的事"
  const nextActions: ActionRow[] = (solution?.next_actions ?? [])
    .map((item) => ({
      text: item.action,
      tag: actionLabel(item.action),
      owner: item.owner,
      due: item.due,
      priority: item.priority,
      basis: item.basis,
    }))
    .sort(byPriorityThenDue);

  return {
    customer,
    internal,
    sales,
    nextActions,
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
