import enum
from datetime import date, datetime, time

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, Enum, ForeignKey, Index, Integer,
    String, Text, Time, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ---------- enums (stored as native PostgreSQL enum types) ----------

class Role(str, enum.Enum):
    recipient = "recipient"                  # the senior
    primary_caregiver = "primary_caregiver"  # manages the circle
    caregiver = "caregiver"                  # family member who can view and confirm


class DoseStatus(str, enum.Enum):
    pending = "pending"
    taken = "taken"
    missed = "missed"
    skipped = "skipped"


class AppointmentKind(str, enum.Enum):
    doctor_visit = "doctor_visit"
    checkup = "checkup"
    lab_test = "lab_test"
    other = "other"


class AppointmentStatus(str, enum.Enum):
    scheduled = "scheduled"
    completed = "completed"
    cancelled = "cancelled"


# ---------- people and circles ----------

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Circle(Base):
    """A family group around one senior. Doses are generated in the circle's timezone."""

    __tablename__ = "circles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    members: Mapped[list["CircleMember"]] = relationship(back_populates="circle", cascade="all, delete-orphan")


class CircleMember(Base):
    """Which user belongs to which circle, and with what role (composite primary key)."""

    __tablename__ = "circle_members"

    circle_id: Mapped[int] = mapped_column(ForeignKey("circles.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[Role] = mapped_column(Enum(Role, name="member_role"))

    circle: Mapped[Circle] = relationship(back_populates="members")
    user: Mapped[User] = relationship()


# ---------- medicines and doses ----------

class Medication(Base):
    __tablename__ = "medications"

    id: Mapped[int] = mapped_column(primary_key=True)
    circle_id: Mapped[int] = mapped_column(ForeignKey("circles.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    dosage: Mapped[str] = mapped_column(String(120), default="")
    instructions: Mapped[str] = mapped_column(Text, default="")
    pills_remaining: Mapped[int | None] = mapped_column(Integer, nullable=True)
    refill_threshold: Mapped[int] = mapped_column(Integer, default=5)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    schedules: Mapped[list["Schedule"]] = relationship(back_populates="medication", cascade="all, delete-orphan")


class Schedule(Base):
    """When a medicine is taken: times of day and weekdays (0=Mon .. 6=Sun, empty = every day)."""

    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    medication_id: Mapped[int] = mapped_column(ForeignKey("medications.id", ondelete="CASCADE"), index=True)
    times_of_day: Mapped[list[time]] = mapped_column(ARRAY(Time))
    days_of_week: Mapped[list[int]] = mapped_column(ARRAY(Integer), default=list)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    medication: Mapped[Medication] = relationship(back_populates="schedules")


class DoseEvent(Base):
    """One concrete dose to be taken at one moment. The worker escalates unconfirmed ones."""

    __tablename__ = "dose_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int] = mapped_column(ForeignKey("schedules.id", ondelete="CASCADE"))
    medication_id: Mapped[int] = mapped_column(ForeignKey("medications.id", ondelete="CASCADE"))
    circle_id: Mapped[int] = mapped_column(ForeignKey("circles.id", ondelete="CASCADE"), index=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[DoseStatus] = mapped_column(Enum(DoseStatus, name="dose_status"), default=DoseStatus.pending)
    taken_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    taken_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    escalation_level: Mapped[int] = mapped_column(Integer, default=0)  # escalation steps already performed
    next_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    medication: Mapped[Medication] = relationship()

    __table_args__ = (
        # makes dose generation idempotent: the same dose can never be inserted twice
        UniqueConstraint("schedule_id", "scheduled_at", name="uq_dose_schedule_time"),
        # the worker's "what is due?" query
        Index("ix_dose_due", "status", "next_action_at"),
        Index("ix_dose_circle_time", "circle_id", "scheduled_at"),
    )


# ---------- doctors and appointments ----------

class Doctor(Base):
    __tablename__ = "doctors"

    id: Mapped[int] = mapped_column(primary_key=True)
    circle_id: Mapped[int] = mapped_column(ForeignKey("circles.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    specialty: Mapped[str] = mapped_column(String(120), default="")
    clinic: Mapped[str] = mapped_column(String(160), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")


class Appointment(Base):
    """A doctor visit, checkup or lab test. recurrence_months makes it a regular checkup."""

    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(primary_key=True)
    circle_id: Mapped[int] = mapped_column(ForeignKey("circles.id", ondelete="CASCADE"), index=True)
    doctor_id: Mapped[int | None] = mapped_column(ForeignKey("doctors.id", ondelete="SET NULL"), nullable=True)
    kind: Mapped[AppointmentKind] = mapped_column(
        Enum(AppointmentKind, name="appointment_kind"), default=AppointmentKind.doctor_visit
    )
    title: Mapped[str] = mapped_column(String(160))
    location: Mapped[str] = mapped_column(String(200), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[AppointmentStatus] = mapped_column(
        Enum(AppointmentStatus, name="appointment_status"), default=AppointmentStatus.scheduled
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recurrence_months: Mapped[int | None] = mapped_column(Integer, nullable=True)  # None = one-off
    reminder_level: Mapped[int] = mapped_column(Integer, default=0)  # reminders already sent
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    doctor: Mapped[Doctor | None] = relationship()

    __table_args__ = (
        CheckConstraint(
            "recurrence_months IS NULL OR (recurrence_months BETWEEN 1 AND 60)", name="ck_recurrence_range"
        ),
        Index("ix_appt_circle_start", "circle_id", "starts_at"),
        Index("ix_appt_status_start", "status", "starts_at"),
    )


# ---------- notifications, devices, audit ----------

class Notification(Base):
    """In-app alert feed and a record of every alert the system sent."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    dose_event_id: Mapped[int | None] = mapped_column(ForeignKey("dose_events.id", ondelete="SET NULL"), nullable=True)
    type: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(String(300))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)


class PushSubscription(Base):
    """A device token for remote push (used once the app runs as a development build)."""

    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    keys: Mapped[dict] = mapped_column(JSONB)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(60))
    entity: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())