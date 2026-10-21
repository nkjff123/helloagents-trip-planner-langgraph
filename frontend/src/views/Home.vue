<script setup lang="ts">
import { ref, reactive, computed, onBeforeUnmount } from "vue";
import { useRouter } from "vue-router";
import type { Dayjs } from "dayjs";
import AppIcon from "@/components/AppIcon.vue";
import { generateTripPlan } from "@/services/api";
import { getTravelDays } from "@/utils/trip";
import type { TripFormData } from "@/types";

const router = useRouter();
const loading = ref(false);
const error = ref("");
let disposed = false;
onBeforeUnmount(() => {
  disposed = true;
});
const form = reactive({
  city: "",
  start_date: null as Dayjs | null,
  end_date: null as Dayjs | null,
  transportation: "公共交通",
  accommodation: "经济型酒店",
  preferences: ["自然风光", "美食"],
  free_text_input: "",
});
const days = computed(() =>
  getTravelDays(
    form.start_date?.format("YYYY-MM-DD") || "",
    form.end_date?.format("YYYY-MM-DD") || "",
  ),
);
const dateError = computed(() =>
  form.start_date && form.end_date && !days.value
    ? "结束日期不能早于开始日期，且旅行时间不能超过 30 天。"
    : "",
);
const togglePreference = (value: string) => {
  const index = form.preferences.indexOf(value);
  if (index < 0) form.preferences.push(value);
  else form.preferences.splice(index, 1);
};
const disabledEndDate = (date: Dayjs) =>
  !!form.start_date &&
  (date.isBefore(form.start_date, "day") ||
    date.diff(form.start_date, "day") > 29);
async function submit() {
  if (loading.value) return;
  error.value = "";
  if (!form.city.trim() || !days.value) {
    error.value = dateError.value || "请填写目的地，并选择完整的出行日期。";
    return;
  }
  loading.value = true;
  const request: TripFormData = {
    ...form,
    city: form.city.trim(),
    start_date: form.start_date!.format("YYYY-MM-DD"),
    end_date: form.end_date!.format("YYYY-MM-DD"),
    travel_days: days.value,
    preferences: [...form.preferences],
  };
  try {
    const response = await generateTripPlan(request);
    if (disposed) return;
    if (!response.success || !response.data)
      throw new Error(response.message || "未能生成行程，请稍后再试。");
    sessionStorage.setItem("tripPlan", JSON.stringify(response.data));
    await router.push("/result");
  } catch (cause) {
    if (!disposed)
      error.value =
        cause instanceof Error
          ? cause.message
          : "暂时无法生成行程，请稍后重试。";
  } finally {
    if (!disposed) loading.value = false;
  }
}
</script>

<template>
  <div class="planner-layout">
    <div class="planner-content">
      <header class="planner-heading">
        <h1>下一站，去哪里？</h1>
        <p>把想去的地方告诉我们，安排一段属于你的旅程。</p>
      </header>
      <a-form
        :model="form"
        layout="vertical"
        class="trip-form"
        :disabled="loading"
        @finish="submit"
        :required-mark="false"
      >
        <section class="form-section" aria-labelledby="destination-heading">
          <h2 id="destination-heading" class="form-section-heading">
            <span>01</span><i></i>目的地与日期
          </h2>
          <a-form-item
            label="目的地"
            name="city"
            :rules="[
              { required: true, whitespace: true, message: '请输入目的地城市' },
            ]"
          >
            <a-input
              v-model:value="form.city"
              size="large"
              placeholder="输入目的地城市，如杭州"
              :maxlength="50"
              ><template #prefix><AppIcon name="pin" :size="19" /></template
            ></a-input>
          </a-form-item>
          <div class="date-row">
            <a-form-item
              label="开始日期"
              name="start_date"
              :rules="[{ required: true, message: '请选择开始日期' }]"
            >
              <a-date-picker
                v-model:value="form.start_date"
                size="large"
                placeholder="选择日期"
                format="YYYY-MM-DD"
                ><template #suffixIcon
                  ><AppIcon name="calendar" :size="18" /></template
              ></a-date-picker>
            </a-form-item>
            <a-form-item
              label="结束日期"
              name="end_date"
              :rules="[{ required: true, message: '请选择结束日期' }]"
              :validate-status="dateError ? 'error' : undefined"
            >
              <a-date-picker
                v-model:value="form.end_date"
                :disabled-date="disabledEndDate"
                size="large"
                placeholder="选择日期"
                format="YYYY-MM-DD"
                ><template #suffixIcon
                  ><AppIcon name="calendar" :size="18" /></template
              ></a-date-picker>
            </a-form-item>
            <div class="days-count" aria-live="polite">
              共 <strong>{{ days || 1 }}</strong> 天
            </div>
          </div>
          <p v-if="dateError" class="field-error" role="alert">
            {{ dateError }}
          </p>
        </section>
        <section class="form-section" aria-labelledby="preferences-heading">
          <h2 id="preferences-heading" class="form-section-heading">
            <span>02</span><i></i>出行偏好
          </h2>
          <div class="preference-row">
            <a-form-item label="交通方式" name="transportation"
              ><div class="select-with-icon">
                <AppIcon name="train" :size="19" /><a-select
                  v-model:value="form.transportation"
                  size="large"
                  :options="
                    ['公共交通', '自驾', '步行', '混合'].map((value) => ({
                      value,
                    }))
                  "
                  aria-label="交通方式"
                /></div
            ></a-form-item>
            <a-form-item label="住宿偏好" name="accommodation"
              ><div class="select-with-icon">
                <AppIcon name="bed" :size="19" /><a-select
                  v-model:value="form.accommodation"
                  size="large"
                  :options="
                    ['经济型酒店', '舒适型酒店', '豪华酒店', '民宿'].map(
                      (value) => ({ value }),
                    )
                  "
                  aria-label="住宿偏好"
                /></div
            ></a-form-item>
          </div>
          <fieldset class="preference-fieldset">
            <legend>旅行偏好</legend>
            <div class="preference-options">
              <button
                v-for="option in [
                  '历史文化',
                  '自然风光',
                  '美食',
                  '购物',
                  '艺术',
                  '休闲',
                ]"
                :key="option"
                type="button"
                :aria-pressed="form.preferences.includes(option)"
                :disabled="loading"
                class="preference-option"
                @click="togglePreference(option)"
              >
                <span v-if="form.preferences.includes(option)" class="check-dot"
                  ><AppIcon name="check" :size="13" /></span
                >{{ option }}
              </button>
            </div>
          </fieldset>
        </section>
        <section
          class="form-section last-section"
          aria-labelledby="notes-heading"
        >
          <h2 id="notes-heading" class="form-section-heading">
            <span>03</span><i></i>特别的期待
          </h2>
          <a-form-item name="free_text_input">
            <div class="notes-input">
              <AppIcon name="edit" :size="19" />
              <a-textarea
                v-model:value="form.free_text_input"
                aria-labelledby="notes-heading"
                placeholder="想去的景点、饮食禁忌、出行节奏……都可以告诉我们"
                :rows="3"
                :maxlength="2000"
              />
            </div>
          </a-form-item>
        </section>
        <div v-if="error" role="alert" class="form-error">{{ error }}</div>
        <button class="plan-submit" type="submit" :disabled="loading">
          <span v-if="loading" class="spinner"></span
          ><span>{{ loading ? "正在生成旅行计划…" : "开始规划我的旅行" }}</span
          ><AppIcon v-if="!loading" name="arrow" :size="22" />
        </button>
        <p v-if="loading" class="submission-note" role="status">
          正在结合景点、住宿、餐饮与天气信息规划，请耐心等待，可能需要几分钟。
        </p>
        <p v-else class="submission-note">
          行程将结合景点、住宿、餐饮与天气信息生成
        </p>
      </a-form>
    </div>
    <figure class="travel-visual">
      <img
        src="/images/guilin-river.webp"
        alt="晨光下的桂林山水，竹筏缓缓划过漓江"
        width="600"
        height="1000"
        fetchpriority="high"
      />
      <figcaption>
        <h2>山水之间，慢一点也很好。</h2>
        <p>从一个目的地，开始下一段故事。</p>
      </figcaption>
    </figure>
  </div>
</template>

<style scoped>
.planner-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.58fr) minmax(0, 1fr);
  gap: 48px;
  align-items: start;
}
.planner-heading {
  margin: 5px 0 22px;
}
.planner-heading h1 {
  font-size: 58px;
  line-height: 1.25;
  letter-spacing: -2px;
  font-weight: 750;
  margin-bottom: 8px;
}
.planner-heading p {
  font-size: 20px;
  line-height: 1.7;
  color: #858b94;
}
.form-section {
  border-bottom: 1px solid var(--line);
  padding-bottom: 23px;
  margin-bottom: 25px;
}
.form-section-heading {
  display: flex;
  align-items: center;
  gap: 20px;
  font-size: 22px;
  line-height: 1.5;
  font-weight: 650;
  margin-bottom: 17px;
}
.form-section-heading > span {
  color: var(--green);
  font-size: 24px;
  font-weight: 650;
}
.form-section-heading i {
  height: 20px;
  border-left: 1px solid #839b91;
}
.trip-form :deep(.ant-form-item) {
  margin-bottom: 20px;
}
.trip-form :deep(.ant-form-item-label) {
  padding-bottom: 7px;
}
.trip-form :deep(.ant-form-item-label > label) {
  font-size: 15px;
  font-weight: 550;
  color: var(--ink);
}
.trip-form :deep(.ant-input-affix-wrapper) {
  padding-inline: 13px;
}
.trip-form :deep(.ant-input-prefix) {
  margin-right: 12px;
  color: #34423d;
}
.trip-form :deep(.ant-input),
.trip-form :deep(.ant-picker-input > input) {
  font-size: 15px;
}
.trip-form :deep(.ant-picker) {
  width: 100%;
  height: 46px;
}
.trip-form :deep(.ant-picker-suffix) {
  color: #6f7883;
  order: -1;
  margin-left: 0;
  margin-right: 12px;
}
.date-row {
  display: grid;
  grid-template-columns: 1fr 1fr auto;
  gap: 22px;
  align-items: end;
}
.date-row :deep(.ant-form-item) {
  margin-bottom: 0;
}
.days-count {
  height: 46px;
  min-width: 126px;
  margin-bottom: 0;
  margin-left: 4px;
  border-left: 1px solid var(--line);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 9px;
  font-size: 19px;
  white-space: nowrap;
}
.days-count strong {
  font-size: 32px;
  line-height: 1;
  color: var(--green);
  font-weight: 650;
}
.preference-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 26px;
}
.select-with-icon {
  position: relative;
}
.select-with-icon > svg {
  position: absolute;
  top: 14px;
  left: 13px;
  z-index: 1;
  pointer-events: none;
}
.select-with-icon :deep(.ant-select) {
  width: 100%;
}
.select-with-icon :deep(.ant-select-selector) {
  padding-left: 42px !important;
  font-size: 15px;
}
.preference-fieldset {
  border: 0;
  padding: 0;
  margin: 0;
  min-width: 0;
}
.preference-fieldset legend {
  border: 0;
  float: none;
  width: auto;
  color: var(--ink);
  line-height: 1.5;
  font-size: 15px;
  font-weight: 550;
  margin-bottom: 8px;
  padding: 0;
}
.preference-options {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.preference-option {
  min-height: 43px;
  flex: 1;
  white-space: nowrap;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 8px 14px;
  border: 1px solid #d8dedb;
  border-radius: 9px;
  background: #fff;
  color: var(--ink);
  font-size: 15px;
}
.preference-option[aria-pressed="true"] {
  color: var(--green);
  border-color: #8ab6a5;
  background: #f0f8f4;
}
.check-dot {
  border-radius: 50%;
  background: var(--green);
  color: #fff;
  width: 20px;
  height: 20px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.last-section {
  border-bottom: 0;
  margin-bottom: 20px;
  padding-bottom: 0;
}
.last-section :deep(.ant-form-item) {
  margin-bottom: 0;
}
.notes-input {
  position: relative;
}
.notes-input > svg {
  position: absolute;
  top: 16px;
  left: 16px;
  z-index: 1;
  pointer-events: none;
}
.last-section :deep(textarea) {
  padding: 13px 15px 13px 44px;
  height: 86px;
  min-height: 86px;
  font-size: 14px;
  line-height: 1.7;
}
.plan-submit {
  width: 100%;
  height: 54px;
  border: 0;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 20px;
  background: var(--green);
  color: #fff;
  font-size: 18px;
  font-weight: 600;
  transition: background 0.15s;
}
.plan-submit:hover {
  background: #23634f;
}
.plan-submit:disabled {
  opacity: 0.7;
}
.submission-note {
  font-size: 13px;
  line-height: 1.7;
  color: #9399a1;
  text-align: center;
  margin-top: 12px;
}
.travel-visual > img {
  width: 100%;
  height: 824px;
  display: block;
  object-fit: cover;
  border-radius: 13px;
}
.travel-visual figcaption {
  padding-top: 15px;
}
.travel-visual h2 {
  font-size: 26px;
  line-height: 1.4;
  font-weight: 650;
  letter-spacing: -0.5px;
}
.travel-visual p {
  font-size: 17px;
  line-height: 1.6;
  color: #858b94;
  margin-top: 5px;
}
.form-error,
.field-error {
  color: #a83b30;
  font-size: 14px;
  line-height: 1.6;
}
.form-error {
  padding: 12px 14px;
  border: 1px solid #eed3d0;
  background: #fdf7f6;
  border-radius: 8px;
  margin-bottom: 16px;
}
.field-error {
  margin-top: 10px;
}
@media (max-width: 1200px) {
  .planner-layout {
    gap: 32px;
    grid-template-columns: minmax(0, 1.5fr) minmax(0, 1fr);
  }
  .planner-heading h1 {
    font-size: 44px;
  }
  .planner-heading p {
    font-size: 16px;
  }
  .date-row {
    gap: 12px;
  }
  .days-count {
    min-width: 88px;
    font-size: 16px;
  }
  .preference-option {
    padding: 8px 11px;
    flex: 0 1 auto;
  }
  .travel-visual h2 {
    font-size: 23px;
  }
  .travel-visual > img {
    height: 820px;
  }
}
@media (max-width: 900px) {
  .planner-layout {
    grid-template-columns: 1fr;
  }
  .travel-visual {
    display: none;
  }
  .planner-heading {
    margin-bottom: 30px;
  }
  .planner-heading h1 {
    font-size: 44px;
  }
  .preference-option {
    flex: 1;
  }
  .form-section {
    padding-bottom: 25px;
    margin-bottom: 25px;
  }
}
@media (max-width: 600px) {
  .planner-heading h1 {
    font-size: 34px;
    letter-spacing: -1.3px;
  }
  .planner-heading p {
    font-size: 14px;
    max-width: 290px;
  }
  .form-section-heading {
    font-size: 19px;
    gap: 15px;
  }
  .form-section-heading > span {
    font-size: 21px;
  }
  .date-row {
    grid-template-columns: 1fr 1fr;
    gap: 14px;
  }
  .days-count {
    grid-column: 1/-1;
    border-left: 0;
    justify-content: flex-start;
    height: 29px;
    font-size: 14px;
    gap: 6px;
    margin: 0;
  }
  .days-count strong {
    font-size: 22px;
  }
  .preference-row {
    gap: 14px;
  }
  .preference-options {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
  }
  .preference-option {
    padding: 9px 5px;
    font-size: 13px;
    gap: 5px;
    min-width: 0;
  }
  .check-dot {
    width: 16px;
    height: 16px;
  }
  .trip-form :deep(.ant-picker-input > input) {
    font-size: 13px;
  }
  .trip-form :deep(.ant-picker-suffix) {
    margin-right: 7px;
  }
  .select-with-icon :deep(.ant-select-selector) {
    font-size: 13px;
    padding-left: 36px !important;
  }
  .select-with-icon > svg {
    left: 11px;
    width: 17px;
  }
  .plan-submit {
    font-size: 16px;
    height: 50px;
  }
  .submission-note {
    font-size: 12px;
  }
}
</style>
