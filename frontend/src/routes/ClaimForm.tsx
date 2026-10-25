import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { SubmitEvent } from "react";

import { CLAIMS_KEY, SKILLS_KEY, createClaim } from "../api/evidence";
import type { EngagementType, EvidenceClass, SourceCreate } from "../api/evidence";
import { CLASS_OPTIONS, ENGAGEMENT_OPTIONS, evidenceErrorMessage } from "./evidenceLabels";

interface ClaimFormProps {
  skillIds: string[];
  heading: string;
}

export function ClaimForm({ skillIds, heading }: ClaimFormProps) {
  const client = useQueryClient();
  const [statement, setStatement] = useState("");
  const [evidenceClass, setEvidenceClass] = useState<EvidenceClass>("project");
  const [engagement, setEngagement] = useState<EngagementType>("unspecified");
  const [organization, setOrganization] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [words, setWords] = useState("");
  const [url, setUrl] = useState("");
  const create = useMutation({
    mutationFn: () => {
      const sources: SourceCreate[] = [];
      if (words.trim() !== "") {
        sources.push({ source_type: "user_assertion", assertion_text: words.trim() });
      }
      if (url.trim() !== "") {
        sources.push({ source_type: "project_url", url: url.trim() });
      }
      return createClaim({
        statement: statement.trim(),
        evidence_class: evidenceClass,
        engagement_type: evidenceClass === "professional" ? engagement : null,
        organization_label: organization.trim() === "" ? null : organization.trim(),
        start_date: startDate === "" ? null : startDate,
        end_date: endDate === "" ? null : endDate,
        skill_ids: skillIds,
        sources,
      });
    },
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: CLAIMS_KEY }),
        client.invalidateQueries({ queryKey: SKILLS_KEY }),
      ]);
    },
  });
  const hasSource = words.trim() !== "" || url.trim() !== "";

  return (
    <form
      aria-label={heading}
      onSubmit={(event: SubmitEvent<HTMLFormElement>) => {
        event.preventDefault();
        create.mutate();
      }}
    >
      <h2>{heading}</h2>
      <p>
        <label>
          Statement
          <textarea
            value={statement}
            maxLength={2000}
            rows={3}
            onChange={(event) => {
              setStatement(event.target.value);
            }}
          />
        </label>
      </p>
      <p>
        <label>
          Evidence class
          <select
            value={evidenceClass}
            onChange={(event) => {
              setEvidenceClass(event.target.value as EvidenceClass);
            }}
          >
            {CLASS_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>{" "}
        {evidenceClass === "professional" && (
          <label>
            Engagement type
            <select
              value={engagement}
              onChange={(event) => {
                setEngagement(event.target.value as EngagementType);
              }}
            >
              {ENGAGEMENT_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        )}
      </p>
      <p>
        <label>
          Organization
          <input
            value={organization}
            maxLength={200}
            onChange={(event) => {
              setOrganization(event.target.value);
            }}
          />
        </label>{" "}
        <label>
          Start date
          <input
            type="date"
            value={startDate}
            onChange={(event) => {
              setStartDate(event.target.value);
            }}
          />
        </label>{" "}
        <label>
          End date (leave empty if ongoing)
          <input
            type="date"
            value={endDate}
            onChange={(event) => {
              setEndDate(event.target.value);
            }}
          />
        </label>
      </p>
      <p>
        <label>
          Your own words about this work
          <textarea
            value={words}
            maxLength={2000}
            rows={2}
            onChange={(event) => {
              setWords(event.target.value);
            }}
          />
        </label>
      </p>
      <p>
        <label>
          Project link (optional)
          <input
            type="url"
            value={url}
            onChange={(event) => {
              setUrl(event.target.value);
            }}
          />
        </label>
      </p>
      <p>Every piece of evidence needs at least one source: your own words or a project link.</p>
      <button type="submit" disabled={create.isPending || statement.trim() === "" || !hasSource}>
        Add evidence
      </button>
      {create.isSuccess && <p role="status">Evidence added.</p>}
      {create.isError && <p role="alert">{evidenceErrorMessage(create.error)}</p>}
    </form>
  );
}
