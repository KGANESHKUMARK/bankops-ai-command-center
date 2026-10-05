import { describe, expect, it } from "vitest";
import { formatDuration, formatMetric, formatNumber, formatSeconds, formatUsd, humanize, pct } from "./format";

describe("humanize", () => {
  it("replaces underscores and colons with spaces and capitalizes", () => {
    expect(humanize("operations_analyst")).toBe("Operations analyst");
    expect(humanize("pending_approval")).toBe("Pending approval");
    expect(humanize("production_ready")).toBe("Production ready");
  });
  it("handles single words and already-clean strings", () => {
    expect(humanize("open")).toBe("Open");
    expect(humanize("Open")).toBe("Open");
  });
  it("returns — for empty/null", () => {
    expect(humanize("")).toBe("—");
    expect(humanize(null)).toBe("—");
  });
});

describe("formatDuration", () => {
  it("formats milliseconds and seconds", () => {
    expect(formatDuration(0)).toBe("0 ms");
    expect(formatDuration(999)).toBe("999 ms");
    expect(formatDuration(1000)).toBe("1.0 s");
    expect(formatDuration(1500)).toBe("1.5 s");
  });
  it("formats minutes", () => {
    expect(formatDuration(65_000)).toBe("1m 5s");
    expect(formatDuration(125_000)).toBe("2m 5s");
  });
  it("handles null", () => {
    expect(formatDuration(null)).toBe("—");
  });
});

describe("formatSeconds", () => {
  it("formats seconds via formatDuration", () => {
    expect(formatSeconds(0)).toBe("0 ms");
    expect(formatSeconds(1.5)).toBe("1.5 s");
    expect(formatSeconds(120)).toBe("2m 0s");
  });
  it("handles null", () => {
    expect(formatSeconds(null)).toBe("—");
  });
});

describe("formatNumber", () => {
  it("adds locale-appropriate thousands separators", () => {
    const result = formatNumber(1234567);
    expect(result).not.toBe("1234567");
    expect(result).toMatch(/[,.]/);
    expect(result).toMatch(/567$/);
    expect(formatNumber(0)).toBe("0");
  });
  it("handles null", () => {
    expect(formatNumber(null)).toBe("—");
  });
});

describe("formatUsd", () => {
  it("formats USD with 2 decimal places for normal values", () => {
    expect(formatUsd(0)).toBe("$0.00");
    expect(formatUsd(1.5)).toBe("$1.50");
  });
  it("formats tiny values with 6 decimal places", () => {
    expect(formatUsd(0.0023)).toBe("$0.002300");
  });
  it("handles null", () => {
    expect(formatUsd(null)).toBe("—");
  });
});

describe("pct", () => {
  it("formats a ratio as a percentage with configurable digits", () => {
    expect(pct(0.5)).toBe("50%");
    expect(pct(1)).toBe("100%");
    expect(pct(0.3333, 1)).toBe("33.3%");
  });
  it("handles null", () => {
    expect(pct(null)).toBe("—");
  });
});

describe("formatMetric", () => {
  it("passes through integers", () => {
    expect(formatMetric(42)).toBe("42");
  });
  it("formats floats with 3 decimals", () => {
    expect(formatMetric(0.875)).toBe("0.875");
  });
  it("handles null and undefined", () => {
    expect(formatMetric(null)).toBe("—");
    expect(formatMetric(undefined)).toBe("—");
  });
  it("handles booleans and arrays", () => {
    expect(formatMetric(true)).toBe("true");
    expect(formatMetric(["a", "b"])).toBe("a, b");
    expect(formatMetric([])).toBe("none");
  });
});
