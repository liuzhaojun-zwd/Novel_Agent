/** Issue 9: Loading Skeleton 骨架屏组件 */
const CARD_WIDTHS = [92, 76, 86, 68];
const LIST_WIDTHS = [94, 82, 90, 74, 87];
const CHAPTER_WIDTHS = [95, 88, 79, 92, 72, 85, 67, 90];

export function CardSkeleton({ lines = 4 }) {
  return (
    <div className="bg-white rounded-xl p-6 shadow-sm border border-gray-100 animate-pulse">
      <div className="h-5 bg-gray-200 rounded w-1/3 mb-4" />
      {Array.from({ length: lines }).map((_, index) => (
        <div
          key={index}
          className="h-3 bg-gray-100 rounded mb-2"
          style={{ width: `${CARD_WIDTHS[index % CARD_WIDTHS.length]}%` }}
        />
      ))}
    </div>
  );
}

export function ListSkeleton({ count = 5 }) {
  return (
    <div className="space-y-2 animate-pulse">
      {Array.from({ length: count }).map((_, index) => (
        <div
          key={index}
          className="h-12 bg-gray-100 rounded-lg"
          style={{ width: `${LIST_WIDTHS[index % LIST_WIDTHS.length]}%` }}
        />
      ))}
    </div>
  );
}

export function ChapterSkeleton() {
  return (
    <div className="bg-white rounded-xl p-6 shadow-sm border border-gray-100 animate-pulse">
      <div className="h-6 bg-gray-200 rounded w-1/2 mb-3" />
      <div className="h-3 bg-gray-100 rounded w-1/4 mb-6" />
      {CHAPTER_WIDTHS.map((width, index) => (
        <div key={index} className="h-3 bg-gray-100 rounded mb-2" style={{ width: `${width}%` }} />
      ))}
    </div>
  );
}
