import { test } from "node:test";
import assert from "node:assert/strict";
import { getPageSlices } from "../src/utils/pagination.ts";

test("PDF pagination keeps short headings and rows together with no gaps or overlaps", () => {
  const pages = getPageSlices(250, 100, [{ start: 90, end: 115 }]);
  assert.deepEqual(pages, [
    { top: 0, height: 90 },
    { top: 90, height: 100 },
    { top: 190, height: 60 },
  ]);
  assert.equal(
    pages.reduce((sum, page) => sum + page.height, 0),
    250,
  );
});
test("oversized content can span pages without creating blank pages or an infinite loop", () => {
  assert.deepEqual(getPageSlices(250, 100, [{ start: 0, end: 250 }]), [
    { top: 0, height: 100 },
    { top: 100, height: 100 },
    { top: 200, height: 50 },
  ]);
});
