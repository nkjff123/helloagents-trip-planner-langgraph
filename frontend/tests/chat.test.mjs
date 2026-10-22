import { test } from "node:test";
import assert from "node:assert/strict";
import { parseSSELine } from "../src/utils/sse.ts";

test("parseSSELine parses standard SSE json data", () => {
  const line = 'data: {"type":"token","content":"您好"}';
  const parsed = parseSSELine(line);
  assert.deepEqual(parsed, { type: "token", content: "您好" });
});

test("parseSSELine handles done signal", () => {
  const line = "data: [DONE]";
  const parsed = parseSSELine(line);
  assert.deepEqual(parsed, { type: "done" });
});

test("parseSSELine ignores non-data lines", () => {
  assert.equal(parseSSELine(": keepalive"), null);
  assert.equal(parseSSELine(""), null);
});
