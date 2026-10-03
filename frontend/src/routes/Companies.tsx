import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { COMPANIES_KEY, fetchCompanies, patchCompany } from "../api/companies";
import type { Company } from "../api/companies";
import type { Priority } from "../api/opportunities";
import { companyErrorMessage } from "./opportunityMessages";

const PRIORITIES: Priority[] = ["high", "normal", "low"];

function splitList(value: string, separator: RegExp): string[] {
  return value
    .split(separator)
    .map((part) => part.trim())
    .filter((part) => part !== "");
}

function CompanyCard({ company }: { company: Company }) {
  const client = useQueryClient();
  const [name, setName] = useState(company.name);
  const [aliases, setAliases] = useState(company.aliases.join("\n"));
  const [domains, setDomains] = useState(company.domains.join("\n"));
  const [careersUrl, setCareersUrl] = useState(company.careers_url ?? "");
  const [notes, setNotes] = useState(company.notes);
  const [priority, setPriority] = useState<Priority>(company.strategic_priority);
  const save = useMutation({
    mutationFn: () =>
      patchCompany(company.id, {
        name,
        aliases: splitList(aliases, /\n/),
        domains: splitList(domains, /[\s,]+/),
        careers_url: careersUrl.trim() === "" ? null : careersUrl.trim(),
        notes,
        strategic_priority: priority,
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: COMPANIES_KEY }),
  });

  return (
    <li>
      <form
        aria-label={`Edit ${company.name}`}
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate();
        }}
      >
        <h2>{company.name}</h2>
        <p>
          Origin: {company.origin === "extracted" ? "added by extraction" : "added by you"}
        </p>
        <p>
          <label>
            Name
            <input
              value={name}
              maxLength={200}
              onChange={(event) => {
                setName(event.target.value);
              }}
            />
          </label>
        </p>
        <p>
          <label>
            Strategic priority
            <select
              value={priority}
              onChange={(event) => {
                setPriority(event.target.value as Priority);
              }}
            >
              {PRIORITIES.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
        </p>
        <p>
          <label>
            Aliases (one per line)
            <textarea
              value={aliases}
              rows={2}
              onChange={(event) => {
                setAliases(event.target.value);
              }}
            />
          </label>
        </p>
        <p>
          <label>
            Domains (one per line)
            <textarea
              value={domains}
              rows={2}
              onChange={(event) => {
                setDomains(event.target.value);
              }}
            />
          </label>
        </p>
        <p>
          <label>
            Careers URL
            <input
              value={careersUrl}
              maxLength={2048}
              onChange={(event) => {
                setCareersUrl(event.target.value);
              }}
            />
          </label>
        </p>
        <p>
          <label>
            Notes
            <textarea
              value={notes}
              rows={3}
              maxLength={5000}
              onChange={(event) => {
                setNotes(event.target.value);
              }}
            />
          </label>
        </p>
        <button type="submit" disabled={save.isPending || name.trim() === ""}>
          Save company
        </button>
        {save.isSuccess && <p role="status">Saved.</p>}
        {save.isError && <p role="alert">{companyErrorMessage(save.error)}</p>}
      </form>
    </li>
  );
}

export function Companies() {
  const companies = useQuery({
    queryKey: COMPANIES_KEY,
    queryFn: ({ signal }) => fetchCompanies(signal),
  });

  return (
    <section aria-labelledby="companies-title">
      <h1 id="companies-title">Companies</h1>
      <p>
        Companies are matched by domain, name or alias when a job description is extracted. The
        strategic priority is yours to set.
      </p>
      {companies.isPending && <p role="status">Loading…</p>}
      {companies.isError && <p role="alert">Could not load companies.</p>}
      {companies.isSuccess && companies.data.length === 0 && <p>No companies yet.</p>}
      {companies.isSuccess && companies.data.length > 0 && (
        <ul>
          {companies.data.map((company) => (
            <CompanyCard key={`${company.id}:${company.updated_at}`} company={company} />
          ))}
        </ul>
      )}
    </section>
  );
}
