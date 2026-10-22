/**
 * 解析 Server-Sent Events 单行数据
 */
export function parseSSELine(line: string): any | null {
  const trimmed = line.trim();
  if (!trimmed.startsWith("data:")) {
    return null;
  }
  const payload = trimmed.slice(5).trim();
  if (!payload || payload === "[DONE]") {
    return { type: "done" };
  }
  try {
    return JSON.parse(payload);
  } catch {
    return null;
  }
}
