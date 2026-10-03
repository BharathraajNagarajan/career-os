import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import type { SubmitEvent } from "react";
import { Link, useParams } from "react-router-dom";

import { COMPANIES_KEY, fetchCompanies } from "../api/companies";
import type { Company } from "../api/companies";
import {
  OPPORTUNITIES_KEY,
  addQualification,
  deleteQualification,
  duplicatesKey,
  fetchDuplicates,
  fetchOpportunity,
  opportunityKey,
  patchOpportunity,
  patchQualification,
  retryExtraction,
  setOpportunityPriority,
} from "../api/opportunities";
import type {
  LocationItem,
  OpportunityDetail as Detail,
  Priority,
  Qualification,
  WorkplaceType,
} from "../api/opportunities";
import { ApplicationSection, DecisionPanel } from "./OpportunityWorkflow";
import {
  CONFLICT_MESSAGE,
  editErrorMessage,
  extractionMessage,
  isConflict,
} from "./opportunityMessages";

export const POLL_INTERVAL_MS = 2000;
export const MAX_POLLS = 60;

const PRIORITIES: Priority[] = ["high", "normal", "low"];
const WORKPLACE_TYPES: WorkplaceType[] = ["unspecified", "onsite", "hybrid", "remote"];
const KINDS = ["minimum", "preferred"] as const;
const CATEGORIES = [
  "skill",
  "experience",
  "education",
  "domain",
  "authorization",
  "location",
  "other",
] as const;

interface LocationDraft {
  city: string;
  region: string;
  country: string;
}

function toDrafts(items: LocationItem[] | undefined): LocationDraft[] {
  return (items ?? []).map((item) => ({
    city: item.city ?? "",
    region: item.region ?? "",
    country: item.country ?? "",
  }));
}

function orNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

function parseKeys(value: string): string[] {
  return value
    .split(",")
    .map((key) => key.trim())
    .filter((key) => key !== "");
}

function parseYears(value: string): number | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : Number(trimmed);
}

function fieldSignature(detail: Detail): string {
  return JSON.stringify([
    detail.title,
    detail.team,
    detail.external_job_id,
    detail.location_text,
    detail.locations.items,
    detail.workplace_type,
    detail.company?.id ?? null,
    detail.source_url,
  ]);
}

interface FieldsFormProps {
  detail: Detail;
  companies: Company[];
  onSaved: (detail: Detail) => void;
  onConflict: () => void;
}

function FieldsForm({ detail, companies, onSaved, onConflict }: FieldsFormProps) {
  const [title, setTitle] = useState(detail.title ?? "");
  const [team, setTeam] = useState(detail.team ?? "");
  const [jobId, setJobId] = useState(detail.external_job_id ?? "");
  const [locationText, setLocationText] = useState(detail.location_text ?? "");
  const [locations, setLocations] = useState(() => toDrafts(detail.locations.items));
  const [workplace, setWorkplace] = useState<WorkplaceType>(detail.workplace_type);
  const [companyId, setCompanyId] = useState(detail.company?.id ?? "");
  const [sourceUrl, setSourceUrl] = useState(detail.source_url ?? "");
  const save = useMutation({
    mutationFn: () =>
      patchOpportunity(detail.id, {
        expected_state_version: detail.state_version,
        title: orNull(title),
        team: orNull(team),
        external_job_id: orNull(jobId),
        location_text: orNull(locationText),
        locations: {
          schema_version: 1,
          items: locations
            .map((row) => ({
              city: orNull(row.city),
              region: orNull(row.region),
              country: orNull(row.country),
            }))
            .filter((row) => row.city !== null || row.region !== null || row.country !== null),
        },
        workplace_type: workplace,
        company_id: companyId === "" ? null : companyId,
        source_url: orNull(sourceUrl),
      }),
    onSuccess: onSaved,
    onError: (error) => {
      if (isConflict(error)) {
        onConflict();
      }
    },
  });

  function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    save.mutate();
  }

  function updateLocation(index: number, change: Partial<LocationDraft>) {
    setLocations((rows) => rows.map((row, i) => (i === index ? { ...row, ...change } : row)));
  }

  return (
    <form aria-label="Edit posting" onSubmit={submit}>
      <p>
        <label>
          Title
          <input
            value={title}
            maxLength={300}
            onChange={(event) => {
              setTitle(event.target.value);
            }}
          />
        </label>
      </p>
      <p>
        <label>
          Company
          <select
            value={companyId}
            onChange={(event) => {
              setCompanyId(event.target.value);
            }}
          >
            <option value="">No company</option>
            {companies.map((company) => (
              <option key={company.id} value={company.id}>
                {company.name}
              </option>
            ))}
          </select>
        </label>
      </p>
      <p>
        <label>
          Team
          <input
            value={team}
            maxLength={300}
            onChange={(event) => {
              setTeam(event.target.value);
            }}
          />
        </label>
      </p>
      <p>
        <label>
          Job ID
          <input
            value={jobId}
            maxLength={200}
            onChange={(event) => {
              setJobId(event.target.value);
            }}
          />
        </label>
      </p>
      <p>
        <label>
          Location
          <input
            value={locationText}
            maxLength={500}
            onChange={(event) => {
              setLocationText(event.target.value);
            }}
          />
        </label>
      </p>
      <p>
        <label>
          Workplace type
          <select
            value={workplace}
            onChange={(event) => {
              setWorkplace(event.target.value as WorkplaceType);
            }}
          >
            {WORKPLACE_TYPES.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
        </label>
      </p>
      <fieldset>
        <legend>Places</legend>
        {locations.map((row, index) => (
          <p key={index}>
            <input
              aria-label={`City ${String(index + 1)}`}
              value={row.city}
              maxLength={100}
              onChange={(event) => {
                updateLocation(index, { city: event.target.value });
              }}
            />{" "}
            <input
              aria-label={`Region ${String(index + 1)}`}
              value={row.region}
              maxLength={100}
              onChange={(event) => {
                updateLocation(index, { region: event.target.value });
              }}
            />{" "}
            <input
              aria-label={`Country code ${String(index + 1)}`}
              value={row.country}
              maxLength={2}
              onChange={(event) => {
                updateLocation(index, { country: event.target.value });
              }}
            />{" "}
            <button
              type="button"
              aria-label={`Remove place ${String(index + 1)}`}
              onClick={() => {
                setLocations((rows) => rows.filter((_, i) => i !== index));
              }}
            >
              Remove
            </button>
          </p>
        ))}
        <button
          type="button"
          onClick={() => {
            setLocations((rows) => [...rows, { city: "", region: "", country: "" }]);
          }}
        >
          Add place
        </button>
      </fieldset>
      <p>
        <label>
          Source URL
          <input
            value={sourceUrl}
            maxLength={2048}
            onChange={(event) => {
              setSourceUrl(event.target.value);
            }}
          />
        </label>
      </p>
      <button type="submit" disabled={save.isPending}>
        Save changes
      </button>
      {save.isError && <p role="alert">{editErrorMessage(save.error)}</p>}
    </form>
  );
}

interface QualificationRowProps {
  qualification: Qualification;
  index: number;
  onChanged: () => Promise<void>;
}

function QualificationRow({ qualification, index, onChanged }: QualificationRowProps) {
  const label = String(index + 1);
  const [kind, setKind] = useState(qualification.kind);
  const [category, setCategory] = useState(qualification.category);
  const [keys, setKeys] = useState(qualification.skill_keys.join(", "));
  const [years, setYears] = useState(qualification.min_years?.toString() ?? "");
  const [hard, setHard] = useState(qualification.is_hard_constraint);
  const save = useMutation({
    mutationFn: () =>
      patchQualification(qualification.id, {
        kind,
        category,
        skill_keys: parseKeys(keys),
        min_years: parseYears(years),
        is_hard_constraint: hard,
      }),
    onSuccess: onChanged,
  });
  const remove = useMutation({
    mutationFn: () => deleteQualification(qualification.id),
    onSuccess: onChanged,
  });

  return (
    <tr>
      <td>{qualification.text_verbatim}</td>
      <td>{qualification.origin}</td>
      <td>
        <select
          aria-label={`Kind ${label}`}
          value={kind}
          onChange={(event) => {
            setKind(event.target.value as typeof kind);
          }}
        >
          {KINDS.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
      </td>
      <td>
        <select
          aria-label={`Category ${label}`}
          value={category}
          onChange={(event) => {
            setCategory(event.target.value as typeof category);
          }}
        >
          {CATEGORIES.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
      </td>
      <td>
        <input
          aria-label={`Skills ${label}`}
          value={keys}
          onChange={(event) => {
            setKeys(event.target.value);
          }}
        />
      </td>
      <td>
        <input
          aria-label={`Minimum years ${label}`}
          type="number"
          min={0}
          max={50}
          value={years}
          onChange={(event) => {
            setYears(event.target.value);
          }}
        />
      </td>
      <td>
        <input
          aria-label={`Hard constraint ${label}`}
          type="checkbox"
          checked={hard}
          onChange={(event) => {
            setHard(event.target.checked);
          }}
        />
      </td>
      <td>
        <button
          type="button"
          aria-label={`Save requirement ${label}`}
          disabled={save.isPending}
          onClick={() => {
            save.mutate();
          }}
        >
          Save
        </button>{" "}
        <button
          type="button"
          aria-label={`Delete requirement ${label}`}
          disabled={remove.isPending}
          onClick={() => {
            remove.mutate();
          }}
        >
          Delete
        </button>
        {(save.isError || remove.isError) && <span role="alert"> Could not save that change.</span>}
      </td>
    </tr>
  );
}

interface AddQualificationProps {
  opportunityId: string;
  onChanged: () => Promise<void>;
}

function AddQualification({ opportunityId, onChanged }: AddQualificationProps) {
  const [text, setText] = useState("");
  const [kind, setKind] = useState<(typeof KINDS)[number]>("minimum");
  const [category, setCategory] = useState<(typeof CATEGORIES)[number]>("skill");
  const [keys, setKeys] = useState("");
  const [years, setYears] = useState("");
  const [hard, setHard] = useState(false);
  const add = useMutation({
    mutationFn: () =>
      addQualification(opportunityId, {
        kind,
        category,
        text_verbatim: text,
        skill_keys: parseKeys(keys),
        min_years: parseYears(years),
        is_hard_constraint: hard,
      }),
    onSuccess: async () => {
      setText("");
      setKeys("");
      setYears("");
      setHard(false);
      await onChanged();
    },
  });

  return (
    <form
      aria-label="Add requirement"
      onSubmit={(event) => {
        event.preventDefault();
        add.mutate();
      }}
    >
      <p>
        <label>
          Requirement text
          <input
            value={text}
            maxLength={1000}
            onChange={(event) => {
              setText(event.target.value);
            }}
          />
        </label>{" "}
        <label>
          New kind
          <select
            value={kind}
            onChange={(event) => {
              setKind(event.target.value as typeof kind);
            }}
          >
            {KINDS.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>{" "}
        <label>
          New category
          <select
            value={category}
            onChange={(event) => {
              setCategory(event.target.value as typeof category);
            }}
          >
            {CATEGORIES.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>{" "}
        <label>
          New skills (comma separated)
          <input
            value={keys}
            onChange={(event) => {
              setKeys(event.target.value);
            }}
          />
        </label>{" "}
        <label>
          New minimum years
          <input
            type="number"
            min={0}
            max={50}
            value={years}
            onChange={(event) => {
              setYears(event.target.value);
            }}
          />
        </label>{" "}
        <label>
          New hard constraint
          <input
            type="checkbox"
            checked={hard}
            onChange={(event) => {
              setHard(event.target.checked);
            }}
          />
        </label>{" "}
        <button type="submit" disabled={add.isPending || text.trim() === ""}>
          Add requirement
        </button>
      </p>
      {add.isError && <p role="alert">Could not add that requirement.</p>}
    </form>
  );
}

function DuplicatesPanel({ opportunityId }: { opportunityId: string }) {
  const duplicates = useQuery({
    queryKey: duplicatesKey(opportunityId),
    queryFn: ({ signal }) => fetchDuplicates(opportunityId, signal),
  });

  return (
    <section aria-labelledby="duplicates-title">
      <h2 id="duplicates-title">Possible duplicates</h2>
      {duplicates.isPending && <p role="status">Checking…</p>}
      {duplicates.isError && <p role="alert">Could not check for duplicates.</p>}
      {duplicates.isSuccess && duplicates.data.length === 0 && <p>No likely duplicates.</p>}
      {duplicates.isSuccess && duplicates.data.length > 0 && (
        <ul>
          {duplicates.data.map((match) => (
            <li key={match.opportunity.id}>
              <Link to={`/opportunities/${match.opportunity.id}`}>
                {match.opportunity.title ?? "Untitled posting"}
              </Link>{" "}
              <span>
                {match.reason === "exact_job_id" ? "Same job ID" : "Similar title"} at{" "}
                {match.opportunity.company?.name ?? "an unknown company"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function OpportunityDetail() {
  const { opportunityId = "" } = useParams();
  const client = useQueryClient();
  const polls = useRef(0);
  const [notice, setNotice] = useState<string | null>(null);
  const detail = useQuery({
    queryKey: opportunityKey(opportunityId),
    queryFn: ({ signal }) => fetchOpportunity(opportunityId, signal),
    refetchInterval: (query) => {
      if (query.state.data?.extraction_status !== "pending") {
        polls.current = 0;
        return false;
      }
      polls.current += 1;
      return polls.current > MAX_POLLS ? false : POLL_INTERVAL_MS;
    },
  });
  const companies = useQuery({
    queryKey: COMPANIES_KEY,
    queryFn: ({ signal }) => fetchCompanies(signal),
  });

  const refresh = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: opportunityKey(opportunityId) }),
      client.invalidateQueries({ queryKey: OPPORTUNITIES_KEY }),
      client.invalidateQueries({ queryKey: duplicatesKey(opportunityId) }),
    ]);
  };
  const stored = (next: Detail) => {
    setNotice(null);
    client.setQueryData(opportunityKey(opportunityId), next);
    void client.invalidateQueries({ queryKey: OPPORTUNITIES_KEY });
    void client.invalidateQueries({ queryKey: duplicatesKey(opportunityId) });
  };
  const priority = useMutation({
    mutationFn: (value: Priority) => setOpportunityPriority(opportunityId, value),
    onSuccess: stored,
  });
  const retry = useMutation({
    mutationFn: () => retryExtraction(opportunityId),
    onSuccess: (next) => {
      polls.current = 0;
      stored(next);
    },
  });

  if (detail.isPending) {
    return <p role="status">Loading…</p>;
  }
  if (detail.isError) {
    return <p role="alert">Could not load this posting.</p>;
  }
  const data = detail.data;

  return (
    <section aria-labelledby="opportunity-title">
      <p>
        <Link to="/opportunities">All opportunities</Link>
      </p>
      <h1 id="opportunity-title">{data.title ?? "Untitled posting"}</h1>
      <p>
        {data.company?.name ?? "No company yet"} · Status: {data.status}
      </p>
      <p role="status">{extractionMessage(data.extraction_status, data.extraction_error_code)}</p>
      {data.extraction_status === "failed" && (
        <p>
          <button
            type="button"
            disabled={retry.isPending}
            onClick={() => {
              retry.mutate();
            }}
          >
            Retry extraction
          </button>{" "}
          This starts one new model call.
        </p>
      )}
      {retry.isError && <p role="alert">Could not start extraction.</p>}
      {notice && <p role="alert">{notice}</p>}

      <p>
        <label>
          Priority
          <select
            value={data.priority}
            onChange={(event) => {
              priority.mutate(event.target.value as Priority);
            }}
          >
            {PRIORITIES.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
      </p>
      {priority.isError && <p role="alert">Could not change the priority.</p>}

      <DecisionPanel detail={data} />
      <ApplicationSection opportunityId={data.id} />

      {data.source_url !== null && (
        <p>
          Source URL (shown as text, never opened or fetched): <span>{data.source_url}</span>
        </p>
      )}

      <FieldsForm
        key={fieldSignature(data)}
        detail={data}
        companies={companies.data ?? []}
        onSaved={stored}
        onConflict={() => {
          setNotice(CONFLICT_MESSAGE);
          void refresh();
        }}
      />

      <h2>Requirements</h2>
      <p>
        The original wording is kept and cannot be edited. The kind, category, skills, years and
        hard-constraint flag can.
      </p>
      {data.qualifications.length === 0 ? (
        <p>No requirements yet.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Original wording</th>
              <th>Origin</th>
              <th>Kind</th>
              <th>Category</th>
              <th>Skills</th>
              <th>Years</th>
              <th>Hard</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {data.qualifications.map((row, index) => (
              <QualificationRow
                key={`${row.id}:${row.updated_at}`}
                qualification={row}
                index={index}
                onChanged={refresh}
              />
            ))}
          </tbody>
        </table>
      )}
      <AddQualification opportunityId={data.id} onChanged={refresh} />

      <DuplicatesPanel opportunityId={data.id} />

      <h2>Job description (as pasted)</h2>
      <pre>{data.jd_text}</pre>
    </section>
  );
}
