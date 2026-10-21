export interface ProtectedRange {
  start: number;
  end: number;
}

export function getPageSlices(
  totalHeight: number,
  pageHeight: number,
  ranges: ProtectedRange[],
) {
  const slices: { top: number; height: number }[] = [];
  for (let top = 0; top < totalHeight;) {
    let bottom = Math.min(top + pageHeight, totalHeight);
    if (bottom < totalHeight) {
      // Moving above one block may meet an overlapping heading. Resolve until stable.
      for (;;) {
        const candidates = ranges.filter(
          (range) =>
            range.start < bottom &&
            range.end > bottom &&
            range.end - range.start < pageHeight &&
            range.start > top + pageHeight * 0.2,
        );
        const next = candidates.reduce(
          (value, range) => Math.min(value, Math.floor(range.start)),
          bottom,
        );
        if (next === bottom) break;
        bottom = next;
      }
    }
    slices.push({ top, height: bottom - top });
    top = bottom;
  }
  return slices;
}
