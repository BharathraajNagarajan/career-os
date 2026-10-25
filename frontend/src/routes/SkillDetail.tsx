import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { SubmitEvent } from "react";
import { Link, useParams } from "react-router-dom";

import {
  CLAIMS_KEY,
  SKILLS_KEY,
  clearGap,
  fetchSkill,
  fetchSkills,
  markGap,
  mergeSkills,
  patchSkill,
  rejectClaim,
  skillKey,
} from "../api/evidence";
import type { Claim, SkillDetail as SkillDetailData } from "../api/evidence";
import { ClaimForm } from "./ClaimForm";
import { ClaimListItem } from "./ClaimListItem";
import { ClassificationControl } from "./ClassificationControl";
import {
  badgeLabel,
  evidenceErrorMessage,
  evidenceNeedsRefresh,
  headlineLabel,
} from "./evidenceLabels";

function useRefresh() {
  const client = useQueryClient();
  return async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: SKILLS_KEY }),
      client.invalidateQueries({ queryKey: CLAIMS_KEY }),
    ]);
  };
}

function EditForm({ skill }: { skill: SkillDetailData }) {
  const refresh = useRefresh();
  const [name, setName] = useState(skill.canonical_name);
  const [aliases, setAliases] = useState(skill.aliases.join(", "));
  const [note, setNote] = useState(skill.user_note);
  const save = useMutation({
    mutationFn: () =>
      patchSkill(skill, {
        canonical_name: name.trim(),
        aliases: aliases
          .split(",")
          .map((alias) => alias.trim())
          .filter((alias) => alias !== ""),
        user_note: note.trim(),
      }),
    onSuccess: refresh,
    onError: (error) => (evidenceNeedsRefresh(error) ? refresh() : undefined),
  });

  return (
    <form
      aria-label="Edit skill"
      onSubmit={(event: SubmitEvent<HTMLFormElement>) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <h2>Name, other names and note</h2>
      <p>
        <label>
          Skill name
          <input
            value={name}
            maxLength={100}
            onChange={(event) => {
              setName(event.target.value);
            }}
          />
        </label>
      </p>
      <p>
        <label>
          Other names (separated by commas)
          <input
            value={aliases}
            onChange={(event) => {
              setAliases(event.target.value);
            }}
          />
        </label>
      </p>
      <p>
        <label>
          Your note
          <textarea
            value={note}
            maxLength={2000}
            rows={2}
            onChange={(event) => {
              setNote(event.target.value);
            }}
          />
        </label>
      </p>
      <button type="submit" disabled={save.isPending || name.trim() === ""}>
        Save skill
      </button>
      {save.isSuccess && <p role="status">Skill saved.</p>}
      {save.isError && <p role="alert">{evidenceErrorMessage(save.error)}</p>}
    </form>
  );
}

function GapSection({ skill }: { skill: SkillDetailData }) {
  const refresh = useRefresh();
  const [note, setNote] = useState("");
  const mark = useMutation({
    mutationFn: () => markGap(skill, note),
    onSuccess: refresh,
  });
  const clear = useMutation({ mutationFn: () => clearGap(skill), onSuccess: refresh });

  return (
    <section aria-label="Gap marker">
      <h2>Gap</h2>
      {skill.user_marked_gap ? (
        <>
          <p>
            You marked this skill as a gap{skill.gap_note !== null && `: ${skill.gap_note}`}
          </p>
          <button
            type="button"
            disabled={clear.isPending}
            onClick={() => {
              clear.mutate();
            }}
          >
            Clear gap
          </button>
          {clear.isError && <p role="alert">{evidenceErrorMessage(clear.error)}</p>}
        </>
      ) : (
        <>
          <p>
            Mark a gap only when you do not have this skill. A skill with no evidence is Not
            recorded, which is not the same thing.
          </p>
          <p>
            <label>
              Gap note (optional)
              <input
                value={note}
                maxLength={2000}
                onChange={(event) => {
                  setNote(event.target.value);
                }}
              />
            </label>{" "}
            <button
              type="button"
              disabled={mark.isPending}
              onClick={() => {
                mark.mutate();
              }}
            >
              Mark as a gap
            </button>
          </p>
          {mark.isError && <p role="alert">{evidenceErrorMessage(mark.error)}</p>}
        </>
      )}
    </section>
  );
}

function MergeSection({ skill }: { skill: SkillDetailData }) {
  const refresh = useRefresh();
  const [chosen, setChosen] = useState("");
  const others = useQuery({
    queryKey: [...SKILLS_KEY, "merge-targets"],
    queryFn: ({ signal }) => fetchSkills({ q: "", category: "", engagement: "" }, signal),
  });
  const merge = useMutation({
    mutationFn: () => {
      const target = others.data?.find((candidate) => candidate.id === chosen);
      if (target === undefined) {
        throw new Error("no target");
      }
      return mergeSkills(skill, target);
    },
    onSuccess: async () => {
      setChosen("");
      await refresh();
    },
  });
  const candidates = (others.data ?? []).filter((candidate) => candidate.id !== skill.id);

  return (
    <section aria-label="Merge duplicates">
      <h2>Merge a duplicate</h2>
      <p>
        The skill you choose is merged into this one. Its evidence moves here and its names become
        other names of this skill.
      </p>
      <p>
        <label>
          Skill to merge into {skill.canonical_name}
          <select
            value={chosen}
            onChange={(event) => {
              setChosen(event.target.value);
            }}
          >
            <option value="">Choose a skill</option>
            {candidates.map((candidate) => (
              <option key={candidate.id} value={candidate.id}>
                {candidate.canonical_name}
              </option>
            ))}
          </select>
        </label>{" "}
        <button
          type="button"
          disabled={chosen === "" || merge.isPending}
          onClick={() => {
            merge.mutate();
          }}
        >
          Merge into {skill.canonical_name}
        </button>
      </p>
      {merge.isSuccess && <p role="status">Skills merged.</p>}
      {merge.isError && <p role="alert">{evidenceErrorMessage(merge.error)}</p>}
    </section>
  );
}

function EvidenceItem({ claim }: { claim: Claim }) {
  const refresh = useRefresh();
  const reject = useMutation({ mutationFn: () => rejectClaim(claim), onSuccess: refresh });
  return (
    <>
      <ul>
        <ClaimListItem claim={claim} />
      </ul>
      {claim.confirmation_status === "confirmed" && (
        <>
          <ClassificationControl claim={claim} onChanged={refresh} />
          <button
            type="button"
            disabled={reject.isPending}
            onClick={() => {
              reject.mutate();
            }}
          >
            Reject this evidence
          </button>
          {reject.isError && <p role="alert">{evidenceErrorMessage(reject.error)}</p>}
        </>
      )}
    </>
  );
}

export function SkillDetail() {
  const { skillId = "" } = useParams();
  const skill = useQuery({
    queryKey: skillKey(skillId),
    queryFn: ({ signal }) => fetchSkill(skillId, signal),
  });

  if (skill.isPending) {
    return <p role="status">Loading…</p>;
  }
  if (skill.isError) {
    return <p role="alert">Could not load this skill.</p>;
  }
  const data = skill.data;
  const live = data.claims.filter((claim) => claim.confirmation_status !== "rejected");

  return (
    <section aria-labelledby="skill-title">
      <p>
        <Link to="/skills">All skills</Link>
      </p>
      <h1 id="skill-title">{data.canonical_name}</h1>
      <p>{headlineLabel(data.headline)}</p>
      {data.merged_into_skill_id !== null ? (
        <p>
          This skill was merged into another one. Its evidence now lives there.{" "}
          <Link to={`/skills/${data.merged_into_skill_id}`}>Open the skill it was merged into</Link>
        </p>
      ) : (
        <>
          {data.badges.length > 0 && (
            <ul aria-label="Evidence badges">
              {data.badges.map((badge) => (
                <li key={`${badge.evidence_class}-${badge.engagement_type ?? ""}`}>
                  {badgeLabel(badge)} · {badge.claim_count} item{badge.claim_count === 1 ? "" : "s"}
                </li>
              ))}
            </ul>
          )}
          <EditForm
            key={`${data.canonical_name}|${data.aliases.join(",")}|${data.user_note}`}
            skill={data}
          />
          <GapSection skill={data} />
          <MergeSection skill={data} />

          <h2>Evidence</h2>
          {live.length === 0 && <p>No evidence recorded for this skill.</p>}
          <ul>
            {live.map((claim) => (
              <li key={claim.id}>
                <EvidenceItem claim={claim} />
              </li>
            ))}
          </ul>
          <ClaimForm skillIds={[data.id]} heading="Add evidence for this skill" />

          <h2>Resumes</h2>
          <p>
            This shows where the skill's name appears in resume text, or where your evidence cites a
            resume. It is text presence, not proof of proficiency.
          </p>
          {data.exposure.length === 0 && <p>Name not found in the text of any resume.</p>}
          <ul>
            {data.exposure.map((resume) => (
              <li key={resume.resume_id}>
                {resume.label}
                {resume.archived && " (archived)"}
                {" · "}
                {[
                  resume.stated ? "cited by your evidence" : null,
                  resume.mentioned ? "name appears in its text" : null,
                ]
                  .filter((part) => part !== null)
                  .join(", ")}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
