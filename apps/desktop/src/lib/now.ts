import { FIXTURE_MODE } from "@/api/client";

// Fixture data is exported at a fixed instant; relative times ("in 2h") are computed against it so
// screenshots and tests don't change with the wall clock.
export const FIXTURE_NOW = Date.parse("2026-10-02T18:00:00Z");

export function nowMs(): number {
  return FIXTURE_MODE ? FIXTURE_NOW : Date.now();
}
