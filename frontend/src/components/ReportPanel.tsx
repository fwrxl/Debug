import { useState, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { getReport } from "../services/api";

interface ReportPanelProps {
  filename: string | null;
  onClose: () => void;
}

export default function ReportPanel({ filename, onClose }: ReportPanelProps) {
  const [content, setContent] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!filename) {
      setContent("");
      setError(null);
      return;
    }

    setLoading(true);
    setError(null);
    getReport(filename)
      .then((text) => setContent(text))
      .catch((err) => setError(String(err)))
      .finally(() => setLoading(false));
  }, [filename]);

  if (!filename) return null;

  return (
    <>
      {/* 遮罩层 */}
      <div
        className="fixed inset-0 bg-black/20 z-40"
        onClick={onClose}
      />
      {/* 抽屉面板 */}
      <div className="fixed right-0 top-0 h-full w-[600px] max-w-[90vw] bg-white shadow-xl z-50 flex flex-col">
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200">
          <h2 className="text-sm font-semibold text-gray-800 truncate">
            📄 {filename}
          </h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-xl leading-none"
          >
            ×
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-6">
          {loading && (
            <div className="flex items-center justify-center h-32 text-gray-400 text-sm">
              加载中...
            </div>
          )}
          {error && (
            <div className="bg-red-50 text-red-700 p-4 rounded text-sm">
              加载失败: {error}
            </div>
          )}
          {!loading && !error && (
            <div className="prose prose-sm max-w-none">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {content}
              </ReactMarkdown>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
