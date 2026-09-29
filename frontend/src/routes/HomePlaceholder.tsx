import { useQuery } from "@tanstack/react-query";

import { fetchHealth } from "../api/health";

export function HomePlaceholder() {
  const health = useQuery({
    queryKey: ["health"],
    queryFn: ({ signal }) => fetchHealth(signal),
  });

  return (
    <section aria-labelledby="home-title">
      <h1 id="home-title">Home</h1>
      <p>Your attention feed arrives in a later task. This page confirms the app can reach the API.</p>
      <p role="status" className={`api-status api-status-${health.status}`}>
        {health.isPending && "Checking the API…"}
        {health.isSuccess && `API connected (version ${health.data.version})`}
        {health.isError && "API unreachable. Start the backend and reload."}
      </p>
    </section>
  );
}
