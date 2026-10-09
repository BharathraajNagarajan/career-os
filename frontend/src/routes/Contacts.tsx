import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { SubmitEvent } from "react";
import { Link } from "react-router-dom";

import { CONTACTS_KEY, createContact, fetchContacts } from "../api/contacts";
import { relationshipErrorMessage, splitAddresses } from "./relationshipMessages";

function CreateContactForm() {
  const client = useQueryClient();
  const [name, setName] = useState("");
  const [emails, setEmails] = useState("");
  const [headline, setHeadline] = useState("");
  const create = useMutation({
    mutationFn: () =>
      createContact({
        full_name: name.trim(),
        emails: splitAddresses(emails),
        linkedin_url: null,
        headline: headline.trim() === "" ? null : headline.trim(),
        notes: "",
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: CONTACTS_KEY }),
  });

  return (
    <form
      aria-label="Add contact"
      onSubmit={(event: SubmitEvent<HTMLFormElement>) => {
        event.preventDefault();
        create.mutate();
      }}
    >
      <h2>Add a contact</h2>
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
          Email addresses (separated by spaces or commas)
          <input
            value={emails}
            onChange={(event) => {
              setEmails(event.target.value);
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
      <button type="submit" disabled={create.isPending || name.trim() === ""}>
        Add contact
      </button>
      {create.isSuccess && <p role="status">Contact added.</p>}
      {create.isError && <p role="alert">{relationshipErrorMessage(create.error)}</p>}
    </form>
  );
}

export function Contacts() {
  const [search, setSearch] = useState("");
  const contacts = useQuery({
    queryKey: [...CONTACTS_KEY, "list", search],
    queryFn: ({ signal }) => fetchContacts({ q: search }, signal),
  });

  return (
    <section aria-labelledby="contacts-title">
      <h1 id="contacts-title">Contacts</h1>
      <p>
        <label>
          Search by name or email
          <input
            type="search"
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
            }}
          />
        </label>
      </p>
      {contacts.isPending && <p role="status">Loading…</p>}
      {contacts.isError && <p role="alert">Could not load contacts.</p>}
      {contacts.isSuccess && contacts.data.length === 0 && <p>No contacts found.</p>}
      {contacts.isSuccess && contacts.data.length > 0 && (
        <ul>
          {contacts.data.map((contact) => (
            <li key={contact.id}>
              <Link to={`/contacts/${contact.id}`}>{contact.full_name}</Link>
              {contact.headline !== null && <span> – {contact.headline}</span>}
              {contact.emails.length > 0 && (
                <span> ({contact.emails.map((email) => email.address).join(", ")})</span>
              )}
            </li>
          ))}
        </ul>
      )}
      <CreateContactForm />
    </section>
  );
}
