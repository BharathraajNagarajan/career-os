import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { APPLICATIONS_KEY, fetchApplications } from "../api/applications";
import { humanize } from "./opportunityMessages";

export function Applications() {
  const list = useQuery({
    queryKey: APPLICATIONS_KEY,
    queryFn: ({ signal }) => fetchApplications(undefined, signal),
  });

  return (
    <section aria-labelledby="applications-title">
      <h1 id="applications-title">Applications</h1>
      <p>
        Applications are created by applying on an opportunity. Open one to record what happened.
      </p>
      {list.isPending && <p role="status">Loading…</p>}
      {list.isError && <p role="alert">Could not load applications.</p>}
      {list.isSuccess && list.data.length === 0 && <p>No applications yet.</p>}
      {list.isSuccess && list.data.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Company</th>
              <th>Title</th>
              <th>Stage</th>
              <th>Applied</th>
            </tr>
          </thead>
          <tbody>
            {list.data.map((row) => (
              <tr key={row.id}>
                <td>{row.company_name ?? "—"}</td>
                <td>
                  <Link to={`/opportunities/${row.opportunity_id}`}>
                    {row.opportunity_title ?? "Untitled posting"}
                  </Link>
                </td>
                <td>
                  {humanize(row.stage)}
                  {row.is_terminal && " (closed)"}
                </td>
                <td>{new Date(row.applied_at).toLocaleDateString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
