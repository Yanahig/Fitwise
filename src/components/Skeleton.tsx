/** 加载占位：用骨架屏替代「正在加载…」，避免页面跳动。 */
export function SkeletonCard({ rows = 3 }: { rows?: number }) {
  return (
    <div className="loading-card" aria-hidden="true">
      <div className="skeleton skeleton--title" />
      {Array.from({ length: rows }).map((_, index) => (
        <div key={index} className="skeleton skeleton--line" style={{ width: `${92 - index * 12}%` }} />
      ))}
    </div>
  );
}

export function SkeletonRows({ count = 4 }: { count?: number }) {
  return (
    <div className="list-shell" aria-hidden="true">
      {Array.from({ length: count }).map((_, index) => (
        <div key={index} className="list-row">
          <div className="list-row__main">
            <div className="skeleton skeleton--line" style={{ width: '38%', height: 14 }} />
            <div className="skeleton skeleton--line" style={{ width: '62%', marginTop: 8 }} />
          </div>
          <div className="skeleton" style={{ width: 72, height: 20 }} />
        </div>
      ))}
    </div>
  );
}
