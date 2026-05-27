from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="user")  # user | technician | admin
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    tickets_created = relationship("Ticket", foreign_keys="Ticket.created_by_id", back_populates="creator")
    tickets_assigned = relationship("Ticket", foreign_keys="Ticket.assigned_to_id", back_populates="assignee")
    comments = relationship("Comment", back_populates="author")
    history_entries = relationship("TicketHistory", back_populates="changed_by")


class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    type = Column(String, default="demande")       # demande | incident
    category = Column(String, default="autre")     # materiel | logiciel | reseau | securite | autre
    priority = Column(String, default="normale")   # faible | normale | haute | critique
    status = Column(String, default="ouvert")      # ouvert | en_cours | resolu | ferme
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    assigned_to_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    creator = relationship("User", foreign_keys=[created_by_id], back_populates="tickets_created")
    assignee = relationship("User", foreign_keys=[assigned_to_id], back_populates="tickets_assigned")
    comments = relationship("Comment", back_populates="ticket", cascade="all, delete-orphan", order_by="Comment.created_at")
    history = relationship("TicketHistory", back_populates="ticket", cascade="all, delete-orphan", order_by="TicketHistory.changed_at")


class Comment(Base):
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    ticket = relationship("Ticket", back_populates="comments")
    author = relationship("User", back_populates="comments")


class KBArticle(Base):
    __tablename__ = "kb_articles"

    id         = Column(Integer, primary_key=True, index=True)
    title      = Column(String, nullable=False)
    content    = Column(Text, nullable=False)
    ticket_type = Column(String, nullable=True)
    category   = Column(String, nullable=True)
    author_id  = Column(Integer, ForeignKey("users.id"), nullable=False)
    views      = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    author = relationship("User")


class TicketTemplate(Base):
    __tablename__ = "ticket_templates"

    id          = Column(Integer, primary_key=True, index=True)
    name        = Column(String, nullable=False)
    title       = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    type        = Column(String, default="demande")
    category    = Column(String, default="autre")
    priority    = Column(String, default="normale")
    author_id   = Column(Integer, ForeignKey("users.id"), nullable=False)
    usage_count = Column(Integer, default=0)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), onupdate=func.now())

    author = relationship("User")


class ProcessTemplate(Base):
    __tablename__ = "process_templates"

    id          = Column(Integer, primary_key=True, index=True)
    name        = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    ticket_type = Column(String, nullable=True)
    author_id   = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    author = relationship("User")
    steps  = relationship("ProcessTemplateStep", order_by="ProcessTemplateStep.order",
                          cascade="all, delete-orphan")


class ProcessTemplateStep(Base):
    __tablename__ = "process_template_steps"

    id          = Column(Integer, primary_key=True, index=True)
    template_id = Column(Integer, ForeignKey("process_templates.id"), nullable=False)
    order       = Column(Integer, nullable=False)
    name        = Column(String, nullable=False)
    description = Column(Text, nullable=True)

    template = relationship("ProcessTemplate", back_populates="steps")


class TicketProcess(Base):
    __tablename__ = "ticket_processes"

    id         = Column(Integer, primary_key=True, index=True)
    ticket_id  = Column(Integer, ForeignKey("tickets.id"), unique=True, nullable=False)
    name       = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    ticket = relationship("Ticket")
    tasks  = relationship("TicketProcessTask", order_by="TicketProcessTask.order",
                          cascade="all, delete-orphan")


class TicketProcessTask(Base):
    __tablename__ = "ticket_process_tasks"

    id              = Column(Integer, primary_key=True, index=True)
    process_id      = Column(Integer, ForeignKey("ticket_processes.id"), nullable=False)
    order           = Column(Integer, nullable=False)
    name            = Column(String, nullable=False)
    description     = Column(Text, nullable=True)
    status          = Column(String, default="en_attente")  # en_attente | en_cours | fait
    assigned_to_id  = Column(Integer, ForeignKey("users.id"), nullable=True)
    completed_at    = Column(DateTime(timezone=True), nullable=True)
    completed_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    process      = relationship("TicketProcess", back_populates="tasks")
    assignee     = relationship("User", foreign_keys=[assigned_to_id])
    completed_by = relationship("User", foreign_keys=[completed_by_id])


class TicketHistory(Base):
    __tablename__ = "ticket_history"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    field_changed = Column(String, nullable=False)
    old_value = Column(String, nullable=True)
    new_value = Column(String, nullable=True)
    changed_at = Column(DateTime(timezone=True), server_default=func.now())

    ticket = relationship("Ticket", back_populates="history")
    changed_by = relationship("User", back_populates="history_entries")
