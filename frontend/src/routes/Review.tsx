import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { fetchResumes } from "../api/resumes";
import {
  REVIEW_ITEMS_KEY,
  batchConfirmReviewItems,
  confirmReviewItem,
  editConfirmReviewItem,
  fetchPendingReviewItems,
  rejectReviewItem,
} from "../api/review";
import type { BatchConfirmResult, ReviewItem } from "../api/review";
import { ClaimReviewEditor } from "./ClaimReviewEditor";
import { asClaimPayload } from "./claimPayload";
import { classificationLabel } from "./evidenceLabels";
import { batchFailureMessage, reviewErrorMessage, shouldRefresh } from "./reviewMessages";

const INVALID_JSON = "The edit must be a valid JSON object.";

function parseEdit(raw: string): Record<string, unknown> | null {
  try {
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
  } catch {
    return null;
  }
  return null;
}

function summary(item: ReviewItem): string {
  const claim = asClaimPayload(item);
  if (claim !== null) {
    return claim.statement;
  }
  const name = item.proposed_payload.name;
  return typeof name === "string" ? name : item.proposal_type.replaceAll("_", " ");
}

interface ReviewCardProps {
  item: ReviewItem;
  selected: boolean;
  onToggle: () => void;
  onNotice: (message: string | null) => void;
}

function ReviewCard({ item, selected, onToggle, onNotice }: ReviewCardProps) {
  const client = useQueryClient();
  const claim = asClaimPayload(item);
  const [mode, setMode] = useState<"view" | "edit" | "reject">("view");
  const [draft, setDraft] = useState(() => JSON.stringify(item.proposed_payload, null, 2));
  const [note, setNote] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);

  const done = useMutation({
    mutationFn: (action: () => Promise<ReviewItem>) => action(),
    onSuccess: () => {
      onNotice(null);
      return client.invalidateQueries({ queryKey: REVIEW_ITEMS_KEY });
    },
    onError: (error) => {
      if (shouldRefresh(error)) {
        onNotice(reviewErrorMessage(error));
        void client.invalidateQueries({ queryKey: REVIEW_ITEMS_KEY });
      }
    },
  });

  function submitEdit() {
    const payload = parseEdit(draft);
    if (payload === null) {
      setLocalError(INVALID_JSON);
      return;
    }
    setLocalError(null);
    done.mutate(() => editConfirmReviewItem(item, payload));
  }

  const message =
    localError ?? (done.isError && !shouldRefresh(done.error) ? reviewErrorMessage(done.error) : null);

  return (
    <li>
      <label>
        <input
          type="checkbox"
          checked={selected}
          disabled={!item.confirmable}
          aria-label={`Select ${summary(item)}`}
          onChange={onToggle}
        />
      </label>
      <h3>{item.proposal_type.replaceAll("_", " ")}</h3>
      <p>
        Source: {item.source}
        {item.confidence !== null && <> · Confidence: {Math.round(item.confidence * 100)}%</>}
      </p>
      {item.rationale && <p>{item.rationale}</p>}
      {claim === null ? (
        <pre>{JSON.stringify(item.proposed_payload, null, 2)}</pre>
      ) : (
        <div>
          <p>{claim.statement}</p>
          <p>
            {classificationLabel(claim.evidence_class, claim.engagement_type)}
            {claim.organization_label !== null && ` · ${claim.organization_label}`}
            {(claim.start_date !== null || claim.end_date !== null) &&
              ` · ${claim.start_date ?? "?"} to ${claim.end_date ?? "present"}`}
          </p>
          {claim.skill_names.length > 0 && <p>Skills: {claim.skill_names.join(", ")}</p>}
        </div>
      )}

      {mode === "edit" && claim !== null && (
        <ClaimReviewEditor
          proposed={claim}
          busy={done.isPending}
          onSave={(payload) => {
            done.mutate(() =>
              editConfirmReviewItem(item, payload as unknown as Record<string, unknown>),
            );
          }}
          onCancel={() => {
            setMode("view");
          }}
        />
      )}

      {mode === "edit" && claim === null && (
        <p>
          <label>
            Edited proposal (JSON)
            <textarea
              value={draft}
              rows={8}
              onChange={(event) => {
                setDraft(event.target.value);
              }}
            />
          </label>{" "}
          <button type="button" disabled={done.isPending} onClick={submitEdit}>
            Save and confirm
          </button>{" "}
          <button
            type="button"
            onClick={() => {
              setMode("view");
              setLocalError(null);
            }}
          >
            Cancel
          </button>
        </p>
      )}

      {mode === "reject" && (
        <p>
          <label>
            Reason (optional)
            <input
              value={note}
              maxLength={1000}
              onChange={(event) => {
                setNote(event.target.value);
              }}
            />
          </label>{" "}
          <button
            type="button"
            disabled={done.isPending}
            onClick={() => {
              done.mutate(() => rejectReviewItem(item, note));
            }}
          >
            Reject
          </button>{" "}
          <button
            type="button"
            onClick={() => {
              setMode("view");
            }}
          >
            Cancel
          </button>
        </p>
      )}

      {mode === "view" && (
        <p>
          <button
            type="button"
            disabled={!item.confirmable || done.isPending}
            onClick={() => {
              done.mutate(() => confirmReviewItem(item));
            }}
          >
            Confirm
          </button>{" "}
          <button
            type="button"
            disabled={!item.confirmable || done.isPending}
            onClick={() => {
              setMode("edit");
            }}
          >
            Edit and confirm
          </button>{" "}
          <button
            type="button"
            disabled={done.isPending}
            onClick={() => {
              setMode("reject");
            }}
          >
            Reject
          </button>
        </p>
      )}
      {!item.confirmable && (
        <p>This kind of proposal cannot be confirmed yet. You can reject it.</p>
      )}
      {message && <p role="alert">{message}</p>}
    </li>
  );
}

interface Group {
  key: string;
  title: string;
  items: ReviewItem[];
}

function groupItems(items: ReviewItem[], labels: Map<string, string>): Group[] {
  const groups = new Map<string, Group>();
  for (const item of items) {
    const key = item.evidence_ref_id ?? "other";
    const label = item.evidence_ref_id === null ? undefined : labels.get(item.evidence_ref_id);
    const title =
      item.evidence_ref_id === null
        ? "Other proposals"
        : `From resume: ${label ?? "a resume"}`;
    const group = groups.get(key) ?? { key, title, items: [] };
    group.items.push(item);
    groups.set(key, group);
  }
  return [...groups.values()];
}

export function Review() {
  const client = useQueryClient();
  const [notice, setNotice] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [outcome, setOutcome] = useState<{
    results: BatchConfirmResult[];
    names: Map<string, string>;
  } | null>(null);
  const items = useQuery({
    queryKey: REVIEW_ITEMS_KEY,
    queryFn: ({ signal }) => fetchPendingReviewItems(signal),
  });
  const resumes = useQuery({
    queryKey: ["resumes"],
    queryFn: ({ signal }) => fetchResumes(signal),
  });
  const batch = useMutation({
    mutationFn: (chosen: ReviewItem[]) => batchConfirmReviewItems(chosen),
    onSuccess: async (results, chosen) => {
      setOutcome({ results, names: new Map(chosen.map((item) => [item.id, summary(item)])) });
      setSelected(new Set(results.filter((result) => !result.ok).map((result) => result.id)));
      await Promise.all([
        client.invalidateQueries({ queryKey: REVIEW_ITEMS_KEY }),
        client.invalidateQueries({ queryKey: ["skills"] }),
        client.invalidateQueries({ queryKey: ["claims"] }),
      ]);
    },
  });

  const labels = new Map((resumes.data ?? []).map((resume) => [resume.id, resume.label]));
  const pending = items.data ?? [];
  const chosen = pending.filter((item) => selected.has(item.id));
  const failures = outcome?.results.filter((result) => !result.ok) ?? [];

  function toggle(id: string) {
    const next = new Set(selected);
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
    }
    setSelected(next);
  }

  function toggleGroup(group: Group) {
    const confirmable = group.items.filter((item) => item.confirmable);
    const all = confirmable.every((item) => selected.has(item.id));
    const next = new Set(selected);
    for (const item of confirmable) {
      if (all) {
        next.delete(item.id);
      } else {
        next.add(item.id);
      }
    }
    setSelected(next);
  }

  return (
    <section aria-labelledby="review-title">
      <h1 id="review-title">Review</h1>
      <p>Proposals wait here until you confirm, edit or reject them. Nothing changes until you do.</p>
      {notice && <p role="alert">{notice}</p>}
      {items.isPending && <p role="status">Loading…</p>}
      {items.isError && <p role="alert">Could not load review items.</p>}
      {items.isSuccess && items.data.length === 0 && <p>Nothing to review.</p>}
      {items.isSuccess && items.data.length > 0 && (
        <>
          <p>
            <button
              type="button"
              disabled={chosen.length === 0 || batch.isPending}
              onClick={() => {
                batch.mutate(chosen);
              }}
            >
              Confirm selected ({chosen.length})
            </button>
          </p>
          {batch.isError && <p role="alert">Could not confirm the selected items.</p>}
          {outcome !== null && (
            <div>
              <p role="status">
                Confirmed {outcome.results.length - failures.length} of {outcome.results.length}{" "}
                selected.
              </p>
              {failures.length > 0 && (
                <ul aria-label="Items that could not be confirmed" role="alert">
                  {failures.map((failure) => (
                    <li key={failure.id}>
                      {outcome.names.get(failure.id) ?? "An item"}:{" "}
                      {batchFailureMessage(failure.error_code)}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
          {groupItems(items.data, labels).map((group) => (
            <section key={group.key} aria-label={group.title}>
              <h2>{group.title}</h2>
              <p>
                <button
                  type="button"
                  onClick={() => {
                    toggleGroup(group);
                  }}
                >
                  Select all in {group.title}
                </button>
              </p>
              <ul>
                {group.items.map((item) => (
                  <ReviewCard
                    key={item.id}
                    item={item}
                    selected={selected.has(item.id)}
                    onToggle={() => {
                      toggle(item.id);
                    }}
                    onNotice={setNotice}
                  />
                ))}
              </ul>
            </section>
          ))}
        </>
      )}
    </section>
  );
}
