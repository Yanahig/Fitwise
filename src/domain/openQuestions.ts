import type { OpenQuestion } from '../api/types';

/**
 * 待确认问题的归类。
 *
 * 需求页只展示"会影响判断"的那几条（范围、规模、集成）：这些不确认，
 * 我们对"客户要什么、能不能做"的判断就是虚的；其余（验收、交付、合规、定制边界）
 * 属于承诺口径，统一放在售前建议页的「向客户对齐」里。
 *
 * 现在用关键词规则兜底；等后端在 open_questions 上给出 impact 标记后，
 * 只需替换这里的实现，页面不用动。
 */

export interface OpenQuestionInsight {
  label: string;
  /** 一句话说明这条为什么重要：优先用 AI 给的 why，没有就退回问题本身 */
  impact: string;
  /** 是否会影响"客户要什么 / 我们能不能做"的判断 */
  affectsJudgement: boolean;
}

/**
 * 顺序即优先级：越靠前越具体。验收、合规、定制这类"承诺口径"要先于
 * 范围/规模判断，否则「按票种抽样」会被误判成票据范围问题。
 */
const LABELS: { label: string; test: RegExp }[] = [
  { label: '验收口径', test: /验收|抽样|抽检|准确率|口径|阈值/ },
  { label: '合规要求', test: /等保|日志|留存|备案|合规/ },
  { label: '定制边界', test: /定制|变更|实施期/ },
  { label: '部署环境', test: /服务器|存储|信创|鲲鹏|达梦|版本|环境/ },
  { label: '集成对接', test: /接口|对接|联调|认证|限流|第三方/ },
  { label: '范围清单', test: /哪几类|类型清单|票据清单|档案类型|票据类型|票种/ },
  { label: '工期安排', test: /工期|项目周期|上线时间|初验|里程碑/ },
  { label: '处理规模', test: /峰值|并发|QPS|处理量|页数|占比/ },
];

/** 只有这三类会改变需求判断本身，其余只影响承诺与交付口径 */
const JUDGEMENT_LABELS = new Set(['集成对接', '范围清单', '处理规模']);

/**
 * 给一条行动建议/待确认项打左侧小标题：让人一眼看出"这条要确认的是什么"。
 * 复用上面同一套关键词表；认不出来时用「细节确认」，不硬凑一个不准确的分类。
 */
export function actionLabel(text: string): string {
  const matched = LABELS.find((item) => item.test.test(text || ''));
  return matched?.label ?? '细节确认';
}

export function summarizeOpenQuestion(question: OpenQuestion): OpenQuestionInsight {
  /**
   * 只拿问题本身去匹配分类。
   *
   * 之前把 why 一起拼进来，结果说明里出现的词会喧宾夺主：例如"2023 年 V2 版本接口清单"
   * 命中「部署环境」的"版本"，把一条对接类问题判成了不影响判断。why 是给人读的解释，
   * 不是分类依据。
   */
  const text = question.question;
  const matched = LABELS.find((item) => item.test.test(text));
  const label = matched?.label ?? '其他';
  return {
    label,
    impact: (question.why || question.question).trim(),
    affectsJudgement: JUDGEMENT_LABELS.has(label),
  };
}

export function summarizeOpenQuestions(list: OpenQuestion[]): OpenQuestionInsight[] {
  return list.map(summarizeOpenQuestion);
}

/** 需求页要展示的关键缺口：只取会影响判断的，最多 limit 条 */
export function pickJudgementGaps(list: OpenQuestion[], limit = 3): OpenQuestionInsight[] {
  return summarizeOpenQuestions(list)
    .filter((item) => item.affectsJudgement)
    .slice(0, limit);
}
