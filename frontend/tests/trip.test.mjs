import { test } from "node:test";
import assert from "node:assert/strict";
import {
  getTravelDays,
  readTripPlan,
  refreshAttractionBudget,
} from "../src/utils/trip.ts";

const plan = () => ({
  city: "杭州",
  start_date: "2026-10-23",
  end_date: "2026-10-25",
  days: [
    {
      day_index: 0,
      date: "2026-10-23",
      description: "湖畔漫步",
      transportation: "公共交通",
      accommodation: "经济型酒店",
      attractions: [
        {
          name: "西湖",
          address: "杭州",
          location: { longitude: 120.1, latitude: 30.2 },
          visit_duration: 120,
          description: "漫步",
          ticket_price: 20,
        },
      ],
      meals: [],
    },
  ],
  weather_info: [],
  overall_suggestions: "轻装出行",
  budget: {
    total_attractions: 60,
    total_hotels: 800,
    total_meals: 360,
    total_transportation: 120,
    total: 1340,
  },
});

test("travel days are inclusive and enforce valid calendar dates and 30-day limit", () => {
  assert.equal(getTravelDays("2026-10-23", "2026-10-25"), 3);
  assert.equal(getTravelDays("2026-10-23", "2026-10-23"), 1);
  assert.equal(getTravelDays("2026-03-07", "2026-03-09"), 3);
  assert.equal(getTravelDays("2026-10-23", "2026-10-22"), null);
  assert.equal(getTravelDays("2026-10-01", "2026-10-31"), null);
  assert.equal(getTravelDays("2026-02-30", "2026-03-02"), null);
  assert.equal(getTravelDays("", ""), null);
});

test("stored plans fail safely for corrupted or incomplete session data", () => {
  assert.equal(readTripPlan(null), null);
  assert.equal(readTripPlan("{invalid"), null);
  assert.equal(
    readTripPlan(JSON.stringify({ city: "杭州", days: [{}] })),
    null,
  );
  const broken = plan();
  broken.days[0].attractions[0].location = null;
  assert.equal(readTripPlan(JSON.stringify(broken)), null);
  assert.deepEqual(readTripPlan(JSON.stringify(plan())), plan());
});

test("removing attractions can refresh ticket totals without changing other budget categories", () => {
  const value = plan();
  refreshAttractionBudget(value);
  assert.equal(value.budget.total_attractions, 20);
  assert.equal(value.budget.total_hotels, 800);
  assert.equal(value.budget.total, 1300);
  value.days[0].attractions = [];
  refreshAttractionBudget(value);
  assert.equal(value.budget.total, 1280);
});
