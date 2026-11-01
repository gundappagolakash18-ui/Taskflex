import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// Node.js >= 22 ships an experimental global `localStorage` that is inert
// without `--localstorage-file` (a plain object with no Storage methods).
// It shadows jsdom's implementation because vitest's `window` IS `globalThis`
// in this environment, so remove it when it lacks Storage methods and let
// jsdom provide the real one.
const ls = globalThis.localStorage as Storage | undefined;
if (ls && typeof ls.clear !== "function") {
  delete (globalThis as { localStorage?: unknown }).localStorage;
}

afterEach(() => {
  cleanup();
  globalThis.localStorage?.clear?.();
});
