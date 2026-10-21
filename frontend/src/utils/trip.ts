import type { TripPlan } from "../types/index";

export function getTravelDays(start: string, end: string): number | null {
  const toDate = (value: string) => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return NaN;
    const time = Date.parse(`${value}T00:00:00Z`);
    return Number.isFinite(time) &&
      new Date(time).toISOString().slice(0, 10) === value
      ? time
      : NaN;
  };
  const days = (toDate(end) - toDate(start)) / 86400000 + 1;
  return Number.isInteger(days) && days > 0 && days <= 30 ? days : null;
}
const record = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === "object" && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === "string";
const finite = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value);

export function readTripPlan(raw: string | null): TripPlan | null {
  try {
    const plan: unknown = JSON.parse(raw || "null");
    if (
      !record(plan) ||
      !text(plan.city) ||
      !text(plan.start_date) ||
      !text(plan.end_date) ||
      !getTravelDays(plan.start_date, plan.end_date) ||
      !text(plan.overall_suggestions) ||
      !Array.isArray(plan.days) ||
      !plan.days.length ||
      !Array.isArray(plan.weather_info)
    )
      return null;
    for (const day of plan.days) {
      if (
        !record(day) ||
        !text(day.date) ||
        !finite(day.day_index) ||
        !text(day.description) ||
        !text(day.transportation) ||
        !text(day.accommodation) ||
        !Array.isArray(day.attractions) ||
        !Array.isArray(day.meals)
      )
        return null;
      for (const attraction of day.attractions) {
        if (
          !record(attraction) ||
          !text(attraction.name) ||
          !text(attraction.address) ||
          !text(attraction.description) ||
          !finite(attraction.visit_duration) ||
          !record(attraction.location) ||
          !finite(attraction.location.longitude) ||
          !finite(attraction.location.latitude)
        )
          return null;
      }
      if (
        day.meals.some(
          (meal) => !record(meal) || !text(meal.name) || !text(meal.type),
        )
      )
        return null;
      if (
        day.hotel != null &&
        (!record(day.hotel) ||
          !text(day.hotel.name) ||
          !text(day.hotel.address))
      )
        return null;
    }
    if (
      plan.budget != null &&
      (!record(plan.budget) ||
        [
          "total_attractions",
          "total_hotels",
          "total_meals",
          "total_transportation",
          "total",
        ].some((key) => !finite((plan.budget as Record<string, unknown>)[key])))
    )
      return null;
    if (
      plan.weather_info.some(
        (weather) =>
          !record(weather) ||
          !text(weather.date) ||
          !text(weather.day_weather) ||
          !text(weather.night_weather) ||
          !finite(weather.day_temp) ||
          !finite(weather.night_temp),
      )
    )
      return null;
    return plan as unknown as TripPlan;
  } catch {
    return null;
  }
}

export function refreshAttractionBudget(plan: TripPlan) {
  if (!plan.budget) return;
  const tickets = plan.days
    .flatMap((day) => day.attractions)
    .reduce((sum, item) => sum + (item.ticket_price || 0), 0);
  plan.budget.total_attractions = Math.round(tickets * 100) / 100;
  plan.budget.total =
    Math.round(
      (tickets +
        plan.budget.total_hotels +
        plan.budget.total_meals +
        plan.budget.total_transportation) *
        100,
    ) / 100;
}
export const formatMoney = (value: number) =>
  new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(value);
