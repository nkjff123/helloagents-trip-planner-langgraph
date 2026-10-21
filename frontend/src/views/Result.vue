<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from "vue";
import { useRouter } from "vue-router";
import { message } from "ant-design-vue";
import AppIcon from "@/components/AppIcon.vue";
import ItineraryDay from "@/components/ItineraryDay.vue";
import TripMap from "@/components/TripMap.vue";
import TripSummary from "@/components/TripSummary.vue";
import { getAttractionPhoto } from "@/services/api";
import { readTripPlan, refreshAttractionBudget } from "@/utils/trip";
import { exportTrip } from "@/utils/exportTrip";
import type { TripPlan } from "@/types";

const router = useRouter();
const plan = ref<TripPlan | null>(null);
const activeDay = ref(0);
const editMode = ref(false);
const exporting = ref(false);
const documentRef = ref<HTMLElement>();
const photos = ref<Record<string, string>>({});
const controller = new AbortController();
let original: TripPlan | null = null;
const currentAttractions = computed(
  () => plan.value?.days[activeDay.value]?.attractions || [],
);
const numberWords = [
  "一",
  "二",
  "三",
  "四",
  "五",
  "六",
  "七",
  "八",
  "九",
  "十",
];
const title = computed(() =>
  plan.value
    ? `${plan.value.city}，${numberWords[plan.value.days.length - 1] || plan.value.days.length}日旅行`
    : "",
);

onMounted(() => {
  try {
    plan.value = readTripPlan(sessionStorage.getItem("tripPlan"));
  } catch {
    plan.value = null;
  }
  if (!plan.value) return;
  const names = [
    ...new Set(
      plan.value.days
        .flatMap((day) => day.attractions)
        .filter((item) => !item.image_url)
        .map((item) => item.name),
    ),
  ];
  // Photos never delay the itinerary or map; bound concurrency for long trips.
  let next = 0;
  const worker = async () => {
    while (next < names.length && !controller.signal.aborted) {
      const name = names[next++];
      const url = await getAttractionPhoto(name, controller.signal);
      if (url && !controller.signal.aborted) photos.value[name] = url;
    }
  };
  void Promise.all(Array.from({ length: Math.min(4, names.length) }, worker));
});
onBeforeUnmount(() => controller.abort());
function startEditing() {
  original = JSON.parse(JSON.stringify(plan.value));
  editMode.value = true;
}
function save() {
  if (!plan.value) return;
  const invalid = plan.value.days.some((day) =>
    day.attractions.some(
      (item) =>
        !item.address.trim() ||
        !Number.isFinite(item.visit_duration) ||
        item.visit_duration < 10 ||
        item.visit_duration > 480,
    ),
  );
  if (invalid) {
    message.error("请填写景点地址，并将游览时长设置为 10–480 分钟。");
    return;
  }
  try {
    sessionStorage.setItem("tripPlan", JSON.stringify(plan.value));
    original = null;
    editMode.value = false;
    message.success("修改已保存");
  } catch {
    message.error("当前浏览器无法保存行程，请检查存储空间。");
  }
}
function cancel() {
  if (original) plan.value = JSON.parse(JSON.stringify(original));
  original = null;
  editMode.value = false;
}
function move(dayIndex: number, index: number, direction: "up" | "down") {
  const items = plan.value?.days[dayIndex]?.attractions;
  const target = index + (direction === "up" ? -1 : 1);
  if (!items || target < 0 || target >= items.length) return;
  [items[index], items[target]] = [items[target], items[index]];
}
function remove(dayIndex: number, index: number) {
  if (!plan.value || plan.value.days[dayIndex].attractions.length <= 1) return;
  plan.value.days[dayIndex].attractions.splice(index, 1);
  refreshAttractionBudget(plan.value);
}
async function download(format: "image" | "pdf") {
  if (!documentRef.value || !plan.value || exporting.value || editMode.value)
    return;
  exporting.value = true;
  try {
    await exportTrip(documentRef.value, plan.value.city, format);
    message.success(format === "pdf" ? "PDF 导出成功" : "图片导出成功");
  } catch (cause) {
    message.error(
      cause instanceof Error
        ? `导出失败：${cause.message}`
        : "导出失败，请稍后重试。",
    );
  } finally {
    exporting.value = false;
  }
}
function handleTabKey(event: KeyboardEvent, index: number) {
  const count = plan.value?.days.length || 0;
  let target = index;
  if (event.key === "ArrowRight") target = (index + 1) % count;
  else if (event.key === "ArrowLeft") target = (index - 1 + count) % count;
  else if (event.key === "Home") target = 0;
  else if (event.key === "End") target = count - 1;
  else return;
  event.preventDefault();
  activeDay.value = target;
  document.getElementById(`day-tab-${target}`)?.focus();
}
</script>

<template>
  <div v-if="plan" class="result-page">
    <div class="result-toolbar">
      <button class="ui-button" @click="router.push('/')">
        <AppIcon name="back" :size="16" />返回规划
      </button>
      <div class="toolbar-actions">
        <template v-if="editMode"
          ><button class="ui-button" @click="cancel">取消编辑</button
          ><button class="ui-button primary" @click="save">
            <AppIcon name="check" :size="16" />保存修改
          </button></template
        >
        <template v-else>
          <button
            class="ui-button edit-button"
            :disabled="exporting"
            @click="startEditing"
          >
            <AppIcon name="edit" :size="17" />编辑行程
          </button>
          <a-dropdown :trigger="['click']" :disabled="exporting">
            <button class="ui-button primary" :disabled="exporting">
              <span v-if="exporting" class="spinner"></span
              >{{ exporting ? "正在导出…" : "导出行程"
              }}<AppIcon v-if="!exporting" name="down" :size="16" />
            </button>
            <template #overlay
              ><a-menu
                ><a-menu-item key="image" @click="download('image')"
                  ><span class="icon-text"
                    ><AppIcon name="image" :size="17" />导出为图片</span
                  ></a-menu-item
                ><a-menu-item key="pdf" @click="download('pdf')"
                  ><span class="icon-text"
                    ><AppIcon name="download" :size="17" />导出为 PDF</span
                  ></a-menu-item
                ></a-menu
              ></template
            >
          </a-dropdown>
        </template>
      </div>
    </div>
    <div ref="documentRef" class="result-document">
      <header class="trip-heading">
        <h1>{{ title }}</h1>
        <p class="trip-dates">
          {{ plan.start_date.replace(/-/g, ".") }} —
          {{ plan.end_date.replace(/-/g, ".") }} · {{ plan.days.length }} 天行程
        </p>
        <p v-if="plan.overall_suggestions" class="trip-advice">
          {{ plan.overall_suggestions }}
        </p>
      </header>
      <p v-if="editMode" class="editing-note" role="status" data-export-ignore>
        正在编辑行程。调整景点顺序、地址与游览时长后，点击“保存修改”。
      </p>
      <div class="result-grid">
        <div class="itinerary-column">
          <h2 class="section-heading">每日行程</h2>
          <div
            class="day-tabs"
            role="tablist"
            aria-label="选择行程日期"
            data-export-ignore
          >
            <button
              v-for="(day, index) in plan.days"
              :id="`day-tab-${index}`"
              :key="day.date"
              :aria-selected="activeDay === index"
              :aria-controls="`day-panel-${index}`"
              :tabindex="activeDay === index ? 0 : -1"
              role="tab"
              @click="activeDay = index"
              @keydown="handleTabKey($event, index)"
            >
              第 {{ day.day_index + 1 }} 天
            </button>
          </div>
          <div
            v-for="(day, index) in plan.days"
            v-show="activeDay === index"
            :id="`day-panel-${index}`"
            :key="day.date"
            role="tabpanel"
            :aria-labelledby="`day-tab-${index}`"
            tabindex="0"
            data-export-day
          >
            <ItineraryDay
              :day="day"
              :edit-mode="editMode"
              :photos="photos"
              :show-day-number="plan.days.length > 1"
              @move="(position, direction) => move(index, position, direction)"
              @remove="(position) => remove(index, position)"
            />
          </div>
        </div>
        <aside class="trip-sidebar">
          <section class="map-section">
            <h2 class="section-heading">景点地图</h2>
            <TripMap :attractions="currentAttractions" />
          </section>
          <TripSummary :budget="plan.budget" :weather="plan.weather_info" />
        </aside>
      </div>
    </div>
  </div>
  <div v-else class="empty-state">
    <AppIcon name="compass" :size="56" />
    <h1>下一段旅程，等你开启</h1>
    <p>
      这里会保存本次会话中最近生成的行程。<br />先选一个目的地，开始规划吧。
    </p>
    <button class="ui-button primary" @click="router.push('/')">
      开始规划行程<AppIcon name="arrow" :size="17" />
    </button>
  </div>
</template>

<style scoped>
.result-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  margin-bottom: 13px;
}
.toolbar-actions {
  display: flex;
  gap: 12px;
}
.edit-button {
  border-color: #729486;
}
.trip-heading {
  margin-bottom: 15px;
}
.trip-heading h1 {
  font-size: 36px;
  letter-spacing: -1.3px;
  line-height: 1.4;
  font-weight: 700;
}
.trip-dates {
  font-size: 18px;
  line-height: 1.7;
  color: #637078;
  margin-top: 4px;
}
.trip-advice {
  font-size: 16px;
  line-height: 1.7;
  color: #637078;
  margin-top: 9px;
  white-space: pre-line;
  overflow-wrap: anywhere;
}
.result-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(0, 1fr);
  gap: 22px;
}
.itinerary-column {
  min-width: 0;
}
.itinerary-column > .section-heading {
  margin-bottom: 10px;
}
.trip-sidebar {
  border-left: 1px solid var(--line);
  padding-left: 22px;
  min-width: 0;
}
.day-tabs {
  display: flex;
  overflow-x: auto;
  border-bottom: 1px solid var(--line);
  gap: 16px;
  scrollbar-width: thin;
}
.day-tabs button {
  height: 38px;
  min-width: 88px;
  padding: 0 16px;
  border: 0;
  border-bottom: 3px solid transparent;
  background: transparent;
  font-size: 14px;
  font-weight: 500;
  color: #69747c;
  white-space: nowrap;
}
.day-tabs button[aria-selected="true"] {
  color: var(--green);
  border-bottom-color: var(--green);
  font-weight: 650;
}
.editing-note {
  padding: 12px 16px;
  border: 1px solid #c8ded1;
  border-radius: 6px;
  background: #f2f8f4;
  color: var(--green);
  font-size: 14px;
  margin-bottom: 20px;
  line-height: 1.7;
}
.map-section > .section-heading {
  margin-bottom: 14px;
}
[role="tabpanel"]:focus-visible {
  outline: 2px solid #80b7a2;
  outline-offset: 5px;
}
@media (max-width: 1100px) {
  .result-grid {
    grid-template-columns: minmax(0, 1.35fr) minmax(0, 1fr);
    gap: 20px;
  }
  .trip-sidebar {
    padding-left: 20px;
  }
  .trip-heading h1 {
    font-size: 34px;
  }
}
@media (max-width: 850px) {
  .result-grid {
    grid-template-columns: 1fr;
    gap: 32px;
  }
  .trip-sidebar {
    border-left: 0;
    border-top: 1px solid var(--line);
    padding: 28px 0 0;
  }
  .trip-heading {
    margin-bottom: 25px;
  }
}
@media (max-width: 600px) {
  .result-toolbar {
    gap: 10px;
    flex-wrap: wrap;
    margin-bottom: 23px;
  }
  .toolbar-actions {
    gap: 8px;
  }
  .result-toolbar .ui-button {
    font-size: 12px;
    height: 37px;
    padding: 0 9px;
    gap: 5px;
  }
  .trip-heading h1 {
    font-size: 29px;
    letter-spacing: -1px;
  }
  .trip-dates {
    font-size: 14px;
  }
  .trip-advice {
    font-size: 14px;
    line-height: 1.8;
  }
  .day-tabs {
    gap: 5px;
  }
  .day-tabs button {
    min-width: 83px;
    padding: 0 14px;
  }
  .editing-note {
    font-size: 12px;
  }
}
</style>
