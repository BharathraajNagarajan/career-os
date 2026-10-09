import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { SubmitEvent } from "react";

import { ACTIONS_KEY, actionsKey, createAction, fetchActions, finishAction, snoozeAction } from "../api/actions";
import type {
  RecruitingAction,
  RecruitingActionKind,
  RecruitingActionStatus,
} from "../api/actions";
import {
  humanizeWord,
  relationshipErrorMessage,
  relationshipNeedsRefresh,
} from "./relationshipMessages";
import { nowLocalInput } from "./workflowDates";

type Filter = "open" | "snoozed" | "done";

const FILTERS: Record<Filter, RecruitingActionStatus[]> = {
  open: ["open"],
  snoozed: ["snoozed"],
  done: ["done", "dismissed", "superseded"],
};

const CREATABLE_KINDS: RecruitingActionKind[] = [
  "follow_up",
  "reply",
  "complete_assessment",
  "attend_interview",
  "schedule_interview",
  "custom",
];
const NEEDS_DUE: RecruitingActionKind[] = ["attend_interview", "complete_assessment"];

function ActionRow({ action }: { action: RecruitingAction }) {
  const client = useQueryClient();
  const [until, setUntil] = useState("");
  const [snoozing, setSnoozing] = useState(false);
  const refresh = () => client.invalidateQueries({ queryKey: ACTIONS_KEY });
  const snooze = useMutation({
    mutationFn: () => snoozeAction(action, new Date(until).toISOString()),
    onSuccess: () => {
      setSnoozing(false);
      return refresh();
    },
  });
  const finish = useMutation({
    mutationFn: (command: "complete" | "dismiss") => finishAction(action, command),
    onSuccess: refresh,
  });
  const failure = snooze.error ?? finish.error;

  return (
    <li>
      <strong>{action.title}</strong> ({humanizeWord(action.kind)}
      {action.sequence_no > 1 && <>, #{action.sequence_no}</>}) – {action.status}
      {action.due_at !== null && <> – due {new Date(action.due_at).toLocaleString()}</>}
      {action.snoozed_until !== null && (
        <> – snoozed until {new Date(action.snoozed_until).toLocaleString()}</>
      )}{" "}
      {action.allowed_actions.includes("snooze") && !snoozing && (
        <button
          type="button"
          onClick={() => {
            setSnoozing(true);
          }}
        >
          Snooze
        </button>
      )}{" "}
      {action.allowed_actions.includes("complete") && (
        <button
          type="button"
          disabled={finish.isPending}
          onClick={() => {
            finish.mutate("complete");
          }}
        >
          Complete
        </button>
      )}{" "}
      {action.allowed_actions.includes("dismiss") && (
        <button
          type="button"
          disabled={finish.isPending}
          onClick={() => {
            finish.mutate("dismiss");
          }}
        >
          Dismiss
        </button>
      )}
      {snoozing && (
        <form
          aria-label={`Snooze ${action.title}`}
          onSubmit={(event: SubmitEvent<HTMLFormElement>) => {
            event.preventDefault();
            snooze.mutate();
          }}
        >
          <label>
            Snooze until
            <input
              type="datetime-local"
              value={until}
              onChange={(event) => {
                setUntil(event.target.value);
              }}
            />
          </label>{" "}
          <button type="submit" disabled={snooze.isPending || until === ""}>
            Confirm snooze
          </button>{" "}
          <button
            type="button"
            onClick={() => {
              setSnoozing(false);
            }}
          >
            Cancel
          </button>
        </form>
      )}
      {failure !== null && (
        <p role="alert">
          {relationshipErrorMessage(failure)}{" "}
          {relationshipNeedsRefresh(failure) && (
            <button
              type="button"
              onClick={() => {
                void refresh();
              }}
            >
              Refresh
            </button>
          )}
        </p>
      )}
    </li>
  );
}

function CreateActionForm() {
  const client = useQueryClient();
  const [kind, setKind] = useState<RecruitingActionKind>("follow_up");
  const [title, setTitle] = useState("");
  const [dueAt, setDueAt] = useState(nowLocalInput());
  const create = useMutation({
    mutationFn: () =>
      createAction({
        kind,
        title: title.trim(),
        due_at: dueAt === "" ? null : new Date(dueAt).toISOString(),
      }),
    onSuccess: async () => {
      setTitle("");
      await client.invalidateQueries({ queryKey: ACTIONS_KEY });
    },
  });
  const dueMissing = NEEDS_DUE.includes(kind) && dueAt === "";

  return (
    <form
      aria-label="Add action"
      onSubmit={(event: SubmitEvent<HTMLFormElement>) => {
        event.preventDefault();
        create.mutate();
      }}
    >
      <h2>Add an action</h2>
      <p>
        <label>
          Kind
          <select
            value={kind}
            onChange={(event) => {
              setKind(event.target.value as RecruitingActionKind);
            }}
          >
            {CREATABLE_KINDS.map((value) => (
              <option key={value} value={value}>
                {humanizeWord(value)}
              </option>
            ))}
          </select>
        </label>{" "}
        <label>
          Title
          <input
            value={title}
            maxLength={200}
            onChange={(event) => {
              setTitle(event.target.value);
            }}
          />
        </label>{" "}
        <label>
          Due or scheduled for
          <input
            type="datetime-local"
            value={dueAt}
            onChange={(event) => {
              setDueAt(event.target.value);
            }}
          />
        </label>
      </p>
      <button type="submit" disabled={create.isPending || title.trim() === "" || dueMissing}>
        Add action
      </button>
      {create.isSuccess && <p role="status">Action added.</p>}
      {create.isError && <p role="alert">{relationshipErrorMessage(create.error)}</p>}
    </form>
  );
}

export function Actions() {
  const [filter, setFilter] = useState<Filter>("open");
  const actions = useQuery({
    queryKey: actionsKey(filter),
    queryFn: ({ signal }) => fetchActions({ statuses: FILTERS[filter] }, signal),
  });

  return (
    <section aria-labelledby="actions-title">
      <h1 id="actions-title">Actions</h1>
      <p role="group" aria-label="Filter actions">
        {(Object.keys(FILTERS) as Filter[]).map((value) => (
          <button
            key={value}
            type="button"
            aria-pressed={filter === value}
            onClick={() => {
              setFilter(value);
            }}
          >
            {humanizeWord(value)}
          </button>
        ))}
      </p>
      {actions.isPending && <p role="status">Loading…</p>}
      {actions.isError && <p role="alert">Could not load actions.</p>}
      {actions.isSuccess && actions.data.length === 0 && <p>Nothing here.</p>}
      {actions.isSuccess && actions.data.length > 0 && (
        <ul>
          {actions.data.map((action) => (
            <ActionRow key={`${action.id}:${String(action.state_version)}`} action={action} />
          ))}
        </ul>
      )}
      <CreateActionForm />
    </section>
  );
}
