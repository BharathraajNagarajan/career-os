export interface Health {
  status: "ok";
  version: string;
}

export async function fetchHealth(signal?: AbortSignal): Promise<Health> {
  const response = await fetch("/healthz", { signal: signal ?? null });
  if (!response.ok) {
    throw new Error(`Health check failed with status ${String(response.status)}`);
  }
  return (await response.json()) as Health;
}
