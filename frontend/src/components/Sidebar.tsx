import type { Session } from "../types";

interface SidebarProps {
  sessions: Session[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
}

export default function Sidebar({ sessions, activeId, onSelect, onNew }: SidebarProps) {
  return (
    <div className="w-64 bg-gray-100 border-r border-gray-200 flex flex-col h-full">
      <div className="p-4 border-b border-gray-200">
        <h1 className="text-lg font-bold text-gray-800">znew Agent</h1>
        <button
          onClick={onNew}
          className="mt-3 w-full bg-blue-600 text-white py-2 rounded hover:bg-blue-700 transition"
        >
          + 新建会话
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {[...sessions].reverse().map((s) => (
          <button
            key={s.id}
            onClick={() => onSelect(s.id)}
            className={`w-full text-left px-3 py-2 rounded text-sm truncate transition ${
              s.id === activeId
                ? "bg-blue-100 text-blue-800 font-medium"
                : "text-gray-700 hover:bg-gray-200"
            }`}
          >
            <div className="truncate">{s.title}</div>
            <div className="text-xs text-gray-400 mt-0.5">
              {new Date(s.createdAt).toLocaleString()}
            </div>
          </button>
        ))}
        {sessions.length === 0 && (
          <div className="text-gray-400 text-sm text-center py-8">暂无历史会话</div>
        )}
      </div>
    </div>
  );
}
