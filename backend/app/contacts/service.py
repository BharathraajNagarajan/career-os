import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, and_, delete, func, select, text, update
from sqlalchemy.orm import Session

from app.actions.repository import RecruitingActionRepository
from app.actions.schemas import ActionResponse
from app.applications.service import run_in_transaction
from app.contacts.emails import ContactEmail, ContactEmails, EmailSource
from app.contacts.events import (
    CONTACT_CREATED,
    CONTACT_EDITED,
    CONTACT_LINKED,
    CONTACT_MERGED,
    CONTACT_UNLINKED,
    ContactCreated,
    ContactEdited,
    ContactLinkChanged,
    ContactMerged,
)
from app.contacts.schemas import (
    CompanyLinkResponse,
    ContactDetail,
    ContactSummary,
    OpportunityLinkResponse,
)
from app.core.errors import ApiError
from app.db.clock import database_now
from app.db.models import (
    Actor,
    AggregateType,
    Company,
    Contact,
    ContactCompany,
    ContactCompanyRelation,
    ContactOpportunity,
    ContactOpportunityRole,
    ContactSource,
    DomainEvent,
    Interaction,
    Opportunity,
    RecruitingAction,
    RecruitingActionStatus,
)
from app.db.tenancy import NotFound, require_user_id, resolve_owned
from app.db.versioning import ConcurrencyConflict
from app.events.repository import DomainEventRepository
from app.interactions.schemas import InteractionResponse
from app.opportunities.normalize import collapse_whitespace

MovableRow = ContactCompany | ContactOpportunity | Interaction | RecruitingAction
LIST_LIMIT = 200
DETAIL_INTERACTIONS = 20
OPEN_STATUSES = (RecruitingActionStatus.OPEN, RecruitingActionStatus.SNOOZED)
EMAIL_MATCH = (
    "EXISTS (SELECT 1 FROM jsonb_array_elements(contacts.emails -> 'items') AS item "
    "WHERE lower(item ->> 'address') LIKE :pattern ESCAPE '\\')"
)


def like_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped.lower()}%"


class ContactService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.events = DomainEventRepository(session)

    def list_for_user(
        self,
        *,
        user_id: uuid.UUID,
        query: str | None,
        company_id: uuid.UUID | None,
        opportunity_id: uuid.UUID | None = None,
    ) -> Sequence[Contact]:
        statement = select(Contact).where(Contact.user_id == require_user_id(user_id))
        if query:
            pattern = like_pattern(collapse_whitespace(query))
            statement = statement.where(
                Contact.full_name.ilike(pattern, escape="\\")
                | text(EMAIL_MATCH).bindparams(pattern=pattern)
            )
        if company_id is not None:
            statement = statement.where(
                select(ContactCompany.id)
                .where(
                    ContactCompany.user_id == Contact.user_id,
                    ContactCompany.contact_id == Contact.id,
                    ContactCompany.company_id == company_id,
                )
                .exists()
            )
        if opportunity_id is not None:
            statement = statement.where(
                select(ContactOpportunity.id)
                .where(
                    ContactOpportunity.user_id == Contact.user_id,
                    ContactOpportunity.contact_id == Contact.id,
                    ContactOpportunity.opportunity_id == opportunity_id,
                )
                .exists()
            )
        return self.session.scalars(
            statement.order_by(Contact.created_at.desc(), Contact.id.desc()).limit(LIST_LIMIT)
        ).all()

    def detail(self, *, user_id: uuid.UUID, contact_id: uuid.UUID) -> ContactDetail:
        row = resolve_owned(self.session, Contact, user_id=user_id, id=contact_id)
        companies = self.session.execute(
            select(ContactCompany, Company)
            .join(
                Company,
                and_(
                    Company.user_id == ContactCompany.user_id,
                    Company.id == ContactCompany.company_id,
                ),
            )
            .where(ContactCompany.user_id == user_id, ContactCompany.contact_id == contact_id)
            .order_by(ContactCompany.created_at, ContactCompany.id)
        ).all()
        opportunities = self.session.execute(
            select(ContactOpportunity, Opportunity, Company)
            .join(
                Opportunity,
                and_(
                    Opportunity.user_id == ContactOpportunity.user_id,
                    Opportunity.id == ContactOpportunity.opportunity_id,
                ),
            )
            .outerjoin(
                Company,
                and_(Company.user_id == Opportunity.user_id, Company.id == Opportunity.company_id),
            )
            .where(
                ContactOpportunity.user_id == user_id, ContactOpportunity.contact_id == contact_id
            )
            .order_by(ContactOpportunity.created_at, ContactOpportunity.id)
        ).all()
        interactions = self.session.scalars(
            select(Interaction)
            .where(Interaction.user_id == user_id, Interaction.contact_id == contact_id)
            .order_by(Interaction.occurred_at.desc(), Interaction.id.desc())
            .limit(DETAIL_INTERACTIONS)
        ).all()
        actions = RecruitingActionRepository(self.session).list_filtered(
            user_id=user_id, statuses=OPEN_STATUSES, contact_id=contact_id
        )
        summary = ContactSummary.build(row)
        return ContactDetail(
            **summary.model_dump(),
            linkedin_url=row.linkedin_url,
            notes=row.notes,
            companies=[
                CompanyLinkResponse(
                    company_id=company.id,
                    company_name=collapse_whitespace(company.name),
                    relation=link.relation,
                    title=link.title,
                    is_current=link.is_current,
                )
                for link, company in companies
            ],
            opportunities=[
                OpportunityLinkResponse(
                    opportunity_id=opportunity.id,
                    opportunity_title=opportunity.title,
                    company_name=None if company is None else collapse_whitespace(company.name),
                    role=link.role,
                )
                for link, opportunity, company in opportunities
            ],
            interactions=[InteractionResponse.build(item) for item in interactions],
            actions=[ActionResponse.build(item) for item in actions],
        )

    def create(
        self,
        *,
        user_id: uuid.UUID,
        full_name: str,
        emails: list[str],
        linkedin_url: str | None,
        headline: str | None,
        notes: str,
    ) -> Contact:
        def work() -> Contact:
            self._lock_emails(user_id)
            self._ensure_addresses_free(user_id, emails, except_id=None)
            now = database_now(self.session)
            stored = ContactEmails(
                items=tuple(
                    ContactEmail(address=address, source=EmailSource.MANUAL, added_at=now)
                    for address in emails
                )
            )
            row = Contact(
                user_id=user_id,
                full_name=full_name,
                emails=stored.to_json(),
                linkedin_url=linkedin_url,
                headline=headline,
                notes=notes,
                source=ContactSource.MANUAL,
            )
            self.session.add(row)
            self.session.flush()
            self.events.append(
                user_id=user_id,
                aggregate_type=AggregateType.CONTACT,
                aggregate_id=row.id,
                event_type=CONTACT_CREATED,
                occurred_at=now,
                actor=Actor.USER,
                payload=ContactCreated(
                    contact_id=row.id, source=row.source.value, email_count=len(emails)
                ),
            )
            return row

        return run_in_transaction(self.session, work, commit=True)

    def edit(
        self,
        *,
        user_id: uuid.UUID,
        contact_id: uuid.UUID,
        expected_updated_at: datetime,
        changes: dict[str, Any],
    ) -> Contact:
        def work() -> Contact:
            row = self._lock_expected(user_id, contact_id, expected_updated_at)
            fields: list[str] = []
            for name in ("full_name", "notes"):
                if changes.get(name) is not None and changes[name] != getattr(row, name):
                    setattr(row, name, changes[name])
                    fields.append(name)
            for name in ("linkedin_url", "headline"):
                if name in changes and changes[name] != getattr(row, name):
                    setattr(row, name, changes[name])
                    fields.append(name)
            if changes.get("emails") is not None and self._set_emails(
                user_id, row, changes["emails"]
            ):
                fields.append("emails")
            if fields:
                self.session.flush()
                self.events.append(
                    user_id=user_id,
                    aggregate_type=AggregateType.CONTACT,
                    aggregate_id=row.id,
                    event_type=CONTACT_EDITED,
                    occurred_at=database_now(self.session),
                    actor=Actor.USER,
                    payload=ContactEdited(contact_id=row.id, fields=fields),
                )
            return row

        return run_in_transaction(self.session, work, commit=True)

    def link_company(
        self,
        *,
        user_id: uuid.UUID,
        contact_id: uuid.UUID,
        company_id: uuid.UUID,
        relation: ContactCompanyRelation,
        title: str | None,
        is_current: bool,
    ) -> None:
        def work() -> None:
            resolve_owned(self.session, Contact, user_id=user_id, id=contact_id)
            resolve_owned(self.session, Company, user_id=user_id, id=company_id)
            link = self.session.scalars(
                select(ContactCompany).where(
                    ContactCompany.user_id == user_id,
                    ContactCompany.contact_id == contact_id,
                    ContactCompany.company_id == company_id,
                )
            ).one_or_none()
            if link is None:
                self.session.add(
                    ContactCompany(
                        user_id=user_id,
                        contact_id=contact_id,
                        company_id=company_id,
                        relation=relation,
                        title=title,
                        is_current=is_current,
                    )
                )
            elif (link.relation, link.title, link.is_current) == (relation, title, is_current):
                return
            else:
                link.relation, link.title, link.is_current = relation, title, is_current
            self.session.flush()
            self._link_event(user_id, CONTACT_LINKED, contact_id, "company", company_id, relation)

        run_in_transaction(self.session, work, commit=True)

    def unlink_company(
        self, *, user_id: uuid.UUID, contact_id: uuid.UUID, company_id: uuid.UUID
    ) -> None:
        def work() -> None:
            resolve_owned(self.session, Contact, user_id=user_id, id=contact_id)
            link = self.session.scalars(
                select(ContactCompany).where(
                    ContactCompany.user_id == user_id,
                    ContactCompany.contact_id == contact_id,
                    ContactCompany.company_id == company_id,
                )
            ).one_or_none()
            if link is None:
                raise NotFound("ContactCompany")
            relation = link.relation
            self.session.delete(link)
            self.session.flush()
            self._link_event(user_id, CONTACT_UNLINKED, contact_id, "company", company_id, relation)

        run_in_transaction(self.session, work, commit=True)

    def link_opportunity(
        self,
        *,
        user_id: uuid.UUID,
        contact_id: uuid.UUID,
        opportunity_id: uuid.UUID,
        role: ContactOpportunityRole,
    ) -> None:
        def work() -> None:
            resolve_owned(self.session, Contact, user_id=user_id, id=contact_id)
            resolve_owned(self.session, Opportunity, user_id=user_id, id=opportunity_id)
            existing = self._opportunity_link(user_id, contact_id, opportunity_id, role)
            if existing is not None:
                return
            self.session.add(
                ContactOpportunity(
                    user_id=user_id, contact_id=contact_id, opportunity_id=opportunity_id, role=role
                )
            )
            self.session.flush()
            self._link_event(
                user_id, CONTACT_LINKED, contact_id, "opportunity", opportunity_id, role
            )

        run_in_transaction(self.session, work, commit=True)

    def unlink_opportunity(
        self,
        *,
        user_id: uuid.UUID,
        contact_id: uuid.UUID,
        opportunity_id: uuid.UUID,
        role: ContactOpportunityRole,
    ) -> None:
        def work() -> None:
            resolve_owned(self.session, Contact, user_id=user_id, id=contact_id)
            link = self._opportunity_link(user_id, contact_id, opportunity_id, role)
            if link is None:
                raise NotFound("ContactOpportunity")
            self.session.delete(link)
            self.session.flush()
            self._link_event(
                user_id, CONTACT_UNLINKED, contact_id, "opportunity", opportunity_id, role
            )

        run_in_transaction(self.session, work, commit=True)

    def merge(
        self,
        *,
        user_id: uuid.UUID,
        survivor_id: uuid.UUID,
        merged_id: uuid.UUID,
        expected_survivor_updated_at: datetime,
        expected_merged_updated_at: datetime,
    ) -> Contact:
        if survivor_id == merged_id:
            raise ApiError(409, "cannot_merge_into_self")

        def work() -> Contact:
            for contact_id in (survivor_id, merged_id):
                self._require_present(user_id, contact_id)
            survivor, merged = self._lock_pair(user_id, survivor_id, merged_id)
            if (
                survivor.updated_at != expected_survivor_updated_at
                or merged.updated_at != expected_merged_updated_at
            ):
                raise ConcurrencyConflict("contacts")
            self._lock_emails(user_id)
            self._union_into(survivor, merged)
            moved_links = self._move_links(user_id, survivor_id, merged_id)
            moved_interactions = self._move_rows(user_id, Interaction, survivor_id, merged_id)
            moved_actions = self._move_rows(user_id, RecruitingAction, survivor_id, merged_id)
            survivor.updated_at = func.now()
            self.session.flush()
            self.events.append(
                user_id=user_id,
                aggregate_type=AggregateType.CONTACT,
                aggregate_id=survivor_id,
                event_type=CONTACT_MERGED,
                occurred_at=database_now(self.session),
                actor=Actor.USER,
                payload=ContactMerged(
                    survivor_id=survivor_id,
                    merged_id=merged_id,
                    moved_interactions=moved_interactions,
                    moved_actions=moved_actions,
                    moved_links=moved_links,
                ),
            )
            self.session.execute(
                delete(Contact).where(Contact.user_id == user_id, Contact.id == merged_id)
            )
            self.session.expire_all()
            return resolve_owned(self.session, Contact, user_id=user_id, id=survivor_id)

        return run_in_transaction(self.session, work, commit=True)

    def _require_present(self, user_id: uuid.UUID, contact_id: uuid.UUID) -> None:
        present = self.session.scalars(
            select(Contact.id).where(Contact.user_id == user_id, Contact.id == contact_id)
        ).one_or_none()
        if present is not None:
            return
        merged_away = self.session.scalars(
            select(DomainEvent.id)
            .where(
                DomainEvent.user_id == user_id,
                DomainEvent.aggregate_type == AggregateType.CONTACT,
                DomainEvent.event_type == CONTACT_MERGED,
                DomainEvent.payload["merged_id"].astext == str(contact_id),
            )
            .limit(1)
        ).one_or_none()
        if merged_away is not None:
            raise ApiError(409, "contact_already_merged")
        raise NotFound("Contact")

    def _lock_pair(
        self, user_id: uuid.UUID, survivor_id: uuid.UUID, merged_id: uuid.UUID
    ) -> tuple[Contact, Contact]:
        rows = self.session.scalars(
            select(Contact)
            .where(Contact.user_id == user_id, Contact.id.in_([survivor_id, merged_id]))
            .order_by(Contact.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
        by_id = {row.id: row for row in rows}
        if len(by_id) != 2:
            raise ConcurrencyConflict("contacts")
        return by_id[survivor_id], by_id[merged_id]

    def _lock_expected(
        self, user_id: uuid.UUID, contact_id: uuid.UUID, expected_updated_at: datetime
    ) -> Contact:
        resolve_owned(self.session, Contact, user_id=user_id, id=contact_id)
        row = self.session.scalars(
            select(Contact)
            .where(Contact.user_id == user_id, Contact.id == contact_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one_or_none()
        if row is None or row.updated_at != expected_updated_at:
            raise ConcurrencyConflict("contacts")
        return row

    def _lock_emails(self, user_id: uuid.UUID) -> None:
        self.session.execute(
            select(
                func.pg_advisory_xact_lock(func.hashtextextended(f"contact_emails:{user_id}", 0))
            )
        )

    def _ensure_addresses_free(
        self, user_id: uuid.UUID, addresses: Sequence[str], *, except_id: uuid.UUID | None
    ) -> None:
        for address in addresses:
            statement = select(Contact.id).where(
                Contact.user_id == user_id,
                Contact.emails["items"].contains([{"address": address}]),
            )
            if except_id is not None:
                statement = statement.where(Contact.id != except_id)
            if self.session.scalars(statement.limit(1)).one_or_none() is not None:
                raise ApiError(409, "contact_email_taken")

    def _set_emails(self, user_id: uuid.UUID, row: Contact, desired: list[str]) -> bool:
        current = ContactEmails.from_json(row.emails)
        if desired == current.addresses:
            return False
        self._lock_emails(user_id)
        known = {item.address: item for item in current.items}
        self._ensure_addresses_free(
            user_id, [address for address in desired if address not in known], except_id=row.id
        )
        now = database_now(self.session)
        row.emails = ContactEmails(
            items=tuple(
                known.get(address)
                or ContactEmail(address=address, source=EmailSource.MANUAL, added_at=now)
                for address in desired
            )
        ).to_json()
        return True

    def _union_into(self, survivor: Contact, merged: Contact) -> None:
        kept = ContactEmails.from_json(survivor.emails)
        extra = tuple(
            item
            for item in ContactEmails.from_json(merged.emails).items
            if item.address not in kept.addresses
        )
        if extra:
            survivor.emails = ContactEmails(items=(*kept.items, *extra)).to_json()
        if survivor.linkedin_url is None:
            survivor.linkedin_url = merged.linkedin_url
        if survivor.headline is None:
            survivor.headline = merged.headline
        if not survivor.notes:
            survivor.notes = merged.notes

    def _move_links(self, user_id: uuid.UUID, survivor_id: uuid.UUID, merged_id: uuid.UUID) -> int:
        params = {"user_id": user_id, "survivor_id": survivor_id, "merged_id": merged_id}
        self.session.execute(
            text(
                "DELETE FROM contact_companies AS merged_link "
                "WHERE merged_link.user_id = :user_id AND merged_link.contact_id = :merged_id "
                "AND EXISTS (SELECT 1 FROM contact_companies AS kept "
                "WHERE kept.user_id = :user_id AND kept.contact_id = :survivor_id "
                "AND kept.company_id = merged_link.company_id)"
            ),
            params,
        )
        self.session.execute(
            text(
                "DELETE FROM contact_opportunities AS merged_link "
                "WHERE merged_link.user_id = :user_id AND merged_link.contact_id = :merged_id "
                "AND EXISTS (SELECT 1 FROM contact_opportunities AS kept "
                "WHERE kept.user_id = :user_id AND kept.contact_id = :survivor_id "
                "AND kept.opportunity_id = merged_link.opportunity_id "
                "AND kept.role = merged_link.role)"
            ),
            params,
        )
        return self._move_rows(user_id, ContactCompany, survivor_id, merged_id) + (
            self._move_rows(user_id, ContactOpportunity, survivor_id, merged_id)
        )

    def _move_rows(
        self,
        user_id: uuid.UUID,
        model: type[MovableRow],
        survivor_id: uuid.UUID,
        merged_id: uuid.UUID,
    ) -> int:
        result = self.session.execute(
            update(model)
            .where(model.user_id == user_id, model.contact_id == merged_id)
            .values(contact_id=survivor_id)
            .execution_options(synchronize_session=False)
        )
        return cast(CursorResult[Any], result).rowcount

    def _opportunity_link(
        self,
        user_id: uuid.UUID,
        contact_id: uuid.UUID,
        opportunity_id: uuid.UUID,
        role: ContactOpportunityRole,
    ) -> ContactOpportunity | None:
        return self.session.scalars(
            select(ContactOpportunity).where(
                ContactOpportunity.user_id == user_id,
                ContactOpportunity.contact_id == contact_id,
                ContactOpportunity.opportunity_id == opportunity_id,
                ContactOpportunity.role == role,
            )
        ).one_or_none()

    def _link_event(
        self,
        user_id: uuid.UUID,
        event_type: str,
        contact_id: uuid.UUID,
        target_type: str,
        target_id: uuid.UUID,
        role: ContactCompanyRelation | ContactOpportunityRole,
    ) -> None:
        self.events.append(
            user_id=user_id,
            aggregate_type=AggregateType.CONTACT,
            aggregate_id=contact_id,
            event_type=event_type,
            occurred_at=database_now(self.session),
            actor=Actor.USER,
            payload=ContactLinkChanged(
                contact_id=contact_id,
                target_type=target_type,
                target_id=target_id,
                role=role.value,
            ),
        )
