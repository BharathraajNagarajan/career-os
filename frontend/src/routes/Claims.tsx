import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { CLAIMS_KEY, fetchClaims } from "../api/evidence";
import type { ClaimFilters } from "../api/evidence";
import { ClaimForm } from "./ClaimForm";
import { ClaimListItem } from "./ClaimListItem";
import { CLASS_OPTIONS } from "./evidenceLabels";

export function Claims() {
  const [filters, setFilters] = useState<ClaimFilters>({ status: "", evidenceClass: "" });
  const claims = useQuery({
    queryKey: [...CLAIMS_KEY, "list", filters.status, filters.evidenceClass],
    queryFn: ({ signal }) => fetchClaims(filters, signal),
  });

  return (
    <section aria-labelledby="claims-title">
      <h1 id="claims-title">Evidence</h1>
      <p>
        Each piece of evidence is one statement about your experience, with one class and at least
        one source. Evidence you confirm in Review or add here appears under its skills.
      </p>
      <p>
        <label>
          Filter by status
          <select
            value={filters.status}
            onChange={(event) => {
              setFilters({ ...filters, status: event.target.value as ClaimFilters["status"] });
            }}
          >
            <option value="">All</option>
            <option value="confirmed">Confirmed</option>
            <option value="rejected">Rejected</option>
          </select>
        </label>{" "}
        <label>
          Filter by evidence class
          <select
            value={filters.evidenceClass}
            onChange={(event) => {
              setFilters({
                ...filters,
                evidenceClass: event.target.value as ClaimFilters["evidenceClass"],
              });
            }}
          >
            <option value="">All</option>
            {CLASS_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </p>
      {claims.isPending && <p role="status">Loading…</p>}
      {claims.isError && <p role="alert">Could not load evidence.</p>}
      {claims.isSuccess && claims.data.length === 0 && <p>No evidence found.</p>}
      {claims.isSuccess && claims.data.length > 0 && (
        <ul>
          {claims.data.map((claim) => (
            <ClaimListItem key={claim.id} claim={claim} />
          ))}
        </ul>
      )}
      <ClaimForm skillIds={[]} heading="Add evidence" />
    </section>
  );
}
