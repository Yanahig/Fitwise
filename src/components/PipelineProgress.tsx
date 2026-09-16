/** 一个处理阶段：id 用于定位，label 是给人看的名字，detail 是这一步在做什么 */
export interface PipelineStage {
  id: string;
  label: string;
  detail: string;
}

/**
 * 处理进度：让售前看到「系统正在做什么」，而不是一个转圈的 loading。
 * 文案一律用业务语言（读材料 / 整理需求 / 判断能不能做）。
 */
export function PipelineProgress({
  stages,
  currentIndex,
  title,
}: {
  stages: PipelineStage[];
  currentIndex: number;
  title: string;
}) {
  const total = stages.length;
  const reached = Math.min(currentIndex, total);
  const percent = Math.round((reached / total) * 100);

  return (
    <div className="pipeline" role="status" aria-live="polite">
      <p className="pipeline__title">{title}</p>
      <div className="progress-track" aria-hidden="true">
        <div className="progress-track__fill" style={{ width: `${percent}%` }} />
      </div>
      <div className="progress-track__meta">
        <span>
          第 {Math.min(currentIndex + 1, total)}/{total} 步
        </span>
        <span>{percent}%</span>
      </div>
      <ol className="pipeline__list">
        {stages.map((stage, index) => {
          const state = index < currentIndex ? 'done' : index === currentIndex ? 'active' : 'todo';
          return (
            <li key={stage.id} className={`pipeline__item pipeline__item--${state}`}>
              <span className="pipeline__dot" aria-hidden="true" />
              <div>
                {/* 标题已经说过的话不再重复一遍 */}
                {stage.label === title ? null : <p className="pipeline__label">{stage.label}</p>}
                <p className="pipeline__detail">{stage.detail}</p>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/** 后台任务类型 → 售前看得懂的说法 */
const JOB_LABELS: Record<string, { title: string; detail: string }> = {
  'requirements.extract': { title: '正在整理客户需求', detail: '读完材料，整理出需求条目' },
  'matches.run': { title: '正在判断需求能不能做', detail: '逐条对照产品能力与历史案例' },
  'solutions.generate': { title: '正在生成解决路径', detail: '汇总判断结论并给出推进建议' },
};

export function jobLabel(kind: string): { title: string; detail: string } {
  return JOB_LABELS[kind] ?? { title: '系统正在处理', detail: '处理完成后会自动刷新' };
}
