function pad(value: number): string {
  return String(value).padStart(2, "0");
}

export function todayLocal(now = new Date()): string {
  return `${String(now.getFullYear())}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

export function nowLocalInput(now = new Date()): string {
  return `${todayLocal(now)}T${pad(now.getHours())}:${pad(now.getMinutes())}`;
}

export function appliedAtFor(day: string, now = new Date()): string {
  return day === todayLocal(now) ? now.toISOString() : new Date(`${day}T12:00:00`).toISOString();
}
