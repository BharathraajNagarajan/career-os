import { useState } from "react";
import type { SubmitEvent } from "react";

import type { EngagementType, EvidenceClass } from "../api/evidence";
import type { ClaimPayload } from "./claimPayload";
import {
  CLASS_OPTIONS,
  ENGAGEMENT_OPTIONS,
  classificationLabel,
} from "./evidenceLabels";

interface ClaimReviewEditorProps {
  proposed: ClaimPayload;
  busy: boolean;
  onSave: (payload: ClaimPayload) => void;
  onCancel: () => void;
}

export function ClaimReviewEditor({ proposed, busy, onSave, onCancel }: ClaimReviewEditorProps) {
  const [statement, setStatement] = useState(proposed.statement);
  const [organization, setOrganization] = useState(proposed.organization_label ?? "");
  const [startDate, setStartDate] = useState(proposed.start_date ?? "");
  const [endDate, setEndDate] = useState(proposed.end_date ?? "");
  const [skills, setSkills] = useState(proposed.skill_names.join(", "));
  const [evidenceClass, setEvidenceClass] = useState<EvidenceClass>(proposed.evidence_class);
  const [engagement, setEngagement] = useState<EngagementType>(
    proposed.engagement_type ?? "unspecified",
  );
  const [confirming, setConfirming] = useState(false);

  const chosenEngagement = evidenceClass === "professional" ? engagement : null;
  const classChanged =
    evidenceClass !== proposed.evidence_class || chosenEngagement !== proposed.engagement_type;

  function build(confirmClassChange: boolean): ClaimPayload {
    return {
      ...proposed,
      statement: statement.trim(),
      organization_label: organization.trim() === "" ? null : organization.trim(),
      start_date: startDate === "" ? null : startDate,
      end_date: endDate === "" ? null : endDate,
      skill_names: skills
        .split(",")
        .map((name) => name.trim())
        .filter((name) => name !== ""),
      evidence_class: evidenceClass,
      engagement_type: chosenEngagement,
      confirm_class_change: confirmClassChange,
    };
  }

  function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (classChanged) {
      setConfirming(true);
      return;
    }
    onSave(build(false));
  }

  return (
    <form aria-label="Edit proposed evidence" onSubmit={submit}>
      <p>
        <label>
          Statement
          <textarea
            value={statement}
            rows={3}
            maxLength={2000}
            onChange={(event) => {
              setStatement(event.target.value);
            }}
          />
        </label>
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
          End date
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
          Evidence class
          <select
            value={evidenceClass}
            onChange={(event) => {
              setEvidenceClass(event.target.value as EvidenceClass);
              setConfirming(false);
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
                setConfirming(false);
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
          Skills (separated by commas)
          <input
            value={skills}
            onChange={(event) => {
              setSkills(event.target.value);
            }}
          />
        </label>
      </p>
      {confirming && (
        <div role="alertdialog" aria-label="Confirm classification change">
          <p>
            Change this evidence from{" "}
            <strong>{classificationLabel(proposed.evidence_class, proposed.engagement_type)}</strong>{" "}
            to <strong>{classificationLabel(evidenceClass, chosenEngagement)}</strong>? Only you can
            make this change.
          </p>
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              onSave(build(true));
            }}
          >
            Confirm change and save
          </button>{" "}
          <button
            type="button"
            onClick={() => {
              setConfirming(false);
            }}
          >
            Keep proposed class
          </button>
        </div>
      )}
      {!confirming && (
        <p>
          <button type="submit" disabled={busy || statement.trim() === ""}>
            Save and confirm
          </button>{" "}
          <button type="button" onClick={onCancel}>
            Cancel
          </button>
        </p>
      )}
    </form>
  );
}
