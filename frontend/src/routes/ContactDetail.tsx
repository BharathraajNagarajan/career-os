import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { SubmitEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { COMPANIES_KEY, fetchCompanies } from "../api/companies";
import {
  CONTACTS_KEY,
  contactKey,
  fetchContact,
  fetchContacts,
  linkCompany,
  linkOpportunity,
  mergeContacts,
  patchContact,
  unlinkCompany,
  unlinkOpportunity,
} from "../api/contacts";
import type {
  ContactCompanyRelation,
  ContactDetail as Detail,
  ContactOpportunityRole,
} from "../api/contacts";
import { OPPORTUNITIES_KEY, fetchOpportunities } from "../api/opportunities";
import { InteractionForm } from "./InteractionForm";
import {
  humanizeWord,
  relationshipErrorMessage,
  relationshipNeedsRefresh,
  splitAddresses,
} from "./relationshipMessages";

const RELATIONS: ContactCompanyRelation[] = [
  "employee",
  "recruiter",
  "former_employee",
  "agency_recruiter",
  "other",
];
const ROLES: ContactOpportunityRole[] = [
  "recruiter",
  "hiring_manager",
  "referrer",
  "interviewer",
  "team_member",
  "other",
];

function orNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

function Failure({ error, onRefresh }: { error: unknown; onRefresh: () => void }) {
  return (
    <p role="alert">
      {relationshipErrorMessage(error)}{" "}
      {relationshipNeedsRefresh(error) && (
        <button type="button" onClick={onRefresh}>
          Refresh
        </button>
      )}
    </p>
  );
}

function useRefreshContact(contactId: string) {
  const client = useQueryClient();
  return () => client.invalidateQueries({ queryKey: contactKey(contactId) });
}

function EditForm({ contact }: { contact: Detail }) {
  const client = useQueryClient();
  const refresh = useRefreshContact(contact.id);
  const [name, setName] = useState(contact.full_name);
  const [emails, setEmails] = useState(contact.emails.map((email) => email.address).join("\n"));
  const [linkedin, setLinkedin] = useState(contact.linkedin_url ?? "");
  const [headline, setHeadline] = useState(contact.headline ?? "");
  const [notes, setNotes] = useState(contact.notes);
  const save = useMutation({
    mutationFn: () =>
      patchContact(contact, {
        full_name: name.trim(),
        emails: splitAddresses(emails),
        linkedin_url: orNull(linkedin),
        headline: orNull(headline),
        notes,
      }),
    onSuccess: (next) => {
      client.setQueryData(contactKey(contact.id), next);
      return client.invalidateQueries({ queryKey: CONTACTS_KEY });
    },
  });

  return (
    <form
      aria-label="Edit contact"
      onSubmit={(event: SubmitEvent<HTMLFormElement>) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <p>
        <label>
          Full name
          <input
            value={name}
            maxLength={200}
            onChange={(event) => {
              setName(event.target.value);
            }}
          />
        </label>
      </p>
      <p>
        <label>
          Email addresses (one per line)
          <textarea
            rows={2}
            value={emails}
            onChange={(event) => {
              setEmails(event.target.value);
            }}
          />
        </label>
      </p>
      <ul aria-label="Email sources">
        {contact.emails.map((email) => (
          <li key={email.address}>
            {email.address} <span>(source: {email.source})</span>
          </li>
        ))}
      </ul>
      <p>
        <label>
          LinkedIn URL
          <input
            value={linkedin}
            onChange={(event) => {
              setLinkedin(event.target.value);
            }}
          />
        </label>
      </p>
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
          Notes
          <textarea
            rows={3}
            maxLength={5000}
            value={notes}
            onChange={(event) => {
              setNotes(event.target.value);
            }}
          />
        </label>
      </p>
      <button type="submit" disabled={save.isPending || name.trim() === ""}>
        Save contact
      </button>
      {save.isSuccess && <p role="status">Saved.</p>}
      {save.isError && (
        <Failure
          error={save.error}
          onRefresh={() => {
            void refresh();
          }}
        />
      )}
    </form>
  );
}

function CompanyLinks({ contact }: { contact: Detail }) {
  const client = useQueryClient();
  const companies = useQuery({
    queryKey: COMPANIES_KEY,
    queryFn: ({ signal }) => fetchCompanies(signal),
  });
  const [companyId, setCompanyId] = useState("");
  const [relation, setRelation] = useState<ContactCompanyRelation>("employee");
  const [title, setTitle] = useState("");
  const store = (next: Detail) => {
    client.setQueryData(contactKey(contact.id), next);
  };
  const add = useMutation({
    mutationFn: () =>
      linkCompany(contact.id, companyId, { relation, title: orNull(title), is_current: true }),
    onSuccess: store,
  });
  const remove = useMutation({
    mutationFn: (id: string) => unlinkCompany(contact.id, id),
    onSuccess: store,
  });

  return (
    <section aria-labelledby="company-links-title">
      <h2 id="company-links-title">Companies</h2>
      {contact.companies.length === 0 && <p>No linked companies.</p>}
      <ul>
        {contact.companies.map((link) => (
          <li key={link.company_id}>
            {link.company_name} – {humanizeWord(link.relation)}
            {link.title !== null && <span>, {link.title}</span>}{" "}
            <button
              type="button"
              onClick={() => {
                remove.mutate(link.company_id);
              }}
            >
              Remove {link.company_name}
            </button>
          </li>
        ))}
      </ul>
      <form
        aria-label="Link company"
        onSubmit={(event: SubmitEvent<HTMLFormElement>) => {
          event.preventDefault();
          add.mutate();
        }}
      >
        <label>
          Company
          <select
            value={companyId}
            onChange={(event) => {
              setCompanyId(event.target.value);
            }}
          >
            <option value="">Choose a company</option>
            {companies.data?.map((company) => (
              <option key={company.id} value={company.id}>
                {company.name}
              </option>
            ))}
          </select>
        </label>{" "}
        <label>
          Relation
          <select
            value={relation}
            onChange={(event) => {
              setRelation(event.target.value as ContactCompanyRelation);
            }}
          >
            {RELATIONS.map((value) => (
              <option key={value} value={value}>
                {humanizeWord(value)}
              </option>
            ))}
          </select>
        </label>{" "}
        <label>
          Title
          <input
            value={title}
            maxLength={200}
            onChange={(event) => {
              setTitle(event.target.value);
            }}
          />
        </label>{" "}
        <button type="submit" disabled={add.isPending || companyId === ""}>
          Link company
        </button>
      </form>
      {(add.isError || remove.isError) && (
        <p role="alert">{relationshipErrorMessage(add.error ?? remove.error)}</p>
      )}
    </section>
  );
}

function OpportunityLinks({ contact }: { contact: Detail }) {
  const client = useQueryClient();
  const opportunities = useQuery({
    queryKey: OPPORTUNITIES_KEY,
    queryFn: ({ signal }) => fetchOpportunities(signal),
  });
  const [opportunityId, setOpportunityId] = useState("");
  const [role, setRole] = useState<ContactOpportunityRole>("recruiter");
  const store = (next: Detail) => {
    client.setQueryData(contactKey(contact.id), next);
  };
  const add = useMutation({
    mutationFn: () => linkOpportunity(contact.id, opportunityId, role),
    onSuccess: store,
  });
  const remove = useMutation({
    mutationFn: (link: { opportunity_id: string; role: ContactOpportunityRole }) =>
      unlinkOpportunity(contact.id, link.opportunity_id, link.role),
    onSuccess: store,
  });

  return (
    <section aria-labelledby="opportunity-links-title">
      <h2 id="opportunity-links-title">Opportunities</h2>
      {contact.opportunities.length === 0 && <p>No linked opportunities.</p>}
      <ul>
        {contact.opportunities.map((link) => (
          <li key={`${link.opportunity_id}:${link.role}`}>
            <Link to={`/opportunities/${link.opportunity_id}`}>
              {link.opportunity_title ?? "Untitled opportunity"}
            </Link>
            {link.company_name !== null && <span> at {link.company_name}</span>} –{" "}
            {humanizeWord(link.role)}{" "}
            <button
              type="button"
              onClick={() => {
                remove.mutate(link);
              }}
            >
              Remove {humanizeWord(link.role)} link
            </button>
          </li>
        ))}
      </ul>
      <form
        aria-label="Link opportunity"
        onSubmit={(event: SubmitEvent<HTMLFormElement>) => {
          event.preventDefault();
          add.mutate();
        }}
      >
        <label>
          Opportunity
          <select
            value={opportunityId}
            onChange={(event) => {
              setOpportunityId(event.target.value);
            }}
          >
            <option value="">Choose an opportunity</option>
            {opportunities.data?.map((opportunity) => (
              <option key={opportunity.id} value={opportunity.id}>
                {opportunity.title ?? "Untitled opportunity"}
              </option>
            ))}
          </select>
        </label>{" "}
        <label>
          Role
          <select
            value={role}
            onChange={(event) => {
              setRole(event.target.value as ContactOpportunityRole);
            }}
          >
            {ROLES.map((value) => (
              <option key={value} value={value}>
                {humanizeWord(value)}
              </option>
            ))}
          </select>
        </label>{" "}
        <button type="submit" disabled={add.isPending || opportunityId === ""}>
          Link opportunity
        </button>
      </form>
      {(add.isError || remove.isError) && (
        <p role="alert">{relationshipErrorMessage(add.error ?? remove.error)}</p>
      )}
    </section>
  );
}

function MergePanel({ contact }: { contact: Detail }) {
  const client = useQueryClient();
  const refresh = useRefreshContact(contact.id);
  const others = useQuery({
    queryKey: [...CONTACTS_KEY, "list", ""],
    queryFn: ({ signal }) => fetchContacts({}, signal),
  });
  const [chosenId, setChosenId] = useState("");
  const [confirming, setConfirming] = useState(false);
  const chosen = others.data?.find((item) => item.id === chosenId);
  const merge = useMutation({
    mutationFn: () => {
      if (chosen === undefined) {
        throw new Error("no contact chosen");
      }
      return mergeContacts(contact, chosen);
    },
    onSuccess: async (next) => {
      setConfirming(false);
      setChosenId("");
      client.setQueryData(contactKey(contact.id), next);
      await client.invalidateQueries({ queryKey: CONTACTS_KEY });
    },
  });

  return (
    <section aria-labelledby="merge-title">
      <h2 id="merge-title">Merge another contact into this one</h2>
      <p>
        <label>
          Contact to merge in
          <select
            value={chosenId}
            onChange={(event) => {
              setChosenId(event.target.value);
              setConfirming(false);
            }}
          >
            <option value="">Choose a contact</option>
            {others.data
              ?.filter((item) => item.id !== contact.id)
              .map((item) => (
                <option key={item.id} value={item.id}>
                  {item.full_name}
                </option>
              ))}
          </select>
        </label>{" "}
        {!confirming && (
          <button
            type="button"
            disabled={chosen === undefined}
            onClick={() => {
              setConfirming(true);
            }}
          >
            Merge…
          </button>
        )}
      </p>
      {confirming && chosen !== undefined && (
        <div role="group" aria-label="Confirm merge">
          <p>
            Merge {chosen.full_name} into {contact.full_name}? Their links, interactions, actions
            and email addresses move here, and {chosen.full_name} is removed. This cannot be
            undone.
          </p>
          <button
            type="button"
            disabled={merge.isPending}
            onClick={() => {
              merge.mutate();
            }}
          >
            Confirm merge
          </button>{" "}
          <button
            type="button"
            onClick={() => {
              setConfirming(false);
            }}
          >
            Cancel
          </button>
        </div>
      )}
      {merge.isSuccess && <p role="status">Contacts merged.</p>}
      {merge.isError && (
        <Failure
          error={merge.error}
          onRefresh={() => {
            void refresh();
            void client.invalidateQueries({ queryKey: CONTACTS_KEY });
          }}
        />
      )}
    </section>
  );
}

export function ContactDetail() {
  const { contactId = "" } = useParams();
  const navigate = useNavigate();
  const contact = useQuery({
    queryKey: contactKey(contactId),
    queryFn: ({ signal }) => fetchContact(contactId, signal),
  });

  if (contact.isPending) {
    return <p role="status">Loading…</p>;
  }
  if (contact.isError) {
    return (
      <p role="alert">
        Could not load this contact.{" "}
        <button
          type="button"
          onClick={() => {
            void navigate("/contacts");
          }}
        >
          Back to contacts
        </button>
      </p>
    );
  }
  const data = contact.data;

  return (
    <section aria-labelledby="contact-title">
      <p>
        <Link to="/contacts">All contacts</Link>
      </p>
      <h1 id="contact-title">{data.full_name}</h1>
      <EditForm key={data.updated_at} contact={data} />
      <CompanyLinks contact={data} />
      <OpportunityLinks contact={data} />
      <MergePanel contact={data} />
      <section aria-labelledby="interactions-title">
        <h2 id="interactions-title">Interactions</h2>
        {data.interactions.length === 0 && <p>No interactions yet.</p>}
        <ul>
          {data.interactions.map((item) => (
            <li key={item.id}>
              <time dateTime={item.occurred_at}>{new Date(item.occurred_at).toLocaleString()}</time>{" "}
              {humanizeWord(item.channel)}, {item.direction}
              {item.summary !== null && <p>{item.summary}</p>}
            </li>
          ))}
        </ul>
      </section>
      <section aria-labelledby="contact-actions-title">
        <h2 id="contact-actions-title">Open actions</h2>
        {data.actions.length === 0 && <p>No open actions.</p>}
        <ul>
          {data.actions.map((action) => (
            <li key={action.id}>
              {action.title} ({humanizeWord(action.kind)}
              {action.due_at !== null && <>, due {new Date(action.due_at).toLocaleString()}</>})
            </li>
          ))}
        </ul>
        <p>
          <Link to="/actions">Manage actions</Link>
        </p>
      </section>
      <InteractionForm contactId={data.id} />
    </section>
  );
}
