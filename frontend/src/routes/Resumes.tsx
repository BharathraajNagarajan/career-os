import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import type { SubmitEvent } from "react";

import {
  assignResumeLane,
  fetchLanes,
  fetchResumes,
  renameResume,
  resumeFileUrl,
  setResumeArchived,
  uploadResume,
} from "../api/resumes";
import type { Lane, Resume } from "../api/resumes";
import { extractionMessage, uploadErrorMessage } from "./resumeMessages";

export const POLL_INTERVAL_MS = 2000;
export const MAX_POLLS = 60;

interface ResumeItemProps {
  resume: Resume;
  lanes: Lane[];
}

function ResumeItem({ resume, lanes }: ResumeItemProps) {
  const client = useQueryClient();
  const [renaming, setRenaming] = useState(false);
  const [label, setLabel] = useState(resume.label);
  const refresh = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: ["resumes"] }),
      client.invalidateQueries({ queryKey: ["lanes"] }),
    ]);
  };
  const rename = useMutation({
    mutationFn: (value: string) => renameResume(resume.id, value),
    onSuccess: async () => {
      setRenaming(false);
      await refresh();
    },
  });
  const assign = useMutation({
    mutationFn: (laneId: string | null) => assignResumeLane(resume.id, laneId),
    onSuccess: refresh,
  });
  const archive = useMutation({
    mutationFn: (archived: boolean) => setResumeArchived(resume.id, archived),
    onSuccess: refresh,
  });
  const selectableLanes = lanes.filter(
    (lane) => lane.status === "active" || lane.id === resume.lane_id,
  );

  return (
    <li>
      {renaming ? (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            rename.mutate(label);
          }}
        >
          <label>
            Label
            <input
              value={label}
              maxLength={120}
              onChange={(event) => {
                setLabel(event.target.value);
              }}
            />
          </label>{" "}
          <button type="submit" disabled={label.trim() === "" || rename.isPending}>
            Save label
          </button>{" "}
          <button
            type="button"
            onClick={() => {
              setRenaming(false);
              setLabel(resume.label);
            }}
          >
            Cancel
          </button>
        </form>
      ) : (
        <strong>{resume.label}</strong>
      )}{" "}
      <span>({resume.original_filename})</span>
      {resume.archived && <span> Archived.</span>}
      <p>{extractionMessage(resume.extraction_status, resume.extraction_error_code)}</p>
      <label>
        Lane for {resume.label}
        <select
          value={resume.lane_id ?? ""}
          onChange={(event) => {
            assign.mutate(event.target.value === "" ? null : event.target.value);
          }}
        >
          <option value="">No lane</option>
          {selectableLanes.map((lane) => (
            <option key={lane.id} value={lane.id}>
              {lane.name}
              {lane.status === "archived" ? " (archived)" : ""}
            </option>
          ))}
        </select>
      </label>{" "}
      {!renaming && (
        <button
          type="button"
          onClick={() => {
            setRenaming(true);
          }}
        >
          Rename
        </button>
      )}{" "}
      <button
        type="button"
        disabled={archive.isPending}
        onClick={() => {
          archive.mutate(!resume.archived);
        }}
      >
        {resume.archived ? "Unarchive" : "Archive"}
      </button>{" "}
      <a href={resumeFileUrl(resume.id)}>Download</a>
      {(rename.isError || assign.isError || archive.isError) && (
        <p role="alert">Could not save that change. Try again.</p>
      )}
    </li>
  );
}

export function Resumes() {
  const client = useQueryClient();
  const polls = useRef(0);
  const fileInput = useRef<HTMLInputElement>(null);
  const resumes = useQuery({
    queryKey: ["resumes"],
    queryFn: ({ signal }) => fetchResumes(signal),
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
  const lanes = useQuery({ queryKey: ["lanes"], queryFn: ({ signal }) => fetchLanes(signal) });
  const upload = useMutation({
    mutationFn: uploadResume,
    onSuccess: async () => {
      polls.current = 0;
      if (fileInput.current) {
        fileInput.current.value = "";
      }
      await client.invalidateQueries({ queryKey: ["resumes"] });
    },
  });

  function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const file = fileInput.current?.files?.[0];
    if (file) {
      upload.mutate(file);
    }
  }

  return (
    <section aria-labelledby="resumes-title">
      <h1 id="resumes-title">Resumes</h1>
      <p>
        Your original files are stored exactly as uploaded and are never changed. To use a new
        version, upload it as a new resume.
      </p>
      <form aria-label="Upload resume" onSubmit={submit}>
        <label>
          Resume file (PDF or DOCX)
          <input ref={fileInput} type="file" accept=".pdf,.docx" required />
        </label>{" "}
        <button type="submit" disabled={upload.isPending}>
          Upload
        </button>
      </form>
      {upload.isPending && <p role="status">Uploading…</p>}
      {upload.isError && <p role="alert">{uploadErrorMessage(upload.error)}</p>}

      {resumes.isPending && <p role="status">Loading resumes…</p>}
      {resumes.isError && <p role="alert">Could not load resumes.</p>}
      {resumes.isSuccess && resumes.data.length === 0 && <p>No resumes yet.</p>}
      {resumes.isSuccess && resumes.data.length > 0 && (
        <ul>
          {resumes.data.map((resume) => (
            <ResumeItem key={resume.id} resume={resume} lanes={lanes.data ?? []} />
          ))}
        </ul>
      )}
    </section>
  );
}
