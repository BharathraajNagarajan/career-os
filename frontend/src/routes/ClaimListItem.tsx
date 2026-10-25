import { Link } from "react-router-dom";

import type { Claim } from "../api/evidence";
import { classificationLabel, dateRange, sourceLabel } from "./evidenceLabels";

export function ClaimListItem({ claim }: { claim: Claim }) {
  const range = dateRange(claim);
  return (
    <li>
      <Link to={`/claims/${claim.id}`}>{claim.statement}</Link>
      <br />
      <span>
        {classificationLabel(claim.evidence_class, claim.engagement_type)}
        {claim.confirmation_status === "rejected" && " · Rejected"}
        {claim.organization_label !== null && ` · ${claim.organization_label}`}
        {range !== null && ` · ${range}`}
      </span>
      <ul aria-label="Sources">
        {claim.sources.map((source) => (
          <li key={source.id}>{sourceLabel(source)}</li>
        ))}
      </ul>
    </li>
  );
}
