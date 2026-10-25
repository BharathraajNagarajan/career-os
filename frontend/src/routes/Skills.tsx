import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { SubmitEvent } from "react";
import { Link } from "react-router-dom";

import { SKILLS_KEY, createSkill, fetchSkills } from "../api/evidence";
import type { EngagementType, SkillCategory, SkillSummary } from "../api/evidence";
import {
  CATEGORY_OPTIONS,
  ENGAGEMENT_OPTIONS,
  badgeLabel,
  evidenceErrorMessage,
  headlineLabel,
} from "./evidenceLabels";

function splitAliases(raw: string): string[] {
  return raw
    .split(",")
    .map((alias) => alias.trim())
    .filter((alias) => alias !== "");
}

function AddSkillForm() {
  const client = useQueryClient();
  const [name, setName] = useState("");
  const [aliases, setAliases] = useState("");
  const create = useMutation({
    mutationFn: () =>
      createSkill({
        canonical_name: name.trim(),
        aliases: splitAliases(aliases),
        user_note: "",
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: SKILLS_KEY }),
  });

  return (
    <form
      aria-label="Add skill"
      onSubmit={(event: SubmitEvent<HTMLFormElement>) => {
        event.preventDefault();
        create.mutate();
      }}
    >
      <h2>Add a skill</h2>
      <p>
        Adding a skill only names it. It shows as Not recorded until you add evidence for it.
      </p>
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
      <button type="submit" disabled={create.isPending || name.trim() === ""}>
        Add skill
      </button>
      {create.isSuccess && <p role="status">Skill added.</p>}
      {create.isError && <p role="alert">{evidenceErrorMessage(create.error)}</p>}
    </form>
  );
}

function SkillRow({ skill }: { skill: SkillSummary }) {
  return (
    <li>
      <Link to={`/skills/${skill.id}`}>{skill.canonical_name}</Link>
      <br />
      <span>{headlineLabel(skill.headline)}</span>
      {skill.badges.length > 0 && (
        <ul aria-label={`Evidence for ${skill.canonical_name}`}>
          {skill.badges.map((badge) => (
            <li key={`${badge.evidence_class}-${badge.engagement_type ?? ""}`}>
              {badgeLabel(badge)}
            </li>
          ))}
        </ul>
      )}
      <br />
      <span>
        {skill.exposure.length === 0
          ? "Name not found in the text of any resume"
          : `Name appears in the text of ${String(skill.exposure.length)} resume${skill.exposure.length === 1 ? "" : "s"} (not proof of proficiency)`}
      </span>
    </li>
  );
}

export function Skills() {
  const [q, setQ] = useState("");
  const [category, setCategory] = useState<SkillCategory | "">("");
  const [engagement, setEngagement] = useState<EngagementType | "">("");
  const skills = useQuery({
    queryKey: [...SKILLS_KEY, "list", q, category, engagement],
    queryFn: ({ signal }) => fetchSkills({ q, category, engagement }, signal),
  });

  return (
    <section aria-labelledby="skills-title">
      <h1 id="skills-title">Skills</h1>
      <p>
        Each skill shows the kinds of evidence you have for it, taken from your confirmed evidence.
        A skill with no evidence is Not recorded, which is unknown, not a gap. Only you can mark a
        gap.
      </p>
      <p>
        <label>
          Search skills
          <input
            type="search"
            value={q}
            onChange={(event) => {
              setQ(event.target.value);
            }}
          />
        </label>{" "}
        <label>
          Category
          <select
            value={category}
            onChange={(event) => {
              setCategory(event.target.value as SkillCategory | "");
            }}
          >
            <option value="">All</option>
            {CATEGORY_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>{" "}
        {category === "professional" && (
          <label>
            Engagement type
            <select
              value={engagement}
              onChange={(event) => {
                setEngagement(event.target.value as EngagementType | "");
              }}
            >
              <option value="">Any</option>
              {ENGAGEMENT_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        )}
      </p>
      {skills.isPending && <p role="status">Loading…</p>}
      {skills.isError && <p role="alert">Could not load skills.</p>}
      {skills.isSuccess && skills.data.length === 0 && <p>No skills found.</p>}
      {skills.isSuccess && skills.data.length > 0 && (
        <ul>
          {skills.data.map((skill) => (
            <SkillRow key={skill.id} skill={skill} />
          ))}
        </ul>
      )}
      <AddSkillForm />
    </section>
  );
}
