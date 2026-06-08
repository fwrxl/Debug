import { useState, useCallback } from "react";
import Sidebar from "./components/Sidebar";
import ChatWindow from "./components/ChatWindow";
import MessageInput from "./components/MessageInput";
import ReportPanel from "./components/ReportPanel";
import { getSessions, saveSessions, createSession, updateSession } from "./stores/history";
import { analyzeStream } from "./services/api";
import type { Session } from "./types";

export default function App() {
  const [sessions, setSessions] = useState<Session[]>(() => getSessions());
  const [activeId, setActiveId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [reportFilename, setReportFilename] = useState<string | null>(null);

  const activeSession = sessions.find((s) => s.id === activeId) ?? null;

  const handleNew = useCallback(() => {
    const newSession = createSession("新会话");
    const next = [...sessions, newSession];
    setSessions(next);
    saveSessions(next);
    setActiveId(newSession.id);
  }, [sessions]);

  const handleSelect = useCallback((id: string) => {
    setActiveId(id);
  }, []);

  const handleOpenReport = useCallback((filename: string) => {
    setReportFilename(filename);
  }, []);

  const handleCloseReport = useCallback(() => {
    setReportFilename(null);
  }, []);

  const handleSubmit = useCallback(
    async (situation: string, failedLog: string) => {
      const userContent = `情景：${situation}\n失败日志：${failedLog}`;
      let sessionId = "";

      setSessions((prev) => {
        let next: Session[];
        if (activeSession) {
          const newTitle = activeSession.title === "新会话"
            ? `情景：${situation}`.slice(0, 20) + (situation.length > 17 ? "..." : "")
            : activeSession.title;
          const updated = {
            ...activeSession,
            title: newTitle,
            messages: [
              ...activeSession.messages,
              { role: "user" as const, content: userContent },
            ],
          };
          next = updateSession(prev, updated);
          sessionId = updated.id;
        } else {
          const created = createSession(`情景：${situation}`);
          created.messages = [{ role: "user" as const, content: userContent }];
          next = [...prev, created];
          sessionId = created.id;
          setActiveId(created.id);
        }
        saveSessions(next);
        return next;
      });

      setIsLoading(true);

      try {
        await analyzeStream(situation, failedLog, (msg) => {
          setSessions((prev) => {
            const idx = prev.findIndex((s) => s.id === sessionId);
            if (idx < 0) return prev;
            const updated = {
              ...prev[idx],
              messages: [...prev[idx].messages, msg],
            };
            const next = [...prev];
            next[idx] = updated;
            saveSessions(next);
            return next;
          });
        });
      } catch (err) {
        setSessions((prev) => {
          const idx = prev.findIndex((s) => s.id === sessionId);
          if (idx < 0) return prev;
          const updated = {
            ...prev[idx],
            messages: [
              ...prev[idx].messages,
              {
                role: "assistant" as const,
                content: `[Error] 请求失败: ${err instanceof Error ? err.message : String(err)}`,
              },
            ],
          };
          const next = [...prev];
          next[idx] = updated;
          saveSessions(next);
          return next;
        });
      } finally {
        setIsLoading(false);
      }
    },
    [activeSession, sessions]
  );

  return (
    <div className="h-screen w-screen flex bg-gray-50">
      <Sidebar
        sessions={sessions}
        activeId={activeId}
        onSelect={handleSelect}
        onNew={handleNew}
      />
      <div className="flex-1 flex flex-col h-full relative">
        <ChatWindow
          messages={activeSession?.messages ?? []}
          isLoading={isLoading}
          onOpenReport={handleOpenReport}
        />
        <MessageInput onSubmit={handleSubmit} disabled={isLoading} />
      </div>
      <ReportPanel filename={reportFilename} onClose={handleCloseReport} />
    </div>
  );
}
