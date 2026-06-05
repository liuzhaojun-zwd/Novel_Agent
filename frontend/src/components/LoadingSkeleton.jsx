/** Issue 9: Loading Skeleton 骨架屏组件 */
export function CardSkeleton({ lines = 4 }) {
  return (
    <div className="bg-white rounded-xl p-6 shadow-sm border border-gray-100 animate-pulse">
      <div className="h-5 bg-gray-200 rounded w-1/3 mb-4" />
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          className="h-3 bg-gray-100 rounded mb-2"
          style={{ width: `${60 + Math.random() * 35}%` }}
        />
      ))}
    </div>
  );
}

export function ListSkeleton({ count = 5 }) {
  return (
    <div className="space-y-2 animate-pulse">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="h-12 bg-gray-100 rounded-lg" style={{ width: `${70 + Math.random() * 25}%` }} />
      ))}
    </div>
  );
}

export function ChapterSkeleton() {
  return (
    <div className="bg-white rounded-xl p-6 shadow-sm border border-gray-100 animate-pulse">
      <div className="h-6 bg-gray-200 rounded w-1/2 mb-3" />
      <div className="h-3 bg-gray-100 rounded w-1/4 mb-6" />
      {Array.from({ length: 8 }).map((_, i) => (
        <div
          key={i}
          className="h-3 bg-gray-100 rounded mb-2"
          style={{ width: `${50 + Math.random() * 45}%` }}
        />
      ))}
    </div>
  );
}