<script setup lang="ts">
import { ref } from "vue";
import AppIcon from "./AppIcon.vue";
import type { DayPlan } from "@/types";
import { formatMoney } from "@/utils/trip";
defineProps<{
  day: DayPlan;
  editMode: boolean;
  photos: Record<string, string>;
  showDayNumber?: boolean;
}>();
defineEmits<{
  move: [index: number, direction: "up" | "down"];
  remove: [index: number];
}>();
const failedPhotos = ref<Record<string, boolean>>({});
const mealLabels: Record<string, string> = {
  breakfast: "早餐",
  lunch: "午餐",
  dinner: "晚餐",
  snack: "小吃",
};
</script>

<template>
  <section class="itinerary-day">
    <header class="day-intro">
      <h3>
        <span v-if="showDayNumber">第 {{ day.day_index + 1 }} 天 · </span
        >{{ day.description || `第 ${day.day_index + 1} 天行程` }}
      </h3>
      <p>
        {{ day.date.replace(/-/g, ".") }}<span>·</span>{{ day.transportation
        }}<span>·</span>{{ day.accommodation }}
      </p>
    </header>
    <ol class="attraction-timeline">
      <li
        v-for="(item, index) in day.attractions"
        :key="`${item.name}-${index}`"
        class="attraction-row"
      >
        <span class="stop-number">{{ index + 1 }}</span>
        <div class="attraction-details">
          <div class="attraction-heading">
            <h3>{{ item.name }}</h3>
            <span v-if="item.rating" class="attraction-rating"
              ><AppIcon name="star" :size="14" />{{ item.rating }}</span
            >
          </div>
          <template v-if="!editMode">
            <p class="detail-line">
              <AppIcon name="pin" :size="16" /><span>{{ item.address }}</span>
            </p>
            <div class="attraction-meta">
              <span
                ><AppIcon name="clock" :size="16" />建议游览
                {{ item.visit_duration }} 分钟</span
              ><span v-if="item.ticket_price != null"
                ><AppIcon name="ticket" :size="16" />门票 ¥{{
                  formatMoney(item.ticket_price)
                }}</span
              >
            </div>
            <p class="attraction-description">{{ item.description }}</p>
          </template>
          <div v-else class="attraction-editor">
            <label
              >地址<a-input
                v-model:value="item.address"
                :aria-label="`${item.name}地址`"
            /></label>
            <label
              >游览时长（分钟）<a-input-number
                v-model:value="item.visit_duration"
                :min="10"
                :max="480"
                :aria-label="`${item.name}游览时长`"
            /></label>
            <label
              >描述<a-textarea
                v-model:value="item.description"
                :rows="2"
                :aria-label="`${item.name}描述`"
            /></label>
            <div class="edit-actions">
              <button
                class="ui-button"
                :disabled="index === 0"
                :aria-label="`上移${item.name}`"
                @click="$emit('move', index, 'up')"
              >
                <AppIcon name="up" :size="16" />上移
              </button>
              <button
                class="ui-button"
                :disabled="index === day.attractions.length - 1"
                :aria-label="`下移${item.name}`"
                @click="$emit('move', index, 'down')"
              >
                <AppIcon name="down" :size="16" />下移
              </button>
              <button
                class="ui-button delete-button"
                :disabled="day.attractions.length <= 1"
                :aria-label="`删除${item.name}`"
                @click="$emit('remove', index)"
              >
                <AppIcon name="trash" :size="16" />删除
              </button>
            </div>
          </div>
        </div>
        <img
          v-if="
            (item.image_url || photos[item.name]) &&
            !failedPhotos[item.name] &&
            !editMode
          "
          class="attraction-photo"
          :src="item.image_url || photos[item.name]"
          :alt="item.name"
          loading="lazy"
          crossorigin="anonymous"
          @error="failedPhotos[item.name] = true"
        />
      </li>
    </ol>
    <p v-if="!day.attractions.length" class="muted section-empty">
      当天暂无景点安排。
    </p>
    <section class="meals-section">
      <h2 class="section-heading">餐饮安排</h2>
      <div
        v-for="(meal, index) in day.meals"
        :key="`${meal.type}-${index}`"
        class="meal-row"
      >
        <span class="meal-type">{{ mealLabels[meal.type] || meal.type }}</span>
        <div class="meal-details">
          <strong>{{ meal.name }}</strong>
          <p v-if="meal.description">{{ meal.description }}</p>
        </div>
        <p v-if="meal.address" class="meal-address">
          <AppIcon name="pin" :size="15" />{{ meal.address }}
        </p>
      </div>
      <p v-if="!day.meals.length" class="muted">当天暂无餐饮安排。</p>
    </section>
    <section v-if="day.hotel" class="hotel-section">
      <h2 class="section-heading">住宿推荐</h2>
      <div class="hotel-row">
        <div class="hotel-details">
          <h3>{{ day.hotel.name }}</h3>
          <p>
            {{ day.hotel.type
            }}<span v-if="day.hotel.address" class="hotel-address"
              ><AppIcon name="pin" :size="15" />{{ day.hotel.address }}</span
            >
          </p>
          <p v-if="day.hotel.distance">{{ day.hotel.distance }}</p>
        </div>
        <div class="hotel-price">
          <p v-if="day.hotel.rating">
            <AppIcon name="star" :size="15" />{{ day.hotel.rating }}
          </p>
          <p>{{ day.hotel.price_range }}</p>
        </div>
      </div>
    </section>
  </section>
</template>

<style scoped>
.day-intro {
  margin: 20px 0 21px;
}
.day-intro h3 {
  font-size: 21px;
  font-weight: 650;
  line-height: 1.6;
}
.day-intro > p {
  margin-top: 4px;
  font-size: 14px;
  line-height: 1.8;
  color: #69747c;
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}
.attraction-timeline {
  list-style: none;
  margin: 0;
  padding: 0 0 0 50px;
  position: relative;
}
.attraction-timeline:before {
  content: "";
  position: absolute;
  left: 15px;
  top: 15px;
  bottom: 15px;
  width: 1px;
  background: #d5dfd9;
}
.attraction-row {
  position: relative;
  display: flex;
  gap: 22px;
  padding: 0 0 23px;
  margin-bottom: 18px;
  border-bottom: 1px solid var(--line);
  min-width: 0;
}
.attraction-row:last-child {
  margin-bottom: 0;
}
.stop-number {
  position: absolute;
  left: -50px;
  top: 0;
  background: var(--green);
  color: #fff;
  border: 3px solid #fff;
  border-radius: 50%;
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 600;
  z-index: 1;
}
.attraction-details {
  flex: 1;
  min-width: 0;
}
.attraction-heading {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin: 4px 0 10px;
}
.attraction-heading h3 {
  font-size: 18px;
  line-height: 1.5;
  font-weight: 650;
}
.attraction-rating {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: #8f6d33;
  font-size: 12px;
  white-space: nowrap;
}
.detail-line {
  display: flex;
  gap: 8px;
  font-size: 13px;
  color: #69747c;
  line-height: 1.8;
}
.detail-line > svg {
  flex-shrink: 0;
  margin-top: 3px;
}
.attraction-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 18px;
  margin-top: 8px;
  font-size: 13px;
  color: #69747c;
}
.attraction-meta > span {
  display: inline-flex;
  gap: 7px;
  align-items: center;
}
.attraction-description {
  margin-top: 13px;
  font-size: 14px;
  line-height: 1.8;
  color: #58636b;
  overflow-wrap: anywhere;
}
.attraction-photo {
  width: 33%;
  max-width: 244px;
  height: 151px;
  border-radius: 6px;
  object-fit: cover;
  flex-shrink: 0;
}
.meals-section {
  margin-top: 25px;
}
.meal-row {
  display: flex;
  align-items: baseline;
  gap: 16px;
  border-top: 1px solid var(--line);
  padding: 12px 0;
  font-size: 13px;
  line-height: 1.7;
}
.meal-type {
  flex-shrink: 0;
  font-size: 14px;
}
.meal-details {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 4px 14px;
}
.meal-details strong {
  font-weight: 600;
  font-size: 14px;
}
.meal-details > p {
  color: var(--muted);
  margin-top: 0;
}
.meal-address {
  display: flex;
  gap: 6px;
  color: var(--muted);
  max-width: 35%;
  font-size: 12px;
}
.meal-address > svg {
  flex-shrink: 0;
  margin-top: 3px;
}
.hotel-section {
  margin-top: 22px;
}
.hotel-row {
  display: flex;
  gap: 18px;
  justify-content: space-between;
  line-height: 1.8;
}
.hotel-details {
  min-width: 0;
}
.hotel-details h3 {
  font-size: 16px;
  font-weight: 600;
}
.hotel-details p {
  font-size: 13px;
  color: #69747c;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}
.hotel-address {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.hotel-price {
  flex-shrink: 0;
  text-align: right;
  font-size: 14px;
}
.hotel-price p:first-child {
  display: flex;
  gap: 6px;
  align-items: center;
  justify-content: flex-end;
}
.hotel-price svg {
  color: #d49a36;
}
.attraction-editor {
  display: grid;
  gap: 12px;
  width: 100%;
  max-width: 500px;
}
.attraction-editor label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
  color: #626e66;
}
.attraction-editor :deep(.ant-input-number) {
  width: 100%;
}
.edit-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 3px;
}
.edit-actions .ui-button {
  font-size: 12px;
  height: 34px;
  padding: 0 10px;
}
.delete-button {
  color: #a6473c;
}
.section-empty {
  padding: 16px 0;
}
@media (max-width: 1100px) {
  .meal-details {
    display: block;
  }
  .meal-details > p {
    margin-top: 4px;
  }
  .attraction-row {
    gap: 14px;
  }
  .attraction-photo {
    width: 30%;
    height: 130px;
  }
  .attraction-meta {
    gap: 8px;
  }
  .meal-row {
    flex-wrap: wrap;
    gap: 8px 16px;
  }
  .meal-address {
    display: flex;
    flex-basis: 100%;
    max-width: none;
    margin-left: 44px;
  }
}
@media (max-width: 600px) {
  .day-intro h3 {
    font-size: 19px;
  }
  .day-intro > p {
    font-size: 12px;
    gap: 8px;
  }
  .attraction-timeline {
    padding-left: 37px;
  }
  .attraction-timeline:before {
    left: 12px;
  }
  .stop-number {
    left: -37px;
    width: 27px;
    height: 27px;
    font-size: 12px;
  }
  .attraction-row {
    gap: 12px;
    flex-wrap: wrap;
  }
  .attraction-heading h3 {
    font-size: 17px;
  }
  .attraction-photo {
    width: 100%;
    height: 150px;
    max-width: none;
    order: 2;
  }
  .attraction-details {
    flex-basis: 100%;
  }
  .attraction-description {
    font-size: 13px;
  }
  .attraction-meta {
    font-size: 12px;
  }
  .meal-row {
    gap: 12px;
  }
  .hotel-row {
    gap: 10px;
  }
  .hotel-details p {
    font-size: 12px;
    gap: 5px;
  }
  .hotel-price {
    font-size: 12px;
    max-width: 30%;
    white-space: normal;
  }
  .attraction-editor {
    max-width: none;
  }
}
</style>
