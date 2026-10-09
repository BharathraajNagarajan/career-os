import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { actionsKey, fetchActions } from "../api/actions";
import { contactsForOpportunityKey, fetchContacts } from "../api/contacts";
import { InteractionForm } from "./InteractionForm";
import { humanizeWord } from "./relationshipMessages";

export function OpportunityRelationships({ opportunityId }: { opportunityId: string }) {
  const contacts = useQuery({
    queryKey: contactsForOpportunityKey(opportunityId),
    queryFn: ({ signal }) => fetchContacts({ opportunityId }, signal),
  });
  const actions = useQuery({
    queryKey: actionsKey(`opportunity:${opportunityId}`),
    queryFn: ({ signal }) =>
      fetchActions({ statuses: ["open", "snoozed"], opportunityId }, signal),
  });

  return (
    <>
      <section aria-labelledby="linked-contacts-title">
        <h2 id="linked-contacts-title">Contacts</h2>
        {contacts.isPending && <p role="status">Loading…</p>}
        {contacts.isError && <p role="alert">Could not load contacts.</p>}
        {contacts.isSuccess && contacts.data.length === 0 && <p>No linked contacts.</p>}
        {contacts.isSuccess && (
          <ul>
            {contacts.data.map((contact) => (
              <li key={contact.id}>
                <Link to={`/contacts/${contact.id}`}>{contact.full_name}</Link>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section aria-labelledby="opportunity-actions-title">
        <h2 id="opportunity-actions-title">Open actions</h2>
        {actions.isPending && <p role="status">Loading…</p>}
        {actions.isError && <p role="alert">Could not load actions.</p>}
        {actions.isSuccess && actions.data.length === 0 && <p>No open actions.</p>}
        {actions.isSuccess && (
          <ul>
            {actions.data.map((action) => (
              <li key={action.id}>
                {action.title} ({humanizeWord(action.kind)}
                {action.due_at !== null && <>, due {new Date(action.due_at).toLocaleString()}</>})
              </li>
            ))}
          </ul>
        )}
        <p>
          <Link to="/actions">Manage actions</Link>
        </p>
      </section>
      <InteractionForm opportunityId={opportunityId} />
    </>
  );
}
