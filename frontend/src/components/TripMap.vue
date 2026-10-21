<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch } from "vue";
import AMapLoader from "@amap/amap-jsapi-loader";
import AppIcon from "./AppIcon.vue";
import type { Attraction } from "@/types";
const props = defineProps<{ attractions: Attraction[] }>();
const container = ref<HTMLElement>();
const status = ref<"loading" | "ready" | "unavailable" | "error">("loading");
let map: any;
let sdk: any;
let disposed = false;
const key = import.meta.env.VITE_AMAP_WEB_JS_KEY;

function renderMarkers() {
  if (!map || !sdk) return;
  map.clearMap();
  const valid = props.attractions.filter(
    (item) =>
      Number.isFinite(item.location?.longitude) &&
      Number.isFinite(item.location?.latitude),
  );
  const markers = valid.map((item, index) => {
    const marker = new sdk.Marker({
      position: [item.location.longitude, item.location.latitude],
      title: item.name,
      content: `<div class="map-stop">${index + 1}</div>`,
      offset: new sdk.Pixel(-15, -30),
    });
    marker.on("click", () => {
      const content = document.createElement("div");
      content.className = "map-info";
      const title = document.createElement("strong");
      title.textContent = item.name;
      const address = document.createElement("p");
      address.textContent = item.address;
      const duration = document.createElement("p");
      duration.textContent = `建议游览 ${item.visit_duration} 分钟`;
      content.append(title, address, duration);
      new sdk.InfoWindow({ content, offset: new sdk.Pixel(0, -28) }).open(
        map,
        marker.getPosition(),
      );
    });
    return marker;
  });
  map.add(markers);
  if (markers.length > 1)
    map.add(
      new sdk.Polyline({
        path: valid.map((item) => [
          item.location.longitude,
          item.location.latitude,
        ]),
        strokeColor: "#184c3c",
        strokeWeight: 3,
        strokeOpacity: 0.75,
        strokeStyle: "dashed",
        showDir: true,
      }),
    );
  if (markers.length) map.setFitView(markers, false, [45, 45, 45, 45], 15);
}
async function loadMap() {
  if (!key || key.startsWith("your_")) {
    status.value = "unavailable";
    return;
  }
  status.value = "loading";
  try {
    sdk = await AMapLoader.load({
      key,
      version: "2.0",
      plugins: ["AMap.ToolBar", "AMap.Scale"],
    });
    if (disposed || !container.value) return;
    map?.destroy();
    const first = props.attractions.find((item) => item.location);
    map = new sdk.Map(container.value, {
      zoom: 12,
      ...(first
        ? { center: [first.location.longitude, first.location.latitude] }
        : {}),
      viewMode: "2D",
      preserveDrawingBuffer: true,
    });
    map.addControl(new sdk.ToolBar({ position: "RB" }));
    map.addControl(new sdk.Scale());
    renderMarkers();
    status.value = "ready";
  } catch {
    // The SDK loader caches failed downloads until explicitly reset.
    if (!sdk) (AMapLoader as typeof AMapLoader & { reset: () => void }).reset();
    if (!disposed) status.value = "error";
  }
}
watch(() => props.attractions, renderMarkers, { deep: true });
onMounted(loadMap);
onBeforeUnmount(() => {
  disposed = true;
  map?.destroy();
});
</script>

<template>
  <div class="trip-map">
    <div
      ref="container"
      class="map-canvas"
      role="region"
      aria-label="当日景点高德地图"
      :aria-busy="status === 'loading'"
    ></div>
    <div v-if="status !== 'ready'" class="map-status" role="status">
      <span v-if="status === 'loading'" class="spinner"></span
      ><AppIcon v-else name="pin" :size="32" /><strong>{{
        status === "loading"
          ? "正在加载地图…"
          : status === "unavailable"
            ? "地图暂不可用"
            : "地图加载失败"
      }}</strong>
      <p>
        {{
          status === "unavailable"
            ? "当前未启用地图服务，仍可查看完整行程与景点地址。"
            : status === "error"
              ? "请检查网络连接，行程信息仍可正常查看。"
              : "正在为你展开当日景点位置"
        }}
      </p>
      <button
        v-if="status === 'error'"
        class="ui-button"
        type="button"
        @click="loadMap"
      >
        重新加载
      </button>
    </div>
  </div>
  <p v-if="status === 'ready'" class="map-caption">
    编号对应当日景点，连线仅示意游览顺序。
  </p>
</template>

<style scoped>
.trip-map {
  height: 390px;
  position: relative;
  background: #f4f7f4;
  border: 1px solid var(--line);
  border-radius: 6px;
  overflow: hidden;
}
.map-canvas {
  width: 100%;
  height: 100%;
}
.map-status {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 34px;
  text-align: center;
  gap: 14px;
  color: var(--green);
}
.map-status strong {
  font-size: 17px;
  font-weight: 600;
}
.map-status p {
  font-size: 13px;
  line-height: 1.8;
  color: var(--muted);
  max-width: 260px;
}
.map-caption {
  font-size: 12px;
  line-height: 1.6;
  margin-top: 8px;
  color: var(--muted);
}
:deep(.map-stop) {
  width: 30px;
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--green);
  border: 2px solid white;
  border-radius: 50% 50% 50% 4px;
  color: white;
  font-size: 13px;
  box-shadow: 0 2px 6px #0002;
}
:deep(.map-info) {
  padding: 8px;
  max-width: 240px;
  font-size: 13px;
  line-height: 1.7;
}
:deep(.map-info strong) {
  font-size: 16px;
}
:deep(.map-info p) {
  margin-top: 6px;
}
@media (max-width: 600px) {
  .trip-map {
    height: 285px;
  }
}
</style>
