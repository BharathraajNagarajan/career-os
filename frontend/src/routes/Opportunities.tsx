import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import type { SubmitEvent } from "react";
import { Link } from "react-router-dom";

import { ApiRequestError } from "../api/client";
import { OPPORTUNITIES_KEY, fetchOpportunities, ingestOpportunity } from "../api/opportunities";
import { extractionMessage, ingestErrorMessage } from "./opportunityMessages";

export const POLL_INTERVAL_MS = 2000;
export const MAX_POLLS = 60;

export function Opportunities() {
  const client = useQueryClient();
  const polls = useRef(0);
  const [jdText, setJdText] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const list = useQuery({
    queryKey: OPPORTUNITIES_KEY,
    queryFn: ({ signal }) => fetchOpportunities(signal),
    refetchInterval: (query) => {
      const pending = query.state.data?.some((row) => row.extraction_status === "pending");
      if (!pending) {
        polls.current = 0;
        return false;
      }
      polls.current += 1;
      return polls.current > MAX_POLLS ? false : POLL_INTERVAL_MS;
    },
  });
  const ingest = useMutation({
    mutationFn: () => ingestOpportunity(jdText, sourceUrl.trim() === "" ? null : sourceUrl.trim()),
    onSuccess: async () => {
      polls.current = 0;
      setJdText("");
      setSourceUrl("");
      await client.invalidateQueries({ queryKey: OPPORTUNITIES_KEY });
    },
  });

  function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    ingest.mutate();
  }

  const duplicateId =
    ingest.error instanceof ApiRequestError && ingest.error.code === "duplicate_jd"
      ? ingest.error.opportunityId
      : null;

  return (
    <section aria-labelledby="opportunities-title">
      <h1 id="opportunities-title">Opportunities</h1>
      <p>
        Paste a job description. Pasting is the only thing that starts a model call: it extracts the
        company, title and requirements once. Nothing is fetched from the web.
      </p>
      <form aria-label="Add job description" onSubmit={submit}>
        <p>
          <label>
            Job description
            <textarea
              value={jdText}
              rows={10}
              required
              onChange={(event) => {
                setJdText(event.target.value);
              }}
            />
          </label>
        </p>
        <p>
          <label>
            Source URL (optional, stored as text, never opened)
            <input
              value={sourceUrl}
              maxLength={2048}
              onChange={(event) => {
                setSourceUrl(event.target.value);
              }}
            />
          </label>
        </p>
        <button type="submit" disabled={ingest.isPending || jdText.trim() === ""}>
          Add and extract
        </button>
      </form>
      {ingest.isPending && <p role="status">Adding…</p>}
      {ingest.isSuccess && <p role="status">Added. Extraction is running.</p>}
      {ingest.isError && (
        <p role="alert">
          {ingestErrorMessage(ingest.error)}{" "}
          {duplicateId !== null && <Link to={`/opportunities/${duplicateId}`}>Open it</Link>}
        </p>
      )}

      {list.isPending && <p role="status">Loading…</p>}
      {list.isError && <p role="alert">Could not load opportunities.</p>}
      {list.isSuccess && list.data.length === 0 && <p>No opportunities yet.</p>}
      {list.isSuccess && list.data.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Company</th>
              <th>Title</th>
              <th>Status</th>
              <th>Priority</th>
              <th>Extraction</th>
            </tr>
          </thead>
          <tbody>
            {list.data.map((row) => (
              <tr key={row.id}>
                <td>{row.company?.name ?? "—"}</td>
                <td>
                  <Link to={`/opportunities/${row.id}`}>{row.title ?? "Untitled posting"}</Link>
                </td>
                <td>{row.status}</td>
                <td>{row.priority}</td>
                <td>{extractionMessage(row.extraction_status, row.extraction_error_code)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
