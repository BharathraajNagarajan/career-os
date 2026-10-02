import { useQuery } from "@tanstack/react-query";

import { fetchBudget } from "../api/llm";

function dollars(amount: string): string {
  const value = Number(amount);
  return `$${value >= 0.01 || value === 0 ? value.toFixed(2) : value.toFixed(4)}`;
}

export function BudgetIndicator() {
  const budget = useQuery({
    queryKey: ["llm-budget"],
    queryFn: ({ signal }) => fetchBudget(signal),
  });

  if (budget.isPending) {
    return <p role="status">Loading AI budget…</p>;
  }
  if (budget.isError) {
    return <p role="alert">Could not load the AI budget.</p>;
  }
  const exhausted = Number(budget.data.remaining_usd) <= 0;
  return (
    <>
      <p>
        <meter
          aria-label="AI budget used today"
          min={0}
          max={Number(budget.data.cap_usd)}
          value={Math.min(Number(budget.data.spent_usd), Number(budget.data.cap_usd))}
        />{" "}
        {dollars(budget.data.spent_usd)} of {dollars(budget.data.cap_usd)} spent today. Resets at
        00:00 UTC.
      </p>
      {exhausted && (
        <p role="alert">
          You have reached today&rsquo;s AI budget of {dollars(budget.data.cap_usd)}. AI features
          pause until 00:00 UTC. Everything else keeps working.
        </p>
      )}
    </>
  );
}
