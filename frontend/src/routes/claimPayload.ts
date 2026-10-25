import type { EngagementType, EvidenceClass } from "../api/evidence";
import type { ReviewItem } from "../api/review";

export interface ClaimPayload {
  schema_version: number;
  statement: string;
  evidence_class: EvidenceClass;
  engagement_type: EngagementType | null;
  start_date: string | null;
  end_date: string | null;
  organization_label: string | null;
  skill_names: string[];
  resume_id: string;
  confirm_class_change?: boolean;
}

export function asClaimPayload(item: ReviewItem): ClaimPayload | null {
  const payload = item.proposed_payload;
  if (item.proposal_type !== "claim" || typeof payload.statement !== "string") {
    return null;
  }
  return payload as unknown as ClaimPayload;
}
