import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { SubmitEvent } from "react";

import { fetchApplications } from "../api/applications";
import type { Application } from "../api/applications";
import { CONTACTS_KEY, createInteraction, fetchContacts } from "../api/contacts";
import type { InteractionChannel, InteractionDirection } from "../api/contacts";
import {
  humanizeWord,
  relationshipErrorMessage,
  relationshipNeedsRefresh,
} from "./relationshipMessages";
import { nowLocalInput } from "./workflowDates";

const CHANNELS: InteractionChannel[] = ["email", "linkedin", "phone", "in_person", "other"];
const DIRECTIONS: InteractionDirection[] = ["outbound", "inbound"];
const EVENT_TYPES = [
  "OUTREACH_SENT",
  "FOLLOWUP_SENT",
  "RECRUITER_CONTACTED",
  "CONTACT_REPLIED",
  "CONNECTION_REQUEST_SENT",
  "CONNECTION_ACCEPTED",
] as const;

interface InteractionFormProps {
  contactId?: string;
  opportunityId?: string;
  onRecorded?: () => void;
}

export function InteractionForm({ contactId, opportunityId, onRecorded }: InteractionFormProps) {
  const client = useQueryClient();
  const contacts = useQuery({
    queryKey: [...CONTACTS_KEY, "list", ""],
    queryFn: ({ signal }) => fetchContacts({}, signal),
    enabled: contactId === undefined,
  });
  const applications = useQuery({
    queryKey: ["applications", "opportunity", opportunityId ?? "none"],
    queryFn: ({ signal }) => fetchApplications(opportunityId, signal),
    enabled: opportunityId !== undefined,
  });
  const application: Application | undefined = applications.data?.[0];
  const [chosenContact, setChosenContact] = useState("");
  const [channel, setChannel] = useState<InteractionChannel>("email");
  const [direction, setDirection] = useState<InteractionDirection>("outbound");
  const [occurredAt, setOccurredAt] = useState(nowLocalInput());
  const [summary, setSummary] = useState("");
  const [eventType, setEventType] = useState("");
  const record = useMutation({
    mutationFn: () => {
      const target = contactId ?? chosenContact;
      const withEvent = eventType !== "" && application !== undefined;
      return createInteraction({
        contact_id: target,
        channel,
        direction,
        occurred_at: new Date(occurredAt).toISOString(),
        summary: summary.trim() === "" ? null : summary.trim(),
        ...(opportunityId === undefined ? {} : { opportunity_id: opportunityId }),
        ...(withEvent
          ? {
              application_id: application.id,
              application_event_type: eventType as (typeof EVENT_TYPES)[number],
              expected_application_state_version: application.state_version,
            }
          : {}),
      });
    },
    onSuccess: async () => {
      setSummary("");
      await client.invalidateQueries();
      onRecorded?.();
    },
  });
  const target = contactId ?? chosenContact;

  return (
    <form
      aria-label="Record interaction"
      onSubmit={(event: SubmitEvent<HTMLFormElement>) => {
        event.preventDefault();
        record.mutate();
      }}
    >
      <h2>Record an interaction</h2>
      {contactId === undefined && (
        <p>
          <label>
            Contact
            <select
              value={chosenContact}
              onChange={(event) => {
                setChosenContact(event.target.value);
              }}
            >
              <option value="">Choose a contact</option>
              {contacts.data?.map((contact) => (
                <option key={contact.id} value={contact.id}>
                  {contact.full_name}
                </option>
              ))}
            </select>
          </label>
        </p>
      )}
      <p>
        <label>
          Channel
          <select
            value={channel}
            onChange={(event) => {
              setChannel(event.target.value as InteractionChannel);
            }}
          >
            {CHANNELS.map((value) => (
              <option key={value} value={value}>
                {humanizeWord(value)}
              </option>
            ))}
          </select>
        </label>{" "}
        <label>
          Direction
          <select
            value={direction}
            onChange={(event) => {
              setDirection(event.target.value as InteractionDirection);
            }}
          >
            {DIRECTIONS.map((value) => (
              <option key={value} value={value}>
                {humanizeWord(value)}
              </option>
            ))}
          </select>
        </label>
      </p>
      <p>
        <label>
          When
          <input
            type="datetime-local"
            value={occurredAt}
            onChange={(event) => {
              setOccurredAt(event.target.value);
            }}
          />
        </label>
      </p>
      <p>
        <label>
          Summary
          <textarea
            rows={3}
            maxLength={2000}
            value={summary}
            onChange={(event) => {
              setSummary(event.target.value);
            }}
          />
        </label>
      </p>
      {application !== undefined && (
        <p>
          <label>
            Also record on the application
            <select
              value={eventType}
              onChange={(event) => {
                setEventType(event.target.value);
              }}
            >
              <option value="">Do not record an event</option>
              {EVENT_TYPES.map((value) => (
                <option key={value} value={value}>
                  {humanizeWord(value)}
                </option>
              ))}
            </select>
          </label>
        </p>
      )}
      <button type="submit" disabled={record.isPending || target === ""}>
        Record interaction
      </button>
      {record.isSuccess && <p role="status">Interaction recorded.</p>}
      {record.isError && (
        <p role="alert">
          {relationshipErrorMessage(record.error)}{" "}
          {relationshipNeedsRefresh(record.error) && (
            <button
              type="button"
              onClick={() => {
                void client.invalidateQueries();
              }}
            >
              Refresh
            </button>
          )}
        </p>
      )}
    </form>
  );
}
