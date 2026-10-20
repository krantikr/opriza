"""Connecting a real desk: the go-live path, with Tally faked at the HTTP seam.

`TallyXmlSource.pull` is the only thing replaced - it hands back the sample
books - so everything from the sync onwards runs exactly as it would against
a customer's TallyPrime.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
from app.core.tenancy import bind_session
from app.kb import runtime
from app.kb.connect import connect_desk, set_role
from app.kb.models import KbBusiness, KbCustomerProfile, KbMember, KbSyncRun, KbTask
from app.kb.sources.base import SourceUnavailable, TallyBatch
from app.kb.sources.mock import MockTallySource
from app.kb.sources.tally_xml import TallyXmlSource
from app.models import Organisation, User, UserRole


@pytest.fixture()
def Session(engine):  # noqa: N802
    os.environ["AGENT_BRAIN"] = "rules"
    os.environ["AGENT_CHANNEL"] = "outbox"
    runtime.reset_graph_cache()
    maker = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    s = maker()
    bind_session(s, None, super_admin=True)
    names = ", ".join(f'"{t}"' for t in Base.metadata.tables)
    s.execute(text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE"))
    org = Organisation(slug="acme-traders", name="Acme Traders", timezone="Asia/Kolkata")
    s.add(org)
    s.flush()
    s.add_all(
        [
            User(organisation_id=org.id, name="Asha Owner", email="asha@acme.in", role=UserRole.OWNER),
            User(organisation_id=org.id, name="Ravi Clerk", email="ravi@acme.in", role=UserRole.MEMBER),
        ]
    )
    s.commit()
    s.close()
    yield maker
    # A failed test can leave its session mid-transaction; close it so the next
    # test's TRUNCATE isn't left waiting on its locks.
    for x in OPEN:
        x.rollback()
        x.close()
    OPEN.clear()


OPEN: list = []


def admin(maker):
    s = maker()
    bind_session(s, None, super_admin=True)
    OPEN.append(s)
    return s


def test_connect_loads_books_and_runs_agents(Session, monkeypatch):
    books = MockTallySource("patel-build-mart")

    def pull(self, since_alter_id=0):
        assert self.url in ("http://192.168.1.20:9000", "http://10.0.0.5:9000")
        return books.pull(0) if since_alter_id == 0 else TallyBatch()

    monkeypatch.setattr(TallyXmlSource, "pull", pull)
    s = admin(Session)
    out = connect_desk(s, "acme-traders", "http://192.168.1.20:9000/", city="Ahmedabad", language="Hinglish")
    s.commit()
    assert out["sync"] == "ok" and out["members_added"] == 2 and out["objects"] > 1000

    biz = s.scalars(select(KbBusiness)).one()
    assert biz.source == "tally_xml" and biz.source_url == "http://192.168.1.20:9000" and biz.as_of is None
    roles = dict(
        s.execute(select(User.email, KbMember.desk_role).join(KbMember, KbMember.user_id == User.id)).all()
    )
    assert roles == {"asha@acme.in": "owner", "ravi@acme.in": "sales"}
    # Facts were built from the books and the agents produced work from them.
    assert s.scalar(select(func.count()).select_from(KbCustomerProfile)) > 20
    assert s.scalar(select(func.count()).select_from(KbTask)) > 0

    # A second connect only updates the address; nothing is duplicated.
    out2 = connect_desk(s, "acme-traders", "http://10.0.0.5:9000", run_agents=False)
    s.commit()
    assert out2["members_added"] == 0 and s.scalar(select(func.count()).select_from(KbBusiness)) == 1

    set_role(s, "acme-traders", "ravi@acme.in", "accounts")
    s.commit()
    assert (
        s.scalar(
            select(KbMember.desk_role)
            .join(User, User.id == KbMember.user_id)
            .where(User.email == "ravi@acme.in")
        )
        == "accounts"
    )
    s.close()


def test_connect_with_tally_offline_keeps_the_desk(Session, monkeypatch):
    def pull(self, since_alter_id=0):
        raise SourceUnavailable("Tally is not reachable at http://192.168.1.20:9000")

    monkeypatch.setattr(TallyXmlSource, "pull", pull)
    s = admin(Session)
    out = connect_desk(s, "acme-traders", "http://192.168.1.20:9000")
    s.commit()
    assert out["sync"] == "failed" and "not reachable" in out["error"]
    assert s.scalars(select(KbBusiness)).one().source == "tally_xml"
    assert s.scalars(select(KbSyncRun)).one().status == "failed"
    s.close()


def test_connect_refuses_bad_input(Session):
    s = admin(Session)
    with pytest.raises(ValueError, match="No organisation"):
        connect_desk(s, "nobody", "http://x:9000")
    with pytest.raises(ValueError, match="http"):
        connect_desk(s, "acme-traders", "192.168.1.20:9000")
    with pytest.raises(ValueError, match="Desk role"):
        set_role(s, "acme-traders", "ravi@acme.in", "boss")
    s.close()
