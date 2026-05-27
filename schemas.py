from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime


class UserOut(BaseModel):
    id: int
    username: str
    email: str
    role: str
    created_at: datetime

    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    username: str
    email: str
    password: str


class RoleUpdate(BaseModel):
    role: str


class CommentCreate(BaseModel):
    content: str


class CommentOut(BaseModel):
    id: int
    ticket_id: int
    user_id: int
    content: str
    created_at: datetime
    author: UserOut

    model_config = {"from_attributes": True}


class HistoryOut(BaseModel):
    id: int
    field_changed: str
    old_value: Optional[str]
    new_value: Optional[str]
    changed_at: datetime
    changed_by: UserOut

    model_config = {"from_attributes": True}


class TicketCreate(BaseModel):
    title: str
    description: str
    type: str = "demande"
    category: str = "autre"
    priority: str = "normale"


class TicketUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    category: Optional[str] = None
    assigned_to_id: Optional[int] = None


class TicketListOut(BaseModel):
    id: int
    title: str
    type: str
    category: str
    priority: str
    status: str
    created_by_id: int
    assigned_to_id: Optional[int]
    created_at: datetime
    updated_at: Optional[datetime]
    creator: UserOut
    assignee: Optional[UserOut]

    model_config = {"from_attributes": True}


class TicketDetailOut(TicketListOut):
    description: str
    comments: List[CommentOut] = []
    history: List[HistoryOut] = []


class Token(BaseModel):
    access_token: str
    token_type: str
    user: UserOut


class KBArticleCreate(BaseModel):
    title: str
    content: str
    ticket_type: Optional[str] = None
    category: Optional[str] = None


class KBArticleUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    ticket_type: Optional[str] = None
    category: Optional[str] = None


class KBArticleOut(BaseModel):
    id: int
    title: str
    content: str
    ticket_type: Optional[str]
    category: Optional[str]
    author: UserOut
    views: int
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = {"from_attributes": True}


class TicketTemplateCreate(BaseModel):
    name: str
    title: str
    description: str
    type: str = "demande"
    category: str = "autre"
    priority: str = "normale"


class TicketTemplateUpdate(BaseModel):
    name: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[str] = None


class TicketTemplateOut(BaseModel):
    id: int
    name: str
    title: str
    description: str
    type: str
    category: str
    priority: str
    author: UserOut
    usage_count: int
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = {"from_attributes": True}


class ProcessTemplateStepCreate(BaseModel):
    order: int
    name: str
    description: Optional[str] = None


class ProcessTemplateCreate(BaseModel):
    name: str
    description: Optional[str] = None
    ticket_type: Optional[str] = None
    steps: List["ProcessTemplateStepCreate"] = []


class ProcessTemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    ticket_type: Optional[str] = None
    steps: Optional[List["ProcessTemplateStepCreate"]] = None


class ProcessTemplateStepOut(BaseModel):
    id: int
    order: int
    name: str
    description: Optional[str]

    model_config = {"from_attributes": True}


class ProcessTemplateOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    ticket_type: Optional[str]
    author: UserOut
    created_at: datetime
    steps: List[ProcessTemplateStepOut] = []

    model_config = {"from_attributes": True}


class TicketProcessTaskOut(BaseModel):
    id: int
    order: int
    name: str
    description: Optional[str]
    status: str
    assignee: Optional[UserOut]
    completed_at: Optional[datetime]
    completed_by: Optional[UserOut]

    model_config = {"from_attributes": True}


class TicketProcessOut(BaseModel):
    id: int
    ticket_id: int
    name: str
    created_at: datetime
    tasks: List[TicketProcessTaskOut] = []

    model_config = {"from_attributes": True}


class AttachProcessPayload(BaseModel):
    template_id: Optional[int] = None
    name: Optional[str] = None
    steps: Optional[List[ProcessTemplateStepCreate]] = None


class UpdateTaskPayload(BaseModel):
    status: str
    assigned_to_id: Optional[int] = None


class StatsOut(BaseModel):
    total: int
    ouvert: int
    en_cours: int
    resolu: int
    ferme: int
    incidents: int
    demandes: int
