import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { SubmitEvent } from "react";

import { fetchProfile, saveProfile } from "../api/profile";
import type { Profile as ProfileData, ProfileUpdate } from "../api/profile";

type Relocation = ProfileUpdate["relocation_preference"];
type Remote = ProfileUpdate["remote_preference"];
type Priority = "high" | "normal" | "low";

interface AuthorizationRow {
  country: string;
  status: string;
  sponsorship: "" | "yes" | "no";
}

interface RoleRow {
  name: string;
  priority: Priority;
  notes: string;
}

function sponsorshipValue(value: boolean | null | undefined): AuthorizationRow["sponsorship"] {
  if (value === true) {
    return "yes";
  }
  return value === false ? "no" : "";
}

function sponsorshipFlag(value: AuthorizationRow["sponsorship"]): boolean | null {
  if (value === "") {
    return null;
  }
  return value === "yes";
}

function ProfileForm({ profile }: { profile: ProfileData }) {
  const client = useQueryClient();
  const [headline, setHeadline] = useState(profile.headline ?? "");
  const [summary, setSummary] = useState(profile.summary ?? "");
  const [location, setLocation] = useState(profile.current_location ?? "");
  const [relocation, setRelocation] = useState<Relocation>(profile.relocation_preference);
  const [remote, setRemote] = useState<Remote>(profile.remote_preference);
  const [authorization, setAuthorization] = useState<AuthorizationRow[]>(
    profile.work_authorization.map((entry) => ({
      country: entry.country,
      status: entry.status,
      sponsorship: sponsorshipValue(entry.sponsorship_needed),
    })),
  );
  const [roles, setRoles] = useState<RoleRow[]>(
    profile.target_roles.map((role) => ({
      name: role.name,
      priority: role.priority,
      notes: role.notes,
    })),
  );
  const [tone, setTone] = useState(profile.communication_preferences.tone);
  const [length, setLength] = useState(profile.communication_preferences.length);
  const [signOff, setSignOff] = useState(profile.communication_preferences.sign_off);
  const [avoid, setAvoid] = useState((profile.communication_preferences.avoid ?? []).join("\n"));

  const save = useMutation({
    mutationFn: saveProfile,
    onSuccess: (saved) => {
      client.setQueryData(["profile"], saved);
    },
  });

  function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    save.mutate({
      headline,
      summary,
      current_location: location,
      relocation_preference: relocation,
      remote_preference: remote,
      work_authorization: authorization.map((row) => ({
        country: row.country,
        status: row.status,
        sponsorship_needed: sponsorshipFlag(row.sponsorship),
      })),
      target_roles: roles.map((role) => ({
        name: role.name,
        priority: role.priority,
        notes: role.notes,
      })),
      communication_preferences: {
        tone,
        length,
        sign_off: signOff,
        avoid: avoid
          .split("\n")
          .map((item) => item.trim())
          .filter((item) => item !== ""),
      },
    });
  }

  function updateAuthorization(index: number, change: Partial<AuthorizationRow>) {
    setAuthorization((rows) =>
      rows.map((row, position) => (position === index ? { ...row, ...change } : row)),
    );
  }

  function updateRole(index: number, change: Partial<RoleRow>) {
    setRoles((rows) =>
      rows.map((row, position) => (position === index ? { ...row, ...change } : row)),
    );
  }

  return (
    <form onSubmit={submit}>
      <p>
        <label>
          Headline
          <input
            value={headline}
            maxLength={200}
            onChange={(event) => {
              setHeadline(event.target.value);
            }}
          />
        </label>
      </p>
      <p>
        <label>
          Summary
          <textarea
            value={summary}
            maxLength={4000}
            onChange={(event) => {
              setSummary(event.target.value);
            }}
          />
        </label>
      </p>

      <h2>Constraints</h2>
      <p>
        <label>
          Current location
          <input
            value={location}
            maxLength={200}
            onChange={(event) => {
              setLocation(event.target.value);
            }}
          />
        </label>
      </p>
      <p>
        <label>
          Relocation
          <select
            value={relocation}
            onChange={(event) => {
              setRelocation(event.target.value as Relocation);
            }}
          >
            <option value="unspecified">Not specified</option>
            <option value="open">Open to relocating</option>
            <option value="not_open">Not open to relocating</option>
          </select>
        </label>
      </p>
      <p>
        <label>
          Work arrangement
          <select
            value={remote}
            onChange={(event) => {
              setRemote(event.target.value as Remote);
            }}
          >
            <option value="no_preference">No preference</option>
            <option value="remote_only">Remote only</option>
            <option value="hybrid">Hybrid</option>
            <option value="onsite">On-site</option>
          </select>
        </label>
      </p>

      <h3>Work authorization</h3>
      {authorization.map((row, index) => (
        <p key={index}>
          <label>
            Country code
            <input
              value={row.country}
              maxLength={2}
              onChange={(event) => {
                updateAuthorization(index, { country: event.target.value });
              }}
            />
          </label>{" "}
          <label>
            Status
            <input
              value={row.status}
              maxLength={100}
              onChange={(event) => {
                updateAuthorization(index, { status: event.target.value });
              }}
            />
          </label>{" "}
          <label>
            Sponsorship needed
            <select
              value={row.sponsorship}
              onChange={(event) => {
                updateAuthorization(index, {
                  sponsorship: event.target.value as AuthorizationRow["sponsorship"],
                });
              }}
            >
              <option value="">Not specified</option>
              <option value="yes">Yes</option>
              <option value="no">No</option>
            </select>
          </label>{" "}
          <button
            type="button"
            onClick={() => {
              setAuthorization((rows) => rows.filter((_, position) => position !== index));
            }}
          >
            Remove authorization
          </button>
        </p>
      ))}
      <button
        type="button"
        disabled={authorization.length >= 20}
        onClick={() => {
          setAuthorization((rows) => [...rows, { country: "", status: "", sponsorship: "" }]);
        }}
      >
        Add authorization
      </button>

      <h2>Target roles</h2>
      {roles.map((role, index) => (
        <p key={index}>
          <label>
            Role name
            <input
              value={role.name}
              maxLength={120}
              onChange={(event) => {
                updateRole(index, { name: event.target.value });
              }}
            />
          </label>{" "}
          <label>
            Priority
            <select
              value={role.priority}
              onChange={(event) => {
                updateRole(index, { priority: event.target.value as Priority });
              }}
            >
              <option value="high">High</option>
              <option value="normal">Normal</option>
              <option value="low">Low</option>
            </select>
          </label>{" "}
          <label>
            Notes
            <input
              value={role.notes}
              maxLength={1000}
              onChange={(event) => {
                updateRole(index, { notes: event.target.value });
              }}
            />
          </label>{" "}
          <button
            type="button"
            onClick={() => {
              setRoles((rows) => rows.filter((_, position) => position !== index));
            }}
          >
            Remove role
          </button>
        </p>
      ))}
      <button
        type="button"
        disabled={roles.length >= 20}
        onClick={() => {
          setRoles((rows) => [...rows, { name: "", priority: "normal", notes: "" }]);
        }}
      >
        Add role
      </button>

      <h2>Communication preferences</h2>
      <p>
        <label>
          Tone
          <input
            value={tone}
            maxLength={200}
            onChange={(event) => {
              setTone(event.target.value);
            }}
          />
        </label>
      </p>
      <p>
        <label>
          Length
          <input
            value={length}
            maxLength={200}
            onChange={(event) => {
              setLength(event.target.value);
            }}
          />
        </label>
      </p>
      <p>
        <label>
          Sign-off
          <input
            value={signOff}
            maxLength={200}
            onChange={(event) => {
              setSignOff(event.target.value);
            }}
          />
        </label>
      </p>
      <p>
        <label>
          Things to avoid (one per line)
          <textarea
            value={avoid}
            onChange={(event) => {
              setAvoid(event.target.value);
            }}
          />
        </label>
      </p>

      <button type="submit" disabled={save.isPending}>
        Save profile
      </button>
      {save.isSuccess && <p role="status">Saved.</p>}
      {save.isError && <p role="alert">Could not save the profile. Check the fields and try again.</p>}
    </form>
  );
}

export function Profile() {
  const profile = useQuery({
    queryKey: ["profile"],
    queryFn: ({ signal }) => fetchProfile(signal),
    staleTime: Infinity,
  });

  return (
    <section aria-labelledby="profile-title">
      <h1 id="profile-title">Profile</h1>
      {profile.isPending && <p role="status">Loading profile…</p>}
      {profile.isError && <p role="alert">Could not load your profile.</p>}
      {profile.isSuccess && <ProfileForm profile={profile.data} />}
    </section>
  );
}
