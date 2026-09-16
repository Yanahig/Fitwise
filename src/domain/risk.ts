import type { Solution } from '../api/types';

/**
 * 风险的公共规则。
 *
 * 风险现在只在一个地方展示：挂在哪条需求上，就展开在那条需求的条目里。
 * 页面上不再有独立的「风险提示」板块 —— 想只看风险，用筛选栏的风险筛选。
 * 所以这里只有三个函数：排序、按需求取、按等级取。
 */

export type SolutionRisk = Solution['risks'][number];
export type RiskLevel = SolutionRisk['level'];

/** 排序权重：高 → 中 → 低 */
export const RISK_ORDER: Record<string, number> = { high: 0, medium: 1, low: 2 };
export const RISK_LEVEL_LABEL: Record<string, string> = { high: '高', medium: '中', low: '低' };
export const RISK_LEVELS: RiskLevel[] = ['high', 'medium', 'low'];

/** 一条需求上可能挂多条风险：行内标记只看等级最高的那条 */
export function topRiskOf(risks: SolutionRisk[]): SolutionRisk | undefined {
  return [...risks].sort((a, b) => (RISK_ORDER[a.level] ?? 9) - (RISK_ORDER[b.level] ?? 9))[0];
}

/** 挂到这条需求上的风险：按高 → 中 → 低排，一条需求有多条风险时读起来有次序 */
export function risksOfRequirement(risks: SolutionRisk[], requirementId: number): SolutionRisk[] {
  return risks
    .filter((risk) => (risk.requirement_ids ?? []).includes(requirementId))
    .sort((a, b) => (RISK_ORDER[a.level] ?? 9) - (RISK_ORDER[b.level] ?? 9));
}

/** 这条需求上最严重的风险等级权重：没有风险给 9（排在最后） */
export function riskRankOfRequirement(risks: SolutionRisk[], requirementId: number): number {
  const ranks = risksOfRequirement(risks, requirementId).map((risk) => RISK_ORDER[risk.level] ?? 9);
  return ranks.length ? Math.min(...ranks) : 9;
}

/** 某个等级命中的需求 id：筛选栏上的数字要和筛出来的行数完全一致 */
export function requirementIdsOfLevel(risks: SolutionRisk[], level: RiskLevel): Set<number> {
  const ids = new Set<number>();
  for (const risk of risks) {
    if (risk.level !== level) continue;
    for (const id of risk.requirement_ids ?? []) ids.add(id);
  }
  return ids;
}

/** 挂不到任何需求的风险（项目级）：条目里放不下，界面上单独兜底 */
export function unplacedRisks(risks: SolutionRisk[]): SolutionRisk[] {
  return risks.filter((risk) => (risk.requirement_ids ?? []).length === 0);
}
