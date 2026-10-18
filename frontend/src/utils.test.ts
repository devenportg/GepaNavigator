import { describe, expect, it } from "vitest";
import { ZONE_META, age, fmtDate, pct } from "./utils";

describe("utils", () => {
  it("форматирует даты по-русски", () => {
    expect(fmtDate("2026-01-05")).toBe("05.01.2026");
    expect(fmtDate(null)).toBe("—");
  });
  it("считает возраст с учётом дня рождения", () => {
    expect(age("2000-06-15", new Date(2026, 5, 14))).toBe(25);
    expect(age("2000-06-15", new Date(2026, 5, 15))).toBe(26);
  });
  it("проценты и зоны по ТЗ (4 цвета рабочего места)", () => {
    expect(pct(0.5)).toBe("50%");
    expect(pct(null)).toBe("—");
    expect(Object.keys(ZONE_META).sort()).toEqual(["green", "purple", "red", "yellow"]);
    expect(ZONE_META.purple.label).toContain("УВО");
  });
});
