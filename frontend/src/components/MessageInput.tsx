import { useState } from "react";

interface MessageInputProps {
  onSubmit: (situation: string, failedLog: string) => void;
  disabled: boolean;
}

export default function MessageInput({ onSubmit, disabled }: MessageInputProps) {
  const [situation, setSituation] = useState("");
  const [failedLog, setFailedLog] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!situation.trim() || !failedLog.trim() || disabled) return;
    onSubmit(situation.trim(), failedLog.trim());
    setSituation("");
    setFailedLog("");
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="bg-white border-t border-gray-200 p-4 space-y-3"
    >
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          测试情景
        </label>
        <textarea
          value={situation}
          onChange={(e) => setSituation(e.target.value)}
          placeholder="描述测试失败的情景..."
          rows={2}
          className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm resize-none"
          disabled={disabled}
        />
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          失败日志
        </label>
        <textarea
          value={failedLog}
          onChange={(e) => setFailedLog(e.target.value)}
          placeholder="粘贴测试失败日志..."
          rows={4}
          className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm resize-none font-mono"
          disabled={disabled}
        />
      </div>
      <button
        type="submit"
        disabled={disabled || !situation.trim() || !failedLog.trim()}
        className="w-full bg-blue-600 text-white py-2 rounded-md hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition text-sm font-medium"
      >
        {disabled ? "Agent 处理中..." : "提交分析"}
      </button>
    </form>
  );
}
