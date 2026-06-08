import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Message, MessageContent, ToolUseBlock, ToolResultBlock, TextBlock } from "../types";

interface ChatWindowProps {
  messages: Message[];
  isLoading: boolean;
  onOpenReport?: (filename: string) => void;
}

function isToolUse(content: MessageContent): boolean {
  if (typeof content === "string") return false;
  return content.some((block) => block.type === "tool_use");
}

function getToolName(content: MessageContent): string {
  if (typeof content === "string") return "";
  const tool = content.find((block): block is ToolUseBlock => block.type === "tool_use");
  return tool?.name ?? "";
}

function getToolInput(content: MessageContent): Record<string, unknown> | null {
  if (typeof content === "string") return null;
  const tool = content.find((block): block is ToolUseBlock => block.type === "tool_use");
  return tool?.input ?? null;
}

function isToolResult(content: MessageContent): boolean {
  if (typeof content === "string") return false;
  return content.some((block) => block.type === "tool_result");
}

function getToolResultText(content: MessageContent): string {
  if (typeof content === "string") return content;
  const result = content.find((block): block is ToolResultBlock => block.type === "tool_result");
  return typeof result?.content === "string" ? result.content : "";
}

function getTextContent(content: MessageContent): string {
  if (typeof content === "string") return content;
  const textBlock = content.find((block): block is TextBlock => block.type === "text");
  return textBlock?.text ?? "";
}

function hasReportLink(text: string): boolean {
  return /reports\/\S+\.md/.test(text);
}

function ReportLink({ text, onOpenReport }: { text: string; onOpenReport?: (f: string) => void }) {
  if (!onOpenReport) return <>{text}</>;

  const parts: (string | JSX.Element)[] = [];
  const regex = /reports\/(\S+\.md)/g;
  let lastIndex = 0;
  let match;

  while ((match = regex.exec(text)) !== null) {
    const fullMatch = match[0];
    const filename = match[1];
    const start = match.index;

    if (start > lastIndex) {
      parts.push(text.slice(lastIndex, start));
    }
    parts.push(
      <button
        key={`${start}-${filename}`}
        onClick={() => onOpenReport(filename)}
        className="text-blue-600 hover:underline cursor-pointer font-medium"
      >
        {fullMatch}
      </button>
    );
    lastIndex = start + fullMatch.length;
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  return <>{parts}</>;
}

function TextBubble({ text, isUser, onOpenReport }: { text: string; isUser: boolean; onOpenReport?: (f: string) => void }) {
  const textHasReport = hasReportLink(text);

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} my-3`}>
      <div
        className={`max-w-[80%] px-4 py-2 rounded-lg whitespace-pre-wrap ${
          isUser
            ? "bg-blue-600 text-white rounded-br-none"
            : "bg-white text-gray-800 border border-gray-200 rounded-bl-none shadow-sm"
        }`}
      >
        {isUser || textHasReport ? (
          <ReportLink text={text} onOpenReport={onOpenReport} />
        ) : (
          <div className="prose prose-sm max-w-none">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {text}
            </ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  );
}

function ToolUseBadge({ tool }: { tool: ToolUseBlock }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="flex justify-center my-2 relative">
      <div
        className="bg-yellow-50 text-yellow-800 text-xs px-3 py-1 rounded-full border border-yellow-200 cursor-pointer select-none"
        onClick={() => setExpanded(!expanded)}
        title="点击查看参数"
      >
        Agent 正在调用工具: <strong>{tool.name}</strong>
        <span className="ml-1 text-yellow-600">{expanded ? "▲" : "▼"}</span>
      </div>
      {expanded && tool.input && (
        <div className="absolute top-full mt-1 z-10 bg-white border border-yellow-200 rounded-md shadow-lg p-3 text-xs text-gray-700 max-w-xs">
          <pre className="whitespace-pre-wrap break-all">{JSON.stringify(tool.input, null, 2)}</pre>
        </div>
      )}
    </div>
  );
}

function ToolResultBadge({ result, onOpenReport }: { result: ToolResultBlock; onOpenReport?: (f: string) => void }) {
  const [expanded, setExpanded] = useState(false);
  const text = typeof result.content === "string" ? result.content : "";
  const isError = text.includes("[Error]") || text.includes("失败");
  const showExpand = hasReportLink(text);

  return (
    <div className="flex flex-col items-center my-2">
      <div
        className={`text-xs px-3 py-1 rounded-full border cursor-pointer select-none ${
          isError
            ? "bg-red-50 text-red-800 border-red-200"
            : "bg-green-50 text-green-800 border-green-200"
        }`}
        onClick={() => setExpanded(!expanded)}
      >
        {isError ? "❌" : "✅"} 工具执行结果
        {showExpand && <span className="ml-1">{expanded ? "▲" : "▼"}</span>}
      </div>
      {expanded && (
        <div className="mt-2 bg-white border border-gray-200 rounded-md shadow-sm p-3 text-xs text-gray-700 max-w-[80%]">
          <ReportLink text={text} onOpenReport={onOpenReport} />
        </div>
      )}
    </div>
  );
}

function MessageBubble({ msg, onOpenReport }: { msg: Message; onOpenReport?: (f: string) => void }) {
  const isUser = msg.role === "user";

  if (typeof msg.content === "string") {
    return <TextBubble text={msg.content} isUser={isUser} onOpenReport={onOpenReport} />;
  }

  return (
    <div className="flex flex-col">
      {msg.content.map((block, idx) => {
        if (block.type === "text") {
          return <TextBubble key={idx} text={block.text} isUser={isUser} onOpenReport={onOpenReport} />;
        }
        if (block.type === "tool_use") {
          return <ToolUseBadge key={idx} tool={block} />;
        }
        if (block.type === "tool_result") {
          return <ToolResultBadge key={idx} result={block} onOpenReport={onOpenReport} />;
        }
        return null;
      })}
    </div>
  );
}

export default function ChatWindow({ messages, isLoading, onOpenReport }: ChatWindowProps) {
  return (
    <div className="flex-1 flex flex-col h-full bg-gray-50">
      <div className="flex-1 overflow-y-auto p-4">
        {messages.map((msg, idx) => (
          <MessageBubble key={idx} msg={msg} onOpenReport={onOpenReport} />
        ))}
        {isLoading && (
          <div className="flex justify-start my-3">
            <div className="bg-white border border-gray-200 rounded-lg rounded-bl-none px-4 py-2 shadow-sm">
              <div className="flex space-x-1">
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
