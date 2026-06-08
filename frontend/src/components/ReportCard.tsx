interface ReportCardProps {
  reportPath: string;
  summary?: string;
}

export default function ReportCard({ reportPath, summary }: ReportCardProps) {
  const filename = reportPath.split("/").pop() ?? reportPath;
  return (
    <div className="bg-white border border-blue-200 rounded-lg p-3 my-2 shadow-sm">
      <div className="text-sm font-medium text-blue-800 mb-1">分析报告</div>
      {summary && <div className="text-xs text-gray-600 mb-2">{summary}</div>}
      <a
        href={`http://localhost:8000/api/reports/${encodeURIComponent(filename)}`}
        target="_blank"
        rel="noopener noreferrer"
        className="text-xs text-blue-600 hover:underline"
      >
        查看完整报告 →
      </a>
    </div>
  );
}
