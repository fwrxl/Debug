import axios from "axios";
import type { Message } from "../types";

const API_BASE = "http://localhost:8000/api";

const client = axios.create({
  baseURL: API_BASE,
  headers: { "Content-Type": "application/json" },
});

export async function analyze(situation: string, failedLog: string): Promise<Message[]> {
  const res = await client.post("/analyze", { situation, failed_log: failedLog });
  return res.data.messages as Message[];
}

export async function analyzeStream(
  situation: string,
  failedLog: string,
  onMessage: (msg: Message) => void
): Promise<void> {
  const res = await fetch(`${API_BASE}/analyze/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ situation, failed_log: failedLog }),
  });

  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: ${res.statusText}`);
  }

  const reader = res.body?.getReader();
  const decoder = new TextDecoder();
  if (!reader) {
    throw new Error("Response body is null");
  }

  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    // SSE 格式: data: {...}\n\n
    const lines = buffer.split("\n\n");
    buffer = lines.pop() || ""; // 保留最后不完整的块

    for (const chunk of lines) {
      const line = chunk.trim();
      if (!line.startsWith("data: ")) continue;

      const dataStr = line.slice(6);
      if (dataStr === "[DONE]") return;

      const data = JSON.parse(dataStr);
      if (data.role === "done") return;
      if (data.role === "error") throw new Error(data.content);

      onMessage(data as Message);
    }
  }
}

export async function listReports(): Promise<string[]> {
  const res = await client.get("/reports");
  return res.data.reports as string[];
}

export async function getReport(filename: string): Promise<string> {
  const res = await client.get(`/reports/${encodeURIComponent(filename)}`);
  return res.data.content as string;
}
