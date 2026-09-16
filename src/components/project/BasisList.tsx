import type { MatchBasis, Material } from '../../api/types';
import { IconEvidence } from '../icons';

/**
 * 一条风险 / 行动的依据：先给判断（哪条需求、什么结论），再给证据。
 *
 * 客户材料那一侧能真的打开原文抽屉；企业能力库与案例没有可浏览的原文，
 * 所以只能给「文档名 + 页码 + 摘录」—— 这一点如实呈现，不假装能点开。
 */
export function BasisList({ basis, materials }: { basis?: MatchBasis[]; materials: Material[] }) {
  if (!basis?.length) return null;
  return (
    <div className="basis">
      <span className="basis__label">依据</span>
      {basis.map((item) => (
        <span key={item.requirement_id} className="basis__group">
          <span className="basis__requirement" title={item.headline}>
            {item.title}
          </span>
          {item.evidences.map((evidence, index) => {
            const materialId =
              evidence.source_type === 'customer'
                ? materials.find((material) => material.filename === evidence.document_name)?.id ?? null
                : null;
            const label = `${evidence.document_name}${evidence.page ? ` 第 ${evidence.page} 页` : ''}`;
            return materialId ? (
              <button
                key={`${item.requirement_id}-${index}`}
                type="button"
                className="link-btn basis__item"
                title={evidence.excerpt}
                onClick={() =>
                  window.dispatchEvent(
                    new CustomEvent('fitwise:open-assets', {
                      detail: { materialId, page: evidence.page ?? 1 },
                    }),
                  )
                }
              >
                <IconEvidence width={12} height={12} />
                {label}
              </button>
            ) : (
              <span key={`${item.requirement_id}-${index}`} className="basis__item basis__item--static" title={evidence.excerpt}>
                {label}
              </span>
            );
          })}
        </span>
      ))}
    </div>
  );
}
