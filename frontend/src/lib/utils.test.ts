import { describe, expect, it } from "vitest";
import { formatMoney, initials, scorePercent } from "@/lib/utils";

describe("formatMoney", () => {
  it("formats INR amounts for the Indian locale", () => {
    expect(formatMoney(350)).toContain("350");
    expect(formatMoney(350)).toContain("₹");
  });

  it("keeps paise when present", () => {
    expect(formatMoney(315.5)).toContain("315.5");
  });

  it("renders a dash for missing values", () => {
    expect(formatMoney(null)).toBe("—");
    expect(formatMoney(undefined)).toBe("—");
  });
});

describe("initials", () => {
  it("takes the first two word initials", () => {
    expect(initials("Ananya Desai")).toBe("AD");
    expect(initials("Ravi")).toBe("R");
    expect(initials(null)).toBe("?");
  });
});

describe("scorePercent", () => {
  it("converts match scores to rounded percentages", () => {
    expect(scorePercent(0.856)).toBe(86);
    expect(scorePercent(1)).toBe(100);
  });
});
