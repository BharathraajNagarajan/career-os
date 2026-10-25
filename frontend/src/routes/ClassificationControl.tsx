import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { changeClassification } from "../api/evidence";
import type { Claim, EngagementType, EvidenceClass } from "../api/evidence";
import {
  CLASS_OPTIONS,
  ENGAGEMENT_OPTIONS,
  classificationLabel,
  evidenceErrorMessage,
} from "./evidenceLabels";

interface ClassificationControlProps {
  claim: Claim;
  onChanged: () => Promise<unknown>;
}

export function ClassificationControl({ claim, onChanged }: ClassificationControlProps) {
  const [evidenceClass, setEvidenceClass] = useState<EvidenceClass>(claim.evidence_class);
  const [engagement, setEngagement] = useState<EngagementType>(
    claim.engagement_type ?? "unspecified",
  );
  const [confirming, setConfirming] = useState(false);
  const change = useMutation({
    mutationFn: () => changeClassification(claim, evidenceClass, engagement),
    onSuccess: async () => {
      setConfirming(false);
      await onChanged();
    },
  });

  const chosenEngagement = evidenceClass === "professional" ? engagement : null;
  const changed =
    evidenceClass !== claim.evidence_class || chosenEngagement !== claim.engagement_type;
  const from = classificationLabel(claim.evidence_class, claim.engagement_type);
  const to = classificationLabel(evidenceClass, chosenEngagement);

  return (
    <section aria-label={`Classification of ${claim.statement}`}>
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
        )}{" "}
        <button
          type="button"
          disabled={!changed || confirming}
          onClick={() => {
            setConfirming(true);
          }}
        >
          Change classification
        </button>
      </p>
      {confirming && (
        <div role="alertdialog" aria-label="Confirm classification change">
          <p>
            Change this evidence from <strong>{from}</strong> to <strong>{to}</strong>? This changes
            how it may be described and counted. Only you can make this change.
          </p>
          <button
            type="button"
            disabled={change.isPending}
            onClick={() => {
              change.mutate();
            }}
          >
            Confirm change
          </button>{" "}
          <button
            type="button"
            onClick={() => {
              setConfirming(false);
            }}
          >
            Cancel
          </button>
        </div>
      )}
      {change.isSuccess && !confirming && <p role="status">Classification changed.</p>}
      {change.isError && <p role="alert">{evidenceErrorMessage(change.error)}</p>}
    </section>
  );
}
