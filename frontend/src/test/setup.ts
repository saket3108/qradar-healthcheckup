import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => { cleanup(); localStorage.clear(); });

class RO { observe() {} unobserve() {} disconnect() {} }
(globalThis as unknown as { ResizeObserver: typeof RO }).ResizeObserver = RO;
(globalThis as unknown as { DOMMatrixReadOnly: unknown }).DOMMatrixReadOnly = class { m22 = 1; constructor() {} };
Object.defineProperty(window, "matchMedia", { writable: true, value: (q: string) => ({ matches: false, media: q, addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(), onchange: null, dispatchEvent: vi.fn() }) });
Element.prototype.scrollIntoView = vi.fn();

// jsdom has no layout engine, so recharts' ResponsiveContainer always measures 0x0 and warns. Not a defect.
const origError = console.error, origWarn = console.warn;
const noise = (a: unknown[]) => typeof a[0] === "string" && a[0].includes("of chart should be greater than 0");
console.error = (...a: unknown[]) => { if (!noise(a)) origError(...a); };
console.warn = (...a: unknown[]) => { if (!noise(a)) origWarn(...a); };
Object.defineProperty(window, "scrollTo", { writable: true, value: vi.fn() });
