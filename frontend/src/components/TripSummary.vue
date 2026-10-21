<script setup lang="ts">
import type { Budget, WeatherInfo } from "@/types";
import { formatMoney } from "@/utils/trip";
import AppIcon from "./AppIcon.vue";
defineProps<{ budget?: Budget; weather: WeatherInfo[] }>();
const weatherIcon = (value: string) =>
  /雨|雪/.test(value) ? "rain" : /晴/.test(value) ? "sun" : "cloud";
</script>

<template>
  <section v-if="budget" class="budget-section">
    <h2 class="section-heading">预算明细</h2>
    <dl class="budget-list">
      <div>
        <dt>景点门票</dt>
        <dd>¥{{ formatMoney(budget.total_attractions) }}</dd>
      </div>
      <div>
        <dt>酒店住宿</dt>
        <dd>¥{{ formatMoney(budget.total_hotels) }}</dd>
      </div>
      <div>
        <dt>餐饮费用</dt>
        <dd>¥{{ formatMoney(budget.total_meals) }}</dd>
      </div>
      <div>
        <dt>交通费用</dt>
        <dd>¥{{ formatMoney(budget.total_transportation) }}</dd>
      </div>
      <div class="budget-total">
        <dt>预估总费用</dt>
        <dd>¥{{ formatMoney(budget.total) }}</dd>
      </div>
    </dl>
  </section>
  <section v-if="weather.length" class="weather-section">
    <h2 class="section-heading">出行天气</h2>
    <div class="weather-list">
      <div v-for="item in weather" :key="item.date" class="weather-item">
        <p class="weather-date">{{ item.date.slice(5).replace("-", ".") }}</p>
        <div class="weather-main">
          <AppIcon :name="weatherIcon(item.day_weather)" :size="29" />
          <div>
            <p>{{ item.day_weather }}</p>
            <p class="temperature">
              {{ item.night_temp }}° / {{ item.day_temp }}°
            </p>
          </div>
        </div>
        <p class="weather-extra">夜间{{ item.night_weather }}</p>
        <p v-if="item.wind_direction" class="weather-extra">
          {{ item.wind_direction }} {{ item.wind_power }}
        </p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.budget-section {
  margin-top: 28px;
}
.budget-list {
  margin: 0;
}
.budget-list > div {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 20px;
  padding: 12px 0;
  border-bottom: 1px solid var(--line);
  font-size: 14px;
  color: #747c85;
}
.budget-list dt,
.budget-list dd {
  margin: 0;
}
.budget-list dd {
  font-variant-numeric: tabular-nums;
}
.budget-list .budget-total {
  padding-top: 16px;
  border: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--ink);
}
.budget-total dd {
  font-size: 24px;
  color: var(--green);
  font-weight: 650;
}
.weather-section {
  margin-top: 27px;
}
.weather-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
  row-gap: 22px;
}
.weather-item {
  padding: 0 14px;
  border-right: 1px solid var(--line);
}
.weather-item:last-child {
  border-right: 0;
}
.weather-date {
  font-size: 12px;
  color: var(--muted);
  text-align: center;
  margin-bottom: 16px;
}
.weather-main {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 10px;
  font-size: 14px;
}
.weather-main > svg {
  flex-shrink: 0;
  color: #758b7b;
}
.temperature {
  font-size: 13px;
  margin-top: 4px;
  white-space: nowrap;
}
.weather-extra {
  font-size: 11px;
  color: var(--muted);
  text-align: center;
  margin-top: 7px;
}
.section-heading {
  margin-bottom: 10px;
}
@media (max-width: 600px) {
  .weather-list {
    grid-template-columns: repeat(auto-fit, minmax(90px, 1fr));
  }
  .weather-item {
    padding: 0 8px;
  }
  .weather-main {
    gap: 6px;
    font-size: 13px;
  }
  .weather-main > svg {
    width: 25px;
  }
  .budget-total dd {
    font-size: 23px;
  }
}
</style>
