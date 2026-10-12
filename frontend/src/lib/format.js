export function fmtDuration(seconds) {
  const mins = Math.round(seconds / 60);
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  if (h === 0) return `${m} min`;
  return `${h} h ${String(m).padStart(2, "0")} min`;
}

export function fmtMiles(mi, digits = 0) {
  return `${Number(mi).toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits })} mi`;
}

const dtf = new Intl.DateTimeFormat(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" });
const dtfLong = new Intl.DateTimeFormat(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

export const fmtTime = (iso) => dtf.format(new Date(iso));
export const fmtDateTime = (iso) => dtfLong.format(new Date(iso));

/** Value for <input type="datetime-local"> from a Date, in the browser's timezone. */
export function toLocalInput(date) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** ISO-8601 with the browser's UTC offset, from a datetime-local value. */
export function localInputToIso(value) {
  const d = new Date(value); // interpreted as local time
  const off = -d.getTimezoneOffset();
  const sign = off >= 0 ? "+" : "-";
  const pad = (n) => String(Math.floor(Math.abs(n))).padStart(2, "0");
  return `${value.length === 16 ? value + ":00" : value}${sign}${pad(off / 60)}:${pad(off % 60)}`;
}

export function nextQuarterHour(now = new Date()) {
  const d = new Date(now);
  d.setSeconds(0, 0);
  d.setMinutes(Math.ceil((d.getMinutes() + 1) / 15) * 15);
  return d;
}
