import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { SubmitEvent } from "react";

import {
  APPLICATIONS_KEY,
  applicationsForOpportunityKey,
  fetchApplications,
  fetchTimeline,
  recordApplicationEvent,
  reopenApplication,
  timelineKey,
  voidApplicationEvent,
} from "../api/applications";
import type { Application, ApplicationChannel, TimelineEntry } from "../api/applications";
import {
  OPPORTUNITIES_KEY,
  applyToOpportunity,
  decideOpportunity,
  opportunityKey,
} from "../api/opportunities";
import type { OpportunityDetail as Detail } from "../api/opportunities";
import { fetchLanes, fetchResumes } from "../api/resumes";
import { commandErrorMessage, humanize, needsRefresh } from "./opportunityMessages";
import { appliedAtFor, nowLocalInput, todayLocal } from "./workflowDates";

const CHANNELS: ApplicationChannel[] = [
  "company_site",
  "job_board",
  "referral",
  "recruiter",
  "email",
  "other",
];

function orNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

function useRefreshWorkflow(opportunityId: string) {
  const client = useQueryClient();
  return async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: opportunityKey(opportunityId) }),
      client.invalidateQueries({ queryKey: OPPORTUNITIES_KEY }),
      client.invalidateQueries({ queryKey: APPLICATIONS_KEY }),
      client.invalidateQueries({ queryKey: timelineKey(opportunityId) }),
    ]);
  };
}

interface FailureProps {
  error: unknown;
  onRefresh: () => void;
}

function Failure({ error, onRefresh }: FailureProps) {
  return (
    <p role="alert">
      {commandErrorMessage(error)}{" "}
      {needsRefresh(error) && (
        <button type="button" onClick={onRefresh}>
          Refresh
        </button>
      )}
    </p>
  );
}

interface ReasonPromptProps {
  label: string;
  confirmLabel: string;
  pending: boolean;
  maxLength: number;
  onConfirm: (reason: string | null) => void;
  onCancel: () => void;
}

function ReasonPrompt({
  label,
  confirmLabel,
  pending,
  maxLength,
  onConfirm,
  onCancel,
}: ReasonPromptProps) {
  const [reason, setReason] = useState("");
  return (
    <form
      aria-label={confirmLabel}
      onSubmit={(event: SubmitEvent<HTMLFormElement>) => {
        event.preventDefault();
        onConfirm(orNull(reason));
      }}
    >
      <label>
        {label}
        <textarea
          rows={2}
          maxLength={maxLength}
          value={reason}
          onChange={(event) => {
            setReason(event.target.value);
          }}
        />
      </label>{" "}
      <button type="submit" disabled={pending}>
        {confirmLabel}
      </button>{" "}
      <button type="button" onClick={onCancel}>
        Cancel
      </button>
    </form>
  );
}

interface ApplyFormProps {
  detail: Detail;
  onCancel: () => void;
  onApplied: () => void;
}

function ApplyForm({ detail, onCancel, onApplied }: ApplyFormProps) {
  const client = useQueryClient();
  const refresh = useRefreshWorkflow(detail.id);
  const resumes = useQuery({
    queryKey: ["resumes"],
    queryFn: ({ signal }) => fetchResumes(signal),
  });
  const lanes = useQuery({
    queryKey: ["lanes"],
    queryFn: ({ signal }) => fetchLanes(signal),
  });
  const [resumeId, setResumeId] = useState("");
  const [laneId, setLaneId] = useState("");
  const [channel, setChannel] = useState<ApplicationChannel>("other");
  const [day, setDay] = useState(todayLocal());
  const apply = useMutation({
    mutationFn: () =>
      applyToOpportunity(detail, {
        resume_id: resumeId === "" ? null : resumeId,
        lane_id: laneId === "" ? null : laneId,
        channel,
        applied_at: appliedAtFor(day),
      }),
    onSuccess: async (result) => {
      client.setQueryData(opportunityKey(detail.id), result.opportunity);
      await refresh();
      onApplied();
    },
  });

  return (
    <form
      aria-label="Apply"
      onSubmit={(event: SubmitEvent<HTMLFormElement>) => {
        event.preventDefault();
        apply.mutate();
      }}
    >
      <p>Applying records that you applied. Nothing is sent anywhere.</p>
      <p>
        <label>
          Resume
          <select
            value={resumeId}
            onChange={(event) => {
              setResumeId(event.target.value);
            }}
          >
            <option value="">None</option>
            {(resumes.data ?? [])
              .filter((row) => row.status === "active")
              .map((row) => (
                <option key={row.id} value={row.id}>
                  {row.label}
                </option>
              ))}
          </select>
        </label>
      </p>
      <p>
        <label>
          Lane
          <select
            value={laneId}
            onChange={(event) => {
              setLaneId(event.target.value);
            }}
          >
            <option value="">None</option>
            {(lanes.data ?? [])
              .filter((row) => row.status === "active")
              .map((row) => (
                <option key={row.id} value={row.id}>
                  {row.name}
                </option>
              ))}
          </select>
        </label>
      </p>
      <p>
        <label>
          Channel
          <select
            value={channel}
            onChange={(event) => {
              setChannel(event.target.value as ApplicationChannel);
            }}
          >
            {CHANNELS.map((value) => (
              <option key={value} value={value}>
                {humanize(value)}
              </option>
            ))}
          </select>
        </label>
      </p>
      <p>
        <label>
          Applied date
          <input
            type="date"
            required
            value={day}
            max={todayLocal()}
            onChange={(event) => {
              setDay(event.target.value);
            }}
          />
        </label>
      </p>
      <button type="submit" disabled={apply.isPending || day === ""}>
        Confirm apply
      </button>{" "}
      <button type="button" onClick={onCancel}>
        Cancel
      </button>
      {apply.isError && (
        <Failure
          error={apply.error}
          onRefresh={() => {
            void refresh();
          }}
        />
      )}
    </form>
  );
}

type Prompt = "skip" | "close" | "apply" | null;

export function DecisionPanel({ detail }: { detail: Detail }) {
  const client = useQueryClient();
  const refresh = useRefreshWorkflow(detail.id);
  const [prompt, setPrompt] = useState<Prompt>(null);
  const decide = useMutation({
    mutationFn: ({
      action,
      reason,
    }: {
      action: "save" | "skip" | "close";
      reason: string | null;
    }) => decideOpportunity(detail, action, reason),
    onSuccess: async (next) => {
      setPrompt(null);
      client.setQueryData(opportunityKey(detail.id), next);
      await refresh();
    },
  });
  const allowed = new Set<string>(detail.allowed_actions);

  return (
    <section aria-labelledby="decision-title">
      <h2 id="decision-title">Decision</h2>
      {detail.allowed_actions.length === 0 ? (
        <p>You applied to this posting. Progress is tracked on the application below.</p>
      ) : (
        <p>
          {allowed.has("save") && (
            <button
              type="button"
              disabled={decide.isPending}
              onClick={() => {
                setPrompt(null);
                decide.mutate({ action: "save", reason: null });
              }}
            >
              Save
            </button>
          )}{" "}
          {allowed.has("skip") && (
            <button
              type="button"
              onClick={() => {
                setPrompt("skip");
              }}
            >
              Skip
            </button>
          )}{" "}
          {allowed.has("apply") && (
            <button
              type="button"
              onClick={() => {
                setPrompt("apply");
              }}
            >
              Apply
            </button>
          )}{" "}
          {allowed.has("close") && (
            <button
              type="button"
              onClick={() => {
                setPrompt("close");
              }}
            >
              Close
            </button>
          )}
        </p>
      )}
      {(prompt === "skip" || prompt === "close") && (
        <ReasonPrompt
          label="Reason (optional)"
          confirmLabel={prompt === "skip" ? "Confirm skip" : "Confirm close"}
          pending={decide.isPending}
          maxLength={500}
          onConfirm={(reason) => {
            decide.mutate({ action: prompt, reason });
          }}
          onCancel={() => {
            setPrompt(null);
          }}
        />
      )}
      {prompt === "apply" && (
        <ApplyForm
          detail={detail}
          onCancel={() => {
            setPrompt(null);
          }}
          onApplied={() => {
            setPrompt(null);
          }}
        />
      )}
      {decide.isError && (
        <Failure
          error={decide.error}
          onRefresh={() => {
            decide.reset();
            void refresh();
          }}
        />
      )}
    </section>
  );
}

interface RecordFormProps {
  application: Application;
  onRecorded: (next: Application) => void;
  onFailure: () => void;
}

function RecordForm({ application, onRecorded, onFailure }: RecordFormProps) {
  const [eventType, setEventType] = useState(application.recordable_event_types[0] ?? "");
  const [when, setWhen] = useState(nowLocalInput());
  const [note, setNote] = useState("");
  const record = useMutation({
    mutationFn: () =>
      recordApplicationEvent(application, {
        event_type: eventType,
        occurred_at: new Date(when).toISOString(),
        note: orNull(note),
      }),
    onSuccess: (next) => {
      setNote("");
      setWhen(nowLocalInput());
      onRecorded(next);
    },
    onError: onFailure,
  });

  return (
    <form
      aria-label="Record event"
      onSubmit={(event: SubmitEvent<HTMLFormElement>) => {
        event.preventDefault();
        record.mutate();
      }}
    >
      <p>
        <label>
          Event type
          <select
            value={eventType}
            onChange={(event) => {
              setEventType(event.target.value);
            }}
          >
            {application.recordable_event_types.map((value) => (
              <option key={value} value={value}>
                {humanize(value)}
              </option>
            ))}
          </select>
        </label>
      </p>
      <p>
        <label>
          When it happened
          <input
            type="datetime-local"
            required
            value={when}
            onChange={(event) => {
              setWhen(event.target.value);
            }}
          />
        </label>
      </p>
      <p>
        <label>
          Note (optional)
          <textarea
            rows={2}
            maxLength={1000}
            value={note}
            onChange={(event) => {
              setNote(event.target.value);
            }}
          />
        </label>
      </p>
      <button type="submit" disabled={record.isPending || when === "" || eventType === ""}>
        Record event
      </button>
      {record.isError && (
        <Failure
          error={record.error}
          onRefresh={() => {
            record.reset();
            onFailure();
          }}
        />
      )}
    </form>
  );
}

interface ApplicationPanelProps {
  application: Application;
  onRefresh: () => Promise<void>;
}

function ApplicationPanel({ application, onRefresh }: ApplicationPanelProps) {
  const client = useQueryClient();
  const store = async (next: Application) => {
    client.setQueryData(applicationsForOpportunityKey(application.opportunity_id), [next]);
    await onRefresh();
  };
  const reopen = useMutation({
    mutationFn: () => reopenApplication(application),
    onSuccess: store,
  });

  return (
    <section aria-labelledby="application-title">
      <h2 id="application-title">Application</h2>
      <p>
        Stage: <strong>{humanize(application.stage)}</strong>
        {application.is_terminal && " (closed)"} · Applied{" "}
        {new Date(application.applied_at).toLocaleDateString()} via {humanize(application.channel)}
      </p>
      {application.is_terminal && (
        <p>
          <button
            type="button"
            disabled={reopen.isPending}
            onClick={() => {
              reopen.mutate();
            }}
          >
            Reopen
          </button>
        </p>
      )}
      {reopen.isError && (
        <Failure
          error={reopen.error}
          onRefresh={() => {
            reopen.reset();
            void onRefresh();
          }}
        />
      )}
      <RecordForm
        key={`${application.id}:${String(application.state_version)}`}
        application={application}
        onRecorded={(next) => {
          void store(next);
        }}
        onFailure={() => {
          void onRefresh();
        }}
      />
    </section>
  );
}

interface TimelineRowProps {
  entry: TimelineEntry;
  application: Application | undefined;
  onChanged: (next: Application) => void;
  onRefresh: () => void;
}

function TimelineRow({ entry, application, onChanged, onRefresh }: TimelineRowProps) {
  const [confirming, setConfirming] = useState(false);
  const voidEntry = useMutation({
    mutationFn: (reason: string | null) => {
      if (application === undefined) {
        throw new Error("no application");
      }
      return voidApplicationEvent(application, entry.id, reason);
    },
    onSuccess: (next) => {
      setConfirming(false);
      onChanged(next);
    },
  });

  return (
    <li>
      <time dateTime={entry.occurred_at}>{new Date(entry.occurred_at).toLocaleString()}</time>{" "}
      <span style={entry.voided ? { textDecoration: "line-through" } : undefined}>
        {humanize(entry.event_type)}
      </span>
      {entry.voided && <span> (voided)</span>} <span>by {entry.actor}</span>
      {entry.note !== null && <p>{entry.note}</p>}
      {entry.voidable && application !== undefined && !confirming && (
        <button
          type="button"
          onClick={() => {
            setConfirming(true);
          }}
        >
          Void
        </button>
      )}
      {confirming && (
        <ReasonPrompt
          label="Reason for voiding (optional)"
          confirmLabel="Confirm void"
          pending={voidEntry.isPending}
          maxLength={500}
          onConfirm={(reason) => {
            voidEntry.mutate(reason);
          }}
          onCancel={() => {
            setConfirming(false);
          }}
        />
      )}
      {voidEntry.isError && <Failure error={voidEntry.error} onRefresh={onRefresh} />}
    </li>
  );
}

export function ApplicationSection({ opportunityId }: { opportunityId: string }) {
  const client = useQueryClient();
  const refresh = useRefreshWorkflow(opportunityId);
  const applications = useQuery({
    queryKey: applicationsForOpportunityKey(opportunityId),
    queryFn: ({ signal }) => fetchApplications(opportunityId, signal),
  });
  const timeline = useQuery({
    queryKey: timelineKey(opportunityId),
    queryFn: ({ signal }) => fetchTimeline(opportunityId, signal),
  });
  const application = applications.data?.[0];
  const changed = async (next: Application) => {
    client.setQueryData(applicationsForOpportunityKey(opportunityId), [next]);
    await refresh();
  };

  return (
    <>
      {application !== undefined && (
        <ApplicationPanel application={application} onRefresh={refresh} />
      )}
      <section aria-labelledby="timeline-title">
        <h2 id="timeline-title">Timeline</h2>
        {timeline.isPending && <p role="status">Loading…</p>}
        {timeline.isError && <p role="alert">Could not load the timeline.</p>}
        {timeline.isSuccess && (
          <ol>
            {timeline.data.map((entry) => (
              <TimelineRow
                key={entry.id}
                entry={entry}
                application={applications.data?.find((row) => row.id === entry.aggregate_id)}
                onChanged={(next) => {
                  void changed(next);
                }}
                onRefresh={() => {
                  void refresh();
                }}
              />
            ))}
          </ol>
        )}
      </section>
    </>
  );
}
