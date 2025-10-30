export default function IndicatorPanel({ data, onSelect }) {
  return (
    <div className="w-1/3 border-r p-4 overflow-y-auto">
      <h2 className="text-lg font-semibold mb-2">抽取指标</h2>
      {Object.entries(data).map(([metric, info]) => (
        <div
          key={metric}
          onClick={() => onSelect(info)}
          className="cursor-pointer hover:bg-gray-100 p-2 rounded"
        >
          <div className="font-medium">{metric}</div>
          <div className="text-sm text-gray-500">
            {info.value || '-'} {info.unit || ''} · {info.year || ''} · {info.confidence || ''}
          </div>
        </div>
      ))}
    </div>
  );
}
