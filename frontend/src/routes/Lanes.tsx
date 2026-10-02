import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { SubmitEvent } from "react";

import {
  createLane,
  fetchLanes,
  fetchResumes,
  patchLane,
  setLaneArchived,
} from "../api/resumes";
import type { Lane, LaneCreate, Resume } from "../api/resumes";
import { laneErrorMessage } from "./resumeMessages";

interface LaneFormProps {
  initial: LaneCreate;
  submitLabel: string;
  pending: boolean;
  error: unknown;
  onSubmit: (lane: LaneCreate) => void;
  onCancel?: () => void;
}

function parseLabels(raw: string): string[] {
  return raw
    .split(",")
    .map((item) => item.trim())
    .filter((item) => item !== "");
}

function LaneForm({ initial, submitLabel, pending, error, onSubmit, onCancel }: LaneFormProps) {
  const [name, setName] = useState(initial.name);
  const [description, setDescription] = useState(initial.description);
  const [notes, setNotes] = useState(initial.emphasis_notes);
  const [labels, setLabels] = useState((initial.target_role_labels ?? []).join(", "));

  function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit({
      name,
      description,
      emphasis_notes: notes,
      target_role_labels: parseLabels(labels),
    });
  }

  return (
    <form onSubmit={submit}>
      <p>
        <label>
          Lane name
          <input
            value={name}
            maxLength={80}
            required
            onChange={(event) => {
              setName(event.target.value);
            }}
          />
        </label>
      </p>
      <p>
        <label>
          Description
          <textarea
            value={description}
            maxLength={1000}
            onChange={(event) => {
              setDescription(event.target.value);
            }}
          />
        </label>
      </p>
      <p>
        <label>
          Emphasis notes
          <textarea
            value={notes}
            maxLength={2000}
            onChange={(event) => {
              setNotes(event.target.value);
            }}
          />
        </label>
      </p>
      <p>
        <label>
          Target role labels (comma separated)
          <input
            value={labels}
            onChange={(event) => {
              setLabels(event.target.value);
            }}
          />
        </label>
      </p>
      <button type="submit" disabled={pending || name.trim() === ""}>
        {submitLabel}
      </button>{" "}
      {onCancel && (
        <button type="button" onClick={onCancel}>
          Cancel
        </button>
      )}
      {error !== null && error !== undefined && <p role="alert">{laneErrorMessage(error)}</p>}
    </form>
  );
}

interface LaneItemProps {
  lane: Lane;
  resumes: Resume[];
}

function LaneItem({ lane, resumes }: LaneItemProps) {
  const client = useQueryClient();
  const [editing, setEditing] = useState(false);
  const refresh = () => client.invalidateQueries({ queryKey: ["lanes"] });
  const save = useMutation({
    mutationFn: (value: LaneCreate) => patchLane(lane.id, value),
    onSuccess: async () => {
      setEditing(false);
      await refresh();
    },
  });
  const setDefault = useMutation({
    mutationFn: (resumeId: string | null) => patchLane(lane.id, { default_resume_id: resumeId }),
    onSuccess: refresh,
  });
  const archive = useMutation({
    mutationFn: (archived: boolean) => setLaneArchived(lane.id, archived),
    onSuccess: refresh,
  });
  const members = resumes.filter(
    (resume) => resume.lane_id === lane.id && resume.status === "active",
  );
  const archived = lane.status === "archived";

  return (
    <li>
      <h3>
        {lane.name}
        {archived && " (archived)"}
      </h3>
      {editing ? (
        <LaneForm
          initial={{
            name: lane.name,
            description: lane.description,
            emphasis_notes: lane.emphasis_notes,
            target_role_labels: lane.target_role_labels,
          }}
          submitLabel="Save lane"
          pending={save.isPending}
          error={save.error}
          onSubmit={(value) => {
            save.mutate(value);
          }}
          onCancel={() => {
            setEditing(false);
          }}
        />
      ) : (
        <>
          {lane.description !== "" && <p>{lane.description}</p>}
          {lane.emphasis_notes !== "" && <p>Emphasis: {lane.emphasis_notes}</p>}
          {lane.target_role_labels.length > 0 && <p>Roles: {lane.target_role_labels.join(", ")}</p>}
        </>
      )}
      <label>
        Default resume for {lane.name}
        <select
          value={lane.default_resume_id ?? ""}
          onChange={(event) => {
            setDefault.mutate(event.target.value === "" ? null : event.target.value);
          }}
        >
          <option value="">No default</option>
          {members.map((resume) => (
            <option key={resume.id} value={resume.id}>
              {resume.label}
            </option>
          ))}
        </select>
      </label>{" "}
      {!editing && (
        <button
          type="button"
          onClick={() => {
            setEditing(true);
          }}
        >
          Edit lane
        </button>
      )}{" "}
      <button
        type="button"
        disabled={archive.isPending}
        onClick={() => {
          archive.mutate(!archived);
        }}
      >
        {archived ? "Unarchive lane" : "Archive lane"}
      </button>
      {setDefault.isError && <p role="alert">{laneErrorMessage(setDefault.error)}</p>}
      {archive.isError && <p role="alert">{laneErrorMessage(archive.error)}</p>}
    </li>
  );
}

export function Lanes() {
  const client = useQueryClient();
  const lanes = useQuery({ queryKey: ["lanes"], queryFn: ({ signal }) => fetchLanes(signal) });
  const resumes = useQuery({
    queryKey: ["resumes"],
    queryFn: ({ signal }) => fetchResumes(signal),
  });
  const [formKey, setFormKey] = useState(0);
  const create = useMutation({
    mutationFn: createLane,
    onSuccess: async () => {
      setFormKey((value) => value + 1);
      await client.invalidateQueries({ queryKey: ["lanes"] });
    },
  });

  return (
    <section aria-labelledby="lanes-title">
      <h1 id="lanes-title">Lanes</h1>
      <p>A lane is a truthful way to present your background for one kind of role.</p>

      <h2>New lane</h2>
      <LaneForm
        key={formKey}
        initial={{ name: "", description: "", emphasis_notes: "", target_role_labels: [] }}
        submitLabel="Create lane"
        pending={create.isPending}
        error={create.error}
        onSubmit={(value) => {
          create.mutate(value);
        }}
      />

      <h2>Your lanes</h2>
      {lanes.isPending && <p role="status">Loading lanes…</p>}
      {lanes.isError && <p role="alert">Could not load lanes.</p>}
      {lanes.isSuccess && lanes.data.length === 0 && <p>No lanes yet.</p>}
      {lanes.isSuccess && lanes.data.length > 0 && (
        <ul>
          {lanes.data.map((lane) => (
            <LaneItem key={lane.id} lane={lane} resumes={resumes.data ?? []} />
          ))}
        </ul>
      )}
    </section>
  );
}
