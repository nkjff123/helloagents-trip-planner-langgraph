import { getPageSlices } from "./pagination";

// Capture the same styled components, expanding every day in an isolated export copy.
export async function exportTrip(
  element: HTMLElement,
  city: string,
  format: "image" | "pdf",
) {
  const { default: html2canvas } = await import("html2canvas");
  const copy = element.cloneNode(true) as HTMLElement;
  copy.classList.add("export-document");
  Object.assign(copy.style, {
    width: "1200px",
    padding: "36px",
    background: "#fff",
  });
  copy.querySelectorAll<HTMLElement>("[data-export-day]").forEach((day) => {
    day.style.display = "block";
  });
  copy
    .querySelectorAll("[data-export-ignore]")
    .forEach((node) => node.remove());
  const liveMap = element.querySelector(".trip-map");
  const copiedMap = copy.querySelector(".trip-map");
  if (liveMap && copiedMap) {
    // AMap uses multiple layers; never export a blank or partially rendered map canvas.
    copiedMap.replaceChildren();
    const note = document.createElement("div");
    note.textContent = "地图与景点位置请在在线行程中查看。";
    Object.assign(note.style, {
      padding: "30px",
      color: "#747c85",
      fontSize: "14px",
    });
    copiedMap.append(note);
    (copiedMap as HTMLElement).style.height = "auto";
  }
  // Browsers only serialize input attributes, so synchronize any live values explicitly.
  copy.querySelectorAll("input,textarea").forEach((node) => node.remove());
  // A real desktop-sized document keeps both layout measurements and capture consistent
  // when exporting from a phone. Changing html2canvas's windowWidth alone is insufficient.
  const frame = document.createElement("iframe");
  frame.setAttribute("aria-hidden", "true");
  frame.tabIndex = -1;
  Object.assign(frame.style, {
    position: "absolute",
    left: "-20000px",
    top: "0",
    width: "1440px",
    height: "1000px",
    border: "0",
  });
  document.body.append(frame);
  try {
    const target = frame.contentDocument!;
    target.open();
    target.write(
      '<!doctype html><html lang="zh-CN"><head><title>旅行计划导出</title></head><body></body></html>',
    );
    target.close();
    const base = target.createElement("base");
    base.href = document.baseURI;
    target.head.append(base);
    const styles = [
      ...document.head.querySelectorAll('style,link[rel="stylesheet"]'),
    ].map((node) => {
      const clone = node.cloneNode(true) as HTMLElement;
      const ready =
        node.tagName === "LINK"
          ? new Promise<void>((resolve) => {
              const timer = setTimeout(resolve, 5000);
              const finish = () => {
                clearTimeout(timer);
                resolve();
              };
              clone.addEventListener("load", finish, { once: true });
              clone.addEventListener("error", finish, { once: true });
            })
          : Promise.resolve();
      target.head.append(clone);
      return ready;
    });
    target.body.append(copy);
    await Promise.all(styles);
    await target.fonts.ready;
    const origin = copy.getBoundingClientRect().top;
    const protectedRanges = [
      ...copy.querySelectorAll(
        "h1,h2,h3,.day-intro,.attraction-row,.meal-row,.hotel-section,.budget-list>div,.weather-item",
      ),
    ].map((node) => {
      const rect = node.getBoundingClientRect();
      const firstStop = node.classList.contains("day-intro")
        ? node.nextElementSibling?.querySelector(".attraction-row")?.getBoundingClientRect()
        : undefined;
      return {
        start: rect.top - origin - 4,
        end: firstStop
          ? firstStop.top - origin + Math.min(firstStop.height, 60)
          : rect.bottom - origin + (/^H[123]$/.test(node.tagName) ? 24 : 4),
      };
    });
    const canvas = await html2canvas(copy, {
      backgroundColor: "#fff",
      scale: Math.min(2, 24000 / Math.max(copy.scrollHeight, 1)),
      logging: false,
      useCORS: true,
      allowTaint: false,
      windowWidth: 1440,
    });
    const filename = `旅行计划_${city.replace(/[\\/:*?"<>|]/g, "")}`;
    if (format === "image") {
      const blob = await new Promise<Blob>((resolve, reject) =>
        canvas.toBlob(
          (value) =>
            value ? resolve(value) : reject(new Error("图片编码失败")),
          "image/png",
        ),
      );
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.download = `${filename}.png`;
      link.href = url;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
    } else {
      const { default: jsPDF } = await import("jspdf");
      const pdf = new jsPDF("p", "mm", "a4");
      const pageWidth = 190;
      const pageHeight = 277;
      const sliceHeight = Math.floor((canvas.width * pageHeight) / pageWidth);
      const ratio = canvas.width / copy.offsetWidth;
      const slices = getPageSlices(
        canvas.height,
        sliceHeight,
        protectedRanges.map((range) => ({
          start: range.start * ratio,
          end: range.end * ratio,
        })),
      );
      for (const [index, page] of slices.entries()) {
        if (index) pdf.addPage();
        const slice = document.createElement("canvas");
        slice.width = canvas.width;
        slice.height = page.height;
        slice
          .getContext("2d")!
          .drawImage(
            canvas,
            0,
            page.top,
            canvas.width,
            slice.height,
            0,
            0,
            canvas.width,
            slice.height,
          );
        pdf.addImage(
          slice.toDataURL("image/png"),
          "PNG",
          10,
          10,
          pageWidth,
          (slice.height * pageWidth) / canvas.width,
        );
      }
      pdf.save(`${filename}.pdf`);
    }
  } finally {
    frame.remove();
  }
}
