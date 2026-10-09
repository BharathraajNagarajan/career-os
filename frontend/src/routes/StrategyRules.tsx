import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { SubmitEvent } from "react";

import { COMPANIES_KEY, fetchCompanies } from "../api/companies";
import { fetchLanes } from "../api/resumes";
import { RULES_KEY, createRule, deleteRule, fetchRules, patchRule } from "../api/rules";
import type { RuleScope, RuleType, StrategyRule } from "../api/rules";
import { humanizeWord, relationshipErrorMessage } from "./relationshipMessages";

const SCOPES: RuleScope[] = ["global", "company", "lane"];
const TYPES: RuleType[] = ["constraint", "preference", "cooldown"];

function RuleRow({ rule, targetName }: { rule: StrategyRule; targetName: string | null }) {
  const client = useQueryClient();
  const [statement, setStatement] = useState(rule.statement);
  const [ruleType, setRuleType] = useState<RuleType>(rule.rule_type);
  const refresh = () => client.invalidateQueries({ queryKey: RULES_KEY });
  const save = useMutation({
    mutationFn: () => patchRule(rule.id, { statement: statement.trim(), rule_type: ruleType }),
    onSuccess: refresh,
  });
  const toggle = useMutation({
    mutationFn: () => patchRule(rule.id, { active: !rule.active }),
    onSuccess: refresh,
  });
  const remove = useMutation({ mutationFn: () => deleteRule(rule.id), onSuccess: refresh });
  const failure = save.error ?? toggle.error ?? remove.error;

  return (
    <li>
      <form
        aria-label={`Edit rule ${rule.statement}`}
        onSubmit={(event: SubmitEvent<HTMLFormElement>) => {
          event.preventDefault();
          save.mutate();
        }}
      >
        <p>
          {humanizeWord(rule.scope)}
          {targetName !== null && <> – {targetName}</>} – {rule.active ? "enabled" : "disabled"}
        </p>
        <p>
          <label>
            Statement
            <textarea
              rows={2}
              maxLength={1000}
              value={statement}
              onChange={(event) => {
                setStatement(event.target.value);
              }}
            />
          </label>{" "}
          <label>
            Type
            <select
              value={ruleType}
              onChange={(event) => {
                setRuleType(event.target.value as RuleType);
              }}
            >
              {TYPES.map((value) => (
                <option key={value} value={value}>
                  {humanizeWord(value)}
                </option>
              ))}
            </select>
          </label>
        </p>
        <button type="submit" disabled={save.isPending || statement.trim() === ""}>
          Save rule
        </button>{" "}
        <button
          type="button"
          disabled={toggle.isPending}
          onClick={() => {
            toggle.mutate();
          }}
        >
          {rule.active ? "Disable" : "Enable"}
        </button>{" "}
        <button
          type="button"
          disabled={remove.isPending}
          onClick={() => {
            remove.mutate();
          }}
        >
          Delete rule
        </button>
        {save.isSuccess && <p role="status">Saved.</p>}
        {failure !== null && <p role="alert">{relationshipErrorMessage(failure)}</p>}
      </form>
    </li>
  );
}

function CreateRuleForm() {
  const client = useQueryClient();
  const companies = useQuery({
    queryKey: COMPANIES_KEY,
    queryFn: ({ signal }) => fetchCompanies(signal),
  });
  const lanes = useQuery({ queryKey: ["lanes"], queryFn: ({ signal }) => fetchLanes(signal) });
  const [scope, setScope] = useState<RuleScope>("global");
  const [targetId, setTargetId] = useState("");
  const [statement, setStatement] = useState("");
  const [ruleType, setRuleType] = useState<RuleType>("preference");
  const create = useMutation({
    mutationFn: () =>
      createRule({
        scope,
        company_id: scope === "company" ? targetId : null,
        lane_id: scope === "lane" ? targetId : null,
        statement: statement.trim(),
        rule_type: ruleType,
        condition: null,
        active: true,
      }),
    onSuccess: async () => {
      setStatement("");
      await client.invalidateQueries({ queryKey: RULES_KEY });
    },
  });
  const needsTarget = scope !== "global";

  return (
    <form
      aria-label="Add rule"
      onSubmit={(event: SubmitEvent<HTMLFormElement>) => {
        event.preventDefault();
        create.mutate();
      }}
    >
      <h2>Add a rule</h2>
      <p>
        <label>
          Scope
          <select
            value={scope}
            onChange={(event) => {
              setScope(event.target.value as RuleScope);
              setTargetId("");
            }}
          >
            {SCOPES.map((value) => (
              <option key={value} value={value}>
                {humanizeWord(value)}
              </option>
            ))}
          </select>
        </label>{" "}
        {scope === "company" && (
          <label>
            Company
            <select
              value={targetId}
              onChange={(event) => {
                setTargetId(event.target.value);
              }}
            >
              <option value="">Choose a company</option>
              {companies.data?.map((company) => (
                <option key={company.id} value={company.id}>
                  {company.name}
                </option>
              ))}
            </select>
          </label>
        )}
        {scope === "lane" && (
          <label>
            Lane
            <select
              value={targetId}
              onChange={(event) => {
                setTargetId(event.target.value);
              }}
            >
              <option value="">Choose a lane</option>
              {lanes.data?.map((lane) => (
                <option key={lane.id} value={lane.id}>
                  {lane.name}
                </option>
              ))}
            </select>
          </label>
        )}
      </p>
      <p>
        <label>
          Type
          <select
            value={ruleType}
            onChange={(event) => {
              setRuleType(event.target.value as RuleType);
            }}
          >
            {TYPES.map((value) => (
              <option key={value} value={value}>
                {humanizeWord(value)}
              </option>
            ))}
          </select>
        </label>
      </p>
      <p>
        <label>
          Statement
          <textarea
            rows={2}
            maxLength={1000}
            value={statement}
            onChange={(event) => {
              setStatement(event.target.value);
            }}
          />
        </label>
      </p>
      <button
        type="submit"
        disabled={create.isPending || statement.trim() === "" || (needsTarget && targetId === "")}
      >
        Add rule
      </button>
      {create.isSuccess && <p role="status">Rule added.</p>}
      {create.isError && <p role="alert">{relationshipErrorMessage(create.error)}</p>}
    </form>
  );
}

export function StrategyRules() {
  const rules = useQuery({ queryKey: RULES_KEY, queryFn: ({ signal }) => fetchRules(signal) });
  const companies = useQuery({
    queryKey: COMPANIES_KEY,
    queryFn: ({ signal }) => fetchCompanies(signal),
  });
  const lanes = useQuery({ queryKey: ["lanes"], queryFn: ({ signal }) => fetchLanes(signal) });

  const targetName = (rule: StrategyRule): string | null => {
    if (rule.company_id !== null) {
      return companies.data?.find((item) => item.id === rule.company_id)?.name ?? null;
    }
    if (rule.lane_id !== null) {
      return lanes.data?.find((item) => item.id === rule.lane_id)?.name ?? null;
    }
    return null;
  };

  return (
    <section aria-labelledby="rules-title">
      <h1 id="rules-title">Strategy rules</h1>
      <p>Rules are stored here. Nothing evaluates them yet.</p>
      {rules.isPending && <p role="status">Loading…</p>}
      {rules.isError && <p role="alert">Could not load rules.</p>}
      {rules.isSuccess && rules.data.length === 0 && <p>No rules yet.</p>}
      {rules.isSuccess && rules.data.length > 0 && (
        <ul>
          {rules.data.map((rule) => (
            <RuleRow
              key={`${rule.id}:${rule.updated_at}`}
              rule={rule}
              targetName={targetName(rule)}
            />
          ))}
        </ul>
      )}
      <CreateRuleForm />
    </section>
  );
}
