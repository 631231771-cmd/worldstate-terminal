function pad(value: number): string { return String(value).padStart(2, "0"); }

/** Format a Date for a datetime-local input in the user's local timezone. */
export function toLocalDateTimeInput(value = new Date()): string {
  return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}T${pad(value.getHours())}:${pad(value.getMinutes())}`;
}

/** Convert a datetime-local value (which has no timezone) to a UTC ISO instant. */
export function fromLocalDateTimeInput(value: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(value);
  if (!match) throw new Error("Captured time is not a valid local date and time.");
  const [, year, month, day, hour, minute] = match;
  return new Date(Number(year), Number(month) - 1, Number(day), Number(hour), Number(minute)).toISOString();
}

export function localTimeZoneLabel(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || `UTC${-new Date().getTimezoneOffset() / 60 >= 0 ? "+" : ""}${-new Date().getTimezoneOffset() / 60}`;
}
