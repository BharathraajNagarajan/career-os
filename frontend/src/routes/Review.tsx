import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  REVIEW_ITEMS_KEY,
  confirmReviewItem,
  editConfirmReviewItem,
  fetchPendingReviewItems,
  rejectReviewItem,
} from "../api/review";
import type { ReviewItem } from "../api/review";
import { reviewErrorMessage, shouldRefresh } from "./reviewMessages";

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

interface ReviewCardProps {
  item: ReviewItem;
  onNotice: (message: string | null) => void;
}

function ReviewCard({ item, onNotice }: ReviewCardProps) {
  const client = useQueryClient();
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
      <h2>{item.proposal_type.replaceAll("_", " ")}</h2>
      <p>
        Source: {item.source}
        {item.confidence !== null && <> · Confidence: {Math.round(item.confidence * 100)}%</>}
      </p>
      {item.rationale && <p>{item.rationale}</p>}
      <pre>{JSON.stringify(item.proposed_payload, null, 2)}</pre>

      {mode === "edit" && (
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

export function Review() {
  const [notice, setNotice] = useState<string | null>(null);
  const items = useQuery({
    queryKey: REVIEW_ITEMS_KEY,
    queryFn: ({ signal }) => fetchPendingReviewItems(signal),
  });

  return (
    <section aria-labelledby="review-title">
      <h1 id="review-title">Review</h1>
      <p>Proposals wait here until you confirm, edit or reject them. Nothing changes until you do.</p>
      {notice && <p role="alert">{notice}</p>}
      {items.isPending && <p role="status">Loading…</p>}
      {items.isError && <p role="alert">Could not load review items.</p>}
      {items.isSuccess && items.data.length === 0 && <p>Nothing to review.</p>}
      {items.isSuccess && items.data.length > 0 && (
        <ul>
          {items.data.map((item) => (
            <ReviewCard key={item.id} item={item} onNotice={setNotice} />
          ))}
        </ul>
      )}
    </section>
  );
}
