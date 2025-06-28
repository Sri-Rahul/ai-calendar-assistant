from pydantic import BaseModel
from typing import Optional, List, Dict, Any, Union
from datetime import datetime
from enum import Enum

class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"

class ChatMessage(BaseModel):
    role: MessageRole
    content: str
    timestamp: Optional[datetime] = None

class BookingRequest(BaseModel):
    title: str
    start_time: datetime
    end_time: datetime
    description: Optional[str] = None
    attendees: Optional[List[str]] = []

class CalendarEvent(BaseModel):
    id: str
    title: str
    start_time: datetime
    end_time: datetime
    description: Optional[str] = None

class ConversationState(BaseModel):
    messages: List[ChatMessage] = []
    user_intent: Optional[str] = None
    extracted_entities: Dict[str, Any] = {}
    calendar_availability: Optional[List[Dict]] = None
    current_booking: Optional[Dict] = None  # Changed from BookingRequest to Dict
    conversation_stage: str = "initial"
    user_preferences: Dict[str, Any] = {}

class ChatResponse(BaseModel):
    message: str
    booking_data: Optional[Dict] = None
    suggested_times: Optional[List[str]] = None
    requires_confirmation: bool = False
