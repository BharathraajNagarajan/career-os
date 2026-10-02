import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  DELETE_CONFIRMATION,
  fetchSessions,
  requestAccountDeletion,
  revokeSession,
  signOut,
} from "../api/auth";
import { SIGN_IN_PATH } from "../api/client";

export function Settings() {
  const client = useQueryClient();
  const navigate = useNavigate();
  const [confirmation, setConfirmation] = useState("");
  const sessions = useQuery({
    queryKey: ["sessions"],
    queryFn: ({ signal }) => fetchSessions(signal),
  });

  const revoke = useMutation({
    mutationFn: revokeSession,
    onSuccess: () => client.invalidateQueries({ queryKey: ["sessions"] }),
  });
  const leave = useMutation({
    mutationFn: signOut,
    onSuccess: async () => {
      client.clear();
      await navigate(SIGN_IN_PATH);
    },
  });
  const deleteAccount = useMutation({
    mutationFn: requestAccountDeletion,
    onSuccess: async () => {
      client.clear();
      await navigate(`${SIGN_IN_PATH}?notice=account_deletion_requested`);
    },
  });

  return (
    <section aria-labelledby="settings-title">
      <h1 id="settings-title">Settings</h1>

      <h2>Sessions</h2>
      {sessions.isPending && <p role="status">Loading sessions…</p>}
      {sessions.isError && <p role="alert">Could not load sessions.</p>}
      {sessions.isSuccess && (
        <ul>
          {sessions.data.map((row) => (
            <li key={row.id}>
              Signed in {new Date(row.created_at).toLocaleString()}, last active{" "}
              {new Date(row.last_seen_at).toLocaleString()}
              {row.current && " (this session)"}{" "}
              {row.current ? (
                <button type="button" onClick={() => { leave.mutate(); }}>
                  Sign out
                </button>
              ) : (
                <button type="button" onClick={() => { revoke.mutate(row.id); }}>
                  Sign out this session
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      <h2>Delete account</h2>
      <p>
        This permanently removes your account and all of its data. Type {DELETE_CONFIRMATION} to
        confirm.
      </p>
      <label>
        Confirmation
        <input
          value={confirmation}
          onChange={(event) => { setConfirmation(event.target.value); }}
          autoComplete="off"
        />
      </label>{" "}
      <button
        type="button"
        disabled={confirmation !== DELETE_CONFIRMATION || deleteAccount.isPending}
        onClick={() => { deleteAccount.mutate(); }}
      >
        Delete account
      </button>
      {deleteAccount.isError && <p role="alert">Could not request deletion. Try again.</p>}
    </section>
  );
}
