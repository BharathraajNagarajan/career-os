import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { SubmitEvent } from "react";
import { Link, useParams } from "react-router-dom";

import {
  CLAIMS_KEY,
  SKILLS_KEY,
  addSource,
  claimKey,
  fetchClaim,
  fetchSkills,
  linkSkill,
  patchClaim,
  rejectClaim,
  unlinkSkill,
} from "../api/evidence";
import type { Claim } from "../api/evidence";
import { ClassificationControl } from "./ClassificationControl";
import { classificationLabel, evidenceErrorMessage, sourceLabel } from "./evidenceLabels";

function useRefresh() {
  const client = useQueryClient();
  return async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: CLAIMS_KEY }),
      client.invalidateQueries({ queryKey: SKILLS_KEY }),
    ]);
  };
}

function EditForm({ claim }: { claim: Claim }) {
  const refresh = useRefresh();
  const [statement, setStatement] = useState(claim.statement);
  const [organization, setOrganization] = useState(claim.organization_label ?? "");
  const [startDate, setStartDate] = useState(claim.start_date ?? "");
  const [endDate, setEndDate] = useState(claim.end_date ?? "");
  const save = useMutation({
    mutationFn: () =>
      patchClaim(claim, {
        statement: statement.trim(),
        organization_label: organization.trim() === "" ? null : organization.trim(),
        start_date: startDate === "" ? null : startDate,
        end_date: endDate === "" ? null : endDate,
      }),
    onSuccess: refresh,
  });

  return (
    <form
      aria-label="Edit evidence"
      onSubmit={(event: SubmitEvent<HTMLFormElement>) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <h2>Statement, organization and dates</h2>
      <p>
        <label>
          Statement
          <textarea
            value={statement}
            maxLength={2000}
            rows={3}
            onChange={(event) => {
              setStatement(event.target.value);
            }}
          />
        </label>
      </p>
      <p>
        <label>
          Organization
          <input
            value={organization}
            maxLength={200}
            onChange={(event) => {
              setOrganization(event.target.value);
            }}
          />
        </label>{" "}
        <label>
          Start date
          <input
            type="date"
            value={startDate}
            onChange={(event) => {
              setStartDate(event.target.value);
            }}
          />
        </label>{" "}
        <label>
          End date
          <input
            type="date"
            value={endDate}
            onChange={(event) => {
              setEndDate(event.target.value);
            }}
          />
        </label>
      </p>
      <button type="submit" disabled={save.isPending || statement.trim() === ""}>
        Save evidence
      </button>
      {save.isSuccess && <p role="status">Evidence saved.</p>}
      {save.isError && <p role="alert">{evidenceErrorMessage(save.error)}</p>}
    </form>
  );
}

function SkillLinks({ claim }: { claim: Claim }) {
  const refresh = useRefresh();
  const [chosen, setChosen] = useState("");
  const skills = useQuery({
    queryKey: [...SKILLS_KEY, "link-targets"],
    queryFn: ({ signal }) => fetchSkills({ q: "", category: "", engagement: "" }, signal),
  });
  const link = useMutation({
    mutationFn: () => linkSkill(claim.id, chosen),
    onSuccess: async () => {
      setChosen("");
      await refresh();
    },
  });
  const unlink = useMutation({
    mutationFn: (skillId: string) => unlinkSkill(claim.id, skillId),
    onSuccess: refresh,
  });
  const linked = new Set(claim.skills.map((skill) => skill.id));
  const available = (skills.data ?? []).filter((skill) => !linked.has(skill.id));

  return (
    <section aria-label="Linked skills">
      <h2>Skills</h2>
      {claim.skills.length === 0 && <p>Not linked to any skill.</p>}
      <ul>
        {claim.skills.map((skill) => (
          <li key={skill.id}>
            <Link to={`/skills/${skill.id}`}>{skill.canonical_name}</Link>{" "}
            <button
              type="button"
              disabled={unlink.isPending}
              onClick={() => {
                unlink.mutate(skill.id);
              }}
            >
              Unlink {skill.canonical_name}
            </button>
          </li>
        ))}
      </ul>
      <p>
        <label>
          Link a skill
          <select
            value={chosen}
            onChange={(event) => {
              setChosen(event.target.value);
            }}
          >
            <option value="">Choose a skill</option>
            {available.map((skill) => (
              <option key={skill.id} value={skill.id}>
                {skill.canonical_name}
              </option>
            ))}
          </select>
        </label>{" "}
        <button
          type="button"
          disabled={chosen === "" || link.isPending}
          onClick={() => {
            link.mutate();
          }}
        >
          Link skill
        </button>
      </p>
      {(link.isError || unlink.isError) && (
        <p role="alert">{evidenceErrorMessage(link.error ?? unlink.error)}</p>
      )}
    </section>
  );
}

function Sources({ claim }: { claim: Claim }) {
  const refresh = useRefresh();
  const [words, setWords] = useState("");
  const add = useMutation({
    mutationFn: () => addSource(claim.id, { source_type: "user_assertion", assertion_text: words.trim() }),
    onSuccess: refresh,
  });

  return (
    <section aria-label="Sources">
      <h2>Sources</h2>
      <ul>
        {claim.sources.map((source) => (
          <li key={source.id}>{sourceLabel(source)}</li>
        ))}
      </ul>
      <p>
        <label>
          Add your own words as a source
          <textarea
            value={words}
            maxLength={2000}
            rows={2}
            onChange={(event) => {
              setWords(event.target.value);
            }}
          />
        </label>{" "}
        <button
          type="button"
          disabled={words.trim() === "" || add.isPending}
          onClick={() => {
            add.mutate();
          }}
        >
          Add source
        </button>
      </p>
      {add.isSuccess && <p role="status">Source added.</p>}
      {add.isError && <p role="alert">{evidenceErrorMessage(add.error)}</p>}
    </section>
  );
}

export function ClaimDetail() {
  const { claimId = "" } = useParams();
  const refresh = useRefresh();
  const claim = useQuery({
    queryKey: claimKey(claimId),
    queryFn: ({ signal }) => fetchClaim(claimId, signal),
  });
  const reject = useMutation({
    mutationFn: (current: Claim) => rejectClaim(current),
    onSuccess: refresh,
  });

  if (claim.isPending) {
    return <p role="status">Loading…</p>;
  }
  if (claim.isError) {
    return <p role="alert">Could not load this evidence.</p>;
  }
  const data = claim.data;

  return (
    <section aria-labelledby="claim-title">
      <p>
        <Link to="/claims">All evidence</Link>
      </p>
      <h1 id="claim-title">Evidence</h1>
      <p>{data.statement}</p>
      <p>
        {classificationLabel(data.evidence_class, data.engagement_type)}
        {data.confirmation_status === "rejected" && " · Rejected"}
      </p>
      {data.confirmation_status === "confirmed" && (
        <>
          <EditForm
            key={`${data.statement}|${data.organization_label ?? ""}|${data.start_date ?? ""}|${data.end_date ?? ""}`}
            claim={data}
          />
          <ClassificationControl claim={data} onChanged={refresh} />
          <SkillLinks claim={data} />
          <Sources claim={data} />
          <button
            type="button"
            disabled={reject.isPending}
            onClick={() => {
              reject.mutate(data);
            }}
          >
            Reject this evidence
          </button>
          {reject.isError && <p role="alert">{evidenceErrorMessage(reject.error)}</p>}
        </>
      )}
    </section>
  );
}
