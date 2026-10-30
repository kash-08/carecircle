from datetime import datetime, time, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import engine
from app.models import (
    Appointment, Base, Circle, CircleMember, Doctor, DoseEvent, DoseStatus, Medication, Role, Schedule, User,
)

NOW = datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module", autouse=True)
def tables():
    Base.metadata.create_all(engine)


@pytest.fixture()
def db():
    """Every test runs inside a transaction that is rolled back, so the real tables stay clean."""
    conn = engine.connect()
    trans = conn.begin()
    session = Session(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    trans.rollback()
    conn.close()


def make_user(db, email="a@example.com"):
    u = User(name="A", email=email, password_hash="x")
    db.add(u)
    db.flush()
    return u


def make_circle(db, user):
    c = Circle(name="Mom", created_by=user.id)
    db.add(c)
    db.flush()
    db.add(CircleMember(circle_id=c.id, user_id=user.id, role=Role.primary_caregiver))
    db.flush()
    return c


def test_circle_with_member_and_defaults(db):
    u = make_user(db)
    c = make_circle(db, u)
    assert c.timezone == "Asia/Kolkata"
    assert db.get(CircleMember, (c.id, u.id)).role == Role.primary_caregiver


def test_email_must_be_unique(db):
    make_user(db, "dup@example.com")
    with pytest.raises(IntegrityError):
        make_user(db, "dup@example.com")


def test_schedule_arrays_round_trip(db):
    c = make_circle(db, make_user(db))
    med = Medication(circle_id=c.id, name="Metformin")
    med.schedules.append(Schedule(times_of_day=[time(8, 0), time(20, 0)], days_of_week=[0, 2, 4], start_date=NOW.date()))
    db.add(med)
    db.flush()
    s = db.scalar(select(Schedule).where(Schedule.medication_id == med.id))
    assert s.times_of_day == [time(8, 0), time(20, 0)] and s.days_of_week == [0, 2, 4]


def test_same_dose_cannot_be_inserted_twice(db):
    c = make_circle(db, make_user(db))
    med = Medication(circle_id=c.id, name="Aspirin")
    med.schedules.append(Schedule(times_of_day=[time(8, 0)], start_date=NOW.date()))
    db.add(med)
    db.flush()
    sched = med.schedules[0]
    db.add(DoseEvent(schedule_id=sched.id, medication_id=med.id, circle_id=c.id, scheduled_at=NOW))
    db.flush()
    db.add(DoseEvent(schedule_id=sched.id, medication_id=med.id, circle_id=c.id, scheduled_at=NOW))
    with pytest.raises(IntegrityError):
        db.flush()


def test_dose_defaults(db):
    c = make_circle(db, make_user(db))
    med = Medication(circle_id=c.id, name="X")
    med.schedules.append(Schedule(times_of_day=[time(9, 0)], start_date=NOW.date()))
    db.add(med)
    db.flush()
    d = DoseEvent(schedule_id=med.schedules[0].id, medication_id=med.id, circle_id=c.id, scheduled_at=NOW)
    db.add(d)
    db.flush()
    assert d.status == DoseStatus.pending and d.escalation_level == 0


def test_appointment_recurrence_is_validated(db):
    c = make_circle(db, make_user(db))
    doc = Doctor(circle_id=c.id, name="Dr. Rao", specialty="Cardiology")
    db.add(doc)
    db.flush()
    ok = Appointment(circle_id=c.id, doctor_id=doc.id, title="BP check", starts_at=NOW, recurrence_months=3)
    db.add(ok)
    db.flush()
    assert ok.status.value == "scheduled" and ok.reminder_level == 0
    db.add(Appointment(circle_id=c.id, title="Bad", starts_at=NOW, recurrence_months=0))
    with pytest.raises(IntegrityError):
        db.flush()


def test_deleting_a_circle_removes_its_data(db):
    c = make_circle(db, make_user(db))
    db.add(Medication(circle_id=c.id, name="Gone soon"))
    db.add(Doctor(circle_id=c.id, name="Dr. X"))
    db.flush()
    db.delete(c)
    db.flush()
    assert db.scalar(select(Medication).where(Medication.circle_id == c.id)) is None
    assert db.scalar(select(Doctor).where(Doctor.circle_id == c.id)) is None