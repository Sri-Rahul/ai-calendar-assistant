import pytz
def get_ist_time() -> datetime:
    """Get current time in IST"""
    ist_tz = pytz.timezone('Asia/Kolkata')
    utc_now = datetime.utcnow()
    return utc_now.replace(tzinfo=pytz.UTC).astimezone(ist_tz).replace(tzinfo=None)
from langgraph.graph import StateGraph, END
from typing import Dict, Any, List
from datetime import datetime, timedelta
import asyncio
import traceback
import re
import pytz

from ..models.schemas import ConversationState, BookingRequest, ChatMessage, MessageRole
from ..services.calendar_service import GoogleCalendarService
from ..services.ai_service import AIService

def parse_duration(duration_str: str) -> timedelta:
    """Parse duration string to timedelta"""
    if not duration_str:
        return timedelta(hours=1)
    
    duration_str = duration_str.lower().strip()
    
    # Handle common phrases
    if 'half' in duration_str and ('hour' in duration_str or 'hr' in duration_str):
        return timedelta(minutes=30)
    if 'an hour' in duration_str or duration_str == 'hour':
        return timedelta(hours=1)
    if 'quarter' in duration_str and ('hour' in duration_str or 'hr' in duration_str):
        return timedelta(minutes=15)
    
    # Extract numeric values
    if 'hour' in duration_str or 'hr' in duration_str:
        match = re.search(r'(\d+(?:\.\d+)?)', duration_str)
        if match:
            hours = float(match.group(1))
            return timedelta(hours=hours)
        else:
            return timedelta(hours=1)
    
    if 'minute' in duration_str or 'min' in duration_str:
        match = re.search(r'(\d+)', duration_str)
        if match:
            minutes = int(match.group(1))
            return timedelta(minutes=minutes)
        else:
            return timedelta(minutes=30)
    
    # Handle text numbers
    if 'thirty' in duration_str:
        return timedelta(minutes=30)
    if 'fifteen' in duration_str:
        return timedelta(minutes=15)
    if 'two hour' in duration_str:
        return timedelta(hours=2)
    
    return timedelta(hours=1)

class CalendarBookingAgent:
    def __init__(self):
        self.calendar_service = GoogleCalendarService()
        try:
            self.calendar_service.authenticate()
            print("✅ Calendar service authenticated successfully")
        except Exception as e:
            print(f"⚠️ Calendar service authentication failed: {e}")
        
        self.ai_service = AIService()
        self.graph = self._create_graph()

    def _create_graph(self) -> StateGraph:
        """Create simplified workflow"""
        workflow = StateGraph(dict)
        
        # Add nodes
        workflow.add_node("extract_info", self._extract_info_node)
        workflow.add_node("ask_title", self._ask_title_node)
        workflow.add_node("ask_duration", self._ask_duration_node)
        workflow.add_node("ask_specific_day", self._ask_specific_day_node)
        workflow.add_node("check_availability", self._check_availability_node)
        workflow.add_node("handle_conflict", self._handle_conflict_node)
        workflow.add_node("ask_attendees", self._ask_attendees_node)
        workflow.add_node("confirm_booking", self._confirm_booking_node)
        workflow.add_node("create_booking", self._create_booking_node)
        workflow.add_node("generate_response", self._generate_response_node)
        
        # Set entry point
        workflow.set_entry_point("extract_info")
        
        # Add conditional routing
        workflow.add_conditional_edges(
            "extract_info",
            self._route_next_step,
            {
                "ask_title": "ask_title",
                "ask_duration": "ask_duration",
                "ask_specific_day": "ask_specific_day",
                "check_availability": "check_availability",
                "handle_conflict": "handle_conflict",
                "ask_attendees": "ask_attendees",
                "confirm_booking": "confirm_booking",
                "create_booking": "create_booking",
                "generate_response": "generate_response",
                "reset_conversation": "generate_response"
            }
        )
        
        # All nodes lead to response generation
        workflow.add_edge("ask_title", "generate_response")
        workflow.add_edge("ask_duration", "generate_response")
        workflow.add_edge("ask_specific_day", "generate_response")
        workflow.add_edge("check_availability", "generate_response")
        workflow.add_edge("handle_conflict", "generate_response")
        workflow.add_edge("ask_attendees", "generate_response")
        workflow.add_edge("confirm_booking", "generate_response")
        workflow.add_edge("create_booking", "generate_response")
        workflow.add_edge("generate_response", END)
        
        return workflow.compile()

    def _conversation_state_to_dict(self, state: ConversationState) -> Dict:
        """Convert ConversationState to dict"""
        return {
            "messages": [
                {
                    "role": msg.role.value if hasattr(msg.role, 'value') else str(msg.role),
                    "content": msg.content,
                    "timestamp": msg.timestamp.isoformat() if msg.timestamp else None
                }
                for msg in state.messages
            ],
            "user_intent": state.user_intent,
            "extracted_entities": state.extracted_entities,
            "calendar_availability": state.calendar_availability,
            "current_booking": state.current_booking,
            "conversation_stage": state.conversation_stage,
            "user_preferences": state.user_preferences
        }

    def _dict_to_conversation_state(self, state_dict: Dict) -> ConversationState:
        """Convert dict back to ConversationState"""
        try:
            messages = []
            for msg_dict in state_dict.get("messages", []):
                try:
                    role = MessageRole(msg_dict["role"]) if isinstance(msg_dict["role"], str) else msg_dict["role"]
                    timestamp = datetime.fromisoformat(msg_dict["timestamp"]) if msg_dict.get("timestamp") else None
                    message = ChatMessage(
                        role=role,
                        content=msg_dict["content"],
                        timestamp=timestamp
                    )
                    messages.append(message)
                except Exception as e:
                    print(f"⚠️ Error converting message: {e}")
                    continue

            return ConversationState(
                messages=messages,
                user_intent=state_dict.get("user_intent"),
                extracted_entities=state_dict.get("extracted_entities", {}),
                calendar_availability=state_dict.get("calendar_availability"),
                current_booking=state_dict.get("current_booking"),
                conversation_stage=state_dict.get("conversation_stage", "initial"),
                user_preferences=state_dict.get("user_preferences", {})
            )
        except Exception as e:
            print(f"❌ Error converting dict to ConversationState: {e}")
            return ConversationState()

    def _handle_generic_time_defaults(self, entities: Dict) -> Dict:
        """Handle generic times with dedicated default times"""
        time_mentioned = entities.get("time", "").lower()
        
        # Map generic times to specific times
        generic_time_mapping = {
            "afternoon": "2:00 PM",
            "morning": "10:00 AM", 
            "evening": "6:00 PM",
            "night": "8:00 PM"
        }
        
        # Check if user mentioned a generic time
        for generic_time, default_time in generic_time_mapping.items():
            if generic_time in time_mentioned:
                print(f"🕐 Generic time '{generic_time}' detected, defaulting to {default_time}")
                entities["default_time"] = default_time
                entities["generic_time_used"] = generic_time
                entities["requested_time"] = default_time
                break
        
        return entities

    async def _extract_info_node(self, state: Dict) -> Dict:
        """Extract and consolidate information from user message"""
        try:
            messages = state.get("messages", [])
            if not messages:
                return state

            last_message = messages[-1]["content"]
            print(f"🔍 Extracting info from: {last_message[:50]}...")

            # Check if this is a new booking request after a completed booking
            if self._is_new_booking_request(last_message, state):
                print("🔄 Detected new booking request, resetting conversation...")
                state = self._reset_conversation_state(state)

            # Get current entities
            entities = state.get("extracted_entities", {})

            # Extract new information from the latest message
            analysis = await self.ai_service.extract_intent_and_entities(last_message)
            new_entities = analysis.get("entities", {})
            intent = analysis.get("intent", "")

            # Handle confirmation
            if intent == "confirm_booking" or self._is_confirmation(last_message):
                state["user_intent"] = "confirm_booking"
                return state

            # FIXED: Handle cancellation/rejection
            if intent == "reject" or self._is_cancellation(last_message):
                print("❌ User cancelled booking")
                state["user_intent"] = "cancel_booking"
                state["conversation_stage"] = "booking_cancelled"
                # Reset all entities for fresh start
                state["extracted_entities"] = {}
                state["calendar_availability"] = None
                state["current_booking"] = None
                state["booking_summary"] = None
                return state

            # Handle time selection (when user selects from available slots)
            if self._is_time_selection(last_message, state.get("conversation_stage")):
                selected_time = self._extract_selected_time(last_message)
                if selected_time:
                    entities["selected_time"] = selected_time
                    entities["time_confirmed"] = True
                    print(f"✅ Time selected: {selected_time}")

            # Handle day selection for weekly bookings
            if self._is_day_selection(last_message, state.get("conversation_stage")):
                selected_day = self._extract_selected_day(last_message)
                if selected_day:
                    entities["selected_day"] = selected_day
                    entities["day_confirmed"] = True
                    entities["parsed_date"] = self._parse_specific_day(selected_day)
                    print(f"✅ Day selected: {selected_day}")

            # Enhanced time range extraction for "3-5 PM" type requests
            time_range_info = self._extract_time_range(last_message)
            if time_range_info:
                for key, value in time_range_info.items():
                    if value:
                        new_entities[key] = value
                        print(f"🕐 Extracted time range - {key}: {value}")

            # Better email and time extraction from combined messages
            combined_info = self._extract_combined_info(last_message)
            if combined_info:
                for key, value in combined_info.items():
                    if value:
                        new_entities[key] = value
                        print(f"🔗 Extracted from combined message - {key}: {value}")

            # Merge new information
            for key, value in new_entities.items():
                if value and str(value).strip() and str(value) not in ["null", "None", ""]:
                    if key == "title":
                        if isinstance(value, list):
                            entities[key] = " ".join(value).title()
                        else:
                            entities[key] = str(value).title()
                        print(f"📝 Updated title: {entities[key]}")
                    elif key == "duration":
                        entities[key] = str(value)
                        print(f"⏱️ Updated duration: {entities[key]}")
                    elif key == "date":
                        entities[key] = str(value)
                        entities["parsed_date"] = self._parse_date(str(value))
                        print(f"📅 Updated date: {entities[key]}")
                    elif key == "time":
                        entities[key] = str(value)
                        entities["requested_time"] = str(value)
                        if self._is_specific_time(str(value)):
                            entities["selected_time"] = str(value)
                        print(f"🕐 Updated time: {entities[key]}")
                    elif key == "attendees":
                        if isinstance(value, list):
                            entities[key] = value
                        else:
                            entities[key] = [str(value)] if str(value).strip() else []
                        print(f"👥 Updated attendees: {entities[key]}")


            # Handle generic time defaults
            entities = self._handle_generic_time_defaults(entities)

            # FIXED: Enhanced title detection for simple responses
            if not entities.get("title") and state.get("conversation_stage") == "asking_title":
                # If we're specifically asking for title and don't have one yet
                # Be more liberal in accepting the response as a title
                last_message_clean = last_message.strip().strip('"\'')
                # Avoid obvious non-titles
                non_title_phrases = [
                    "i don't know", 'not sure', 'whatever', 'anything', 'nothing specific',
                    'just a meeting', 'regular meeting', 'normal meeting'
                ]
                if (
                    last_message_clean and
                    len(last_message_clean.split()) <= 6 and
                    not any(phrase in last_message.lower() for phrase in non_title_phrases) and
                    not any(word in last_message.lower() for word in ['when', 'what', 'how', 'where', 'time'])
                ):
                    entities["title"] = last_message_clean.title()
                    print(f"🎯 Force-detected title from asking_title stage: '{entities['title']}'")

            # Handle "no attendees" responses
            if self._is_no_attendees_response(last_message):
                entities["attendees"] = []
                entities["attendees_confirmed"] = True
                print("✅ No attendees confirmed")
            elif entities.get("attendees") and len(entities["attendees"]) > 0:
                entities["attendees_confirmed"] = True
                print(f"✅ Attendees auto-confirmed: {entities['attendees']}")

            state["extracted_entities"] = entities
            state["user_intent"] = intent

            return state

        except Exception as e:
            print(f"❌ Error in extract_info_node: {e}")
            return state

    def _is_cancellation(self, message: str) -> bool:
        """Check if message is a cancellation"""
        message_lower = message.lower().strip()
        cancellations = ['no', 'cancel', 'nevermind', 'no thanks', 'not now', 'abort', 'stop']
        # Handle "no, cancel" specifically
        if any(phrase in message_lower for phrase in ['no, cancel', 'no cancel', 'cancel it']):
            return True
        return message_lower in cancellations

    def _extract_time_range(self, message: str) -> Dict:
        """Extract time range like '3-5 PM' or 'between 3-5 PM'"""
        extracted = {}
        
        patterns = [
            r'(?:between\s+)?(\d{1,2})\s*(?:-|to)\s*(\d{1,2})\s*(am|pm)',
            r'(\d{1,2})\s*(?:-|to)\s*(\d{1,2})\s*(am|pm)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, message.lower())
            if match:
                start_hour = int(match.group(1))
                end_hour = int(match.group(2))
                ampm = match.group(3)
                
                # Calculate duration
                if ampm == 'pm' and start_hour != 12:
                    start_hour += 12
                if ampm == 'pm' and end_hour != 12:
                    end_hour += 12
                elif ampm == 'am' and end_hour == 12:
                    end_hour = 0
                
                duration_hours = end_hour - start_hour
                if duration_hours < 0:
                    duration_hours += 24
                
                extracted["duration"] = f"{duration_hours} hour{'s' if duration_hours != 1 else ''}"
                extracted["time"] = f"{match.group(1)} {ampm}"
                extracted["time_range"] = f"{match.group(1)}-{match.group(2)} {ampm}"
                
                print(f"🕐 Extracted time range: {extracted['time_range']} (Duration: {extracted['duration']})")
                break
        
        return extracted

    def _is_day_selection(self, message: str, stage: str = None) -> bool:
        """Check if message is selecting a day for weekly booking"""
        if stage != "asking_specific_day":
            return False
        
        days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
        message_lower = message.lower().strip()
        
        return any(day in message_lower for day in days)

    def _extract_selected_day(self, message: str) -> str:
        """Extract selected day from user message"""
        days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
        message_lower = message.lower().strip()
        
        for day in days:
            if day in message_lower:
                return day
        
        return message.strip().lower()

    def _parse_specific_day(self, day: str) -> datetime:
        """Parse specific day to next occurrence"""
        today = datetime.now()
        weekdays = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
        
        if day.lower() in weekdays:
            target_weekday = weekdays.index(day.lower())
            days_ahead = target_weekday - today.weekday()
            
            if days_ahead <= 0:
                days_ahead += 7
                
            return today + timedelta(days=days_ahead)
        
        return today + timedelta(days=7)

    def _is_specific_time(self, time_str: str) -> bool:
        """Check if time string is specific vs generic"""
        time_str_lower = time_str.lower().strip()
        generic_times = ['morning', 'afternoon', 'evening', 'night']
        
        if time_str_lower in generic_times:
            return False
            
        specific_patterns = [
            r'\d{1,2}:\d{2}\s*(?:am|pm)',
            r'\d{1,2}\s*(?:am|pm)',
        ]
        
        for pattern in specific_patterns:
            if re.search(pattern, time_str_lower):
                return True
                
        return False

    def _is_new_booking_request(self, message: str, state: Dict) -> bool:
        """Check if this is a new booking request after a completed booking"""
        current_stage = state.get("conversation_stage", "")
        if current_stage not in ["booking_confirmed", "booking_failed"]:
            return False
            
        message_lower = message.lower()
        booking_keywords = [
            'schedule', 'book', 'meeting', 'call', 'appointment', 
            'set up', 'arrange', 'plan', 'availability'
        ]
        
        return any(keyword in message_lower for keyword in booking_keywords)

    def _reset_conversation_state(self, state: Dict) -> Dict:
        """Reset conversation state for new booking"""
        state["extracted_entities"] = {}
        state["calendar_availability"] = None
        state["current_booking"] = None
        state["conversation_stage"] = "initial"
        state["user_intent"] = None
        state["booking_summary"] = None
        return state

    def _extract_combined_info(self, message: str) -> Dict:
        """Extract multiple pieces of info from a single message"""
        extracted = {}
        
        time_patterns = [
            r'(\d{1,2}:\d{2}\s*(?:am|pm))',
            r'(\d{1,2}\s*(?:am|pm))',
        ]
        
        for pattern in time_patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                extracted["time"] = match.group(1)
                break
        
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        emails = re.findall(email_pattern, message)
        if emails:
            extracted["attendees"] = emails
        
        return extracted

    def _is_confirmation(self, message: str) -> bool:
        """Check if message is a confirmation"""
        message_lower = message.lower().strip()
        confirmations = ['yes', 'yep', 'yeah', 'confirm', 'book it', 'schedule it', 'ok', 'okay', 'sure']
        return message_lower in confirmations

    def _is_time_selection(self, message: str, stage: str = None) -> bool:
        """Check if message is selecting a time slot"""
        if stage not in ["showing_slots", "showing_alternative_slots"]:
            return False
        
        time_patterns = [
            r'\d{1,2}:\d{2}\s*(?:AM|PM)',
            r'\d{1,2}\s*(?:AM|PM)',
            r'^\d{1,2}$'
        ]
        
        for pattern in time_patterns:
            if re.search(pattern, message, re.IGNORECASE):
                return True
        return False

    def _extract_selected_time(self, message: str) -> str:
        """Extract selected time from user message"""
        time_patterns = [
            r'(\d{1,2}:\d{2}\s*(?:AM|PM))',
            r'(\d{1,2}\s*(?:AM|PM))',
            r'^(\d{1,2})$'
        ]
        
        for pattern in time_patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                return match.group(1)
        return message.strip()

    def _is_no_attendees_response(self, message: str) -> bool:
        """Check if user doesn't want attendees"""
        message_lower = message.lower().strip()
        no_attendees = ['no', 'none', 'just me', 'only me', 'no one', 'nobody']
        return message_lower in no_attendees

    def _route_next_step(self, state: Dict) -> str:
        """Enhanced routing with proper conflict and cancellation handling"""
        entities = state.get("extracted_entities", {})
        intent = state.get("user_intent", "")
        stage = state.get("conversation_stage", "")

        # Handle confirmation
        if intent == "confirm_booking":
            if self._has_complete_booking_info(entities):
                return "create_booking"
            else:
                return "generate_response"

        # FIXED: Handle cancellation - reset everything
        if intent == "cancel_booking" or stage == "booking_cancelled":
            return "generate_response"

        # Handle booking conflicts - show alternatives
        if stage == "booking_conflict":
            return "handle_conflict"

        # Enhanced flow routing with day selection for weekly bookings
        if not entities.get("title"):
            return "ask_title"
        elif not entities.get("duration"):
            return "ask_duration"
        elif self._needs_specific_day(entities):
            return "ask_specific_day"
        elif not entities.get("selected_time"):
            return "check_availability"
        elif not entities.get("attendees_confirmed"):
            return "ask_attendees"
        else:
            return "confirm_booking"

    def _needs_specific_day(self, entities: Dict) -> bool:
        """Check if we need to ask for specific day"""
        date_str = entities.get("date", "")
        has_specific_day = entities.get("day_confirmed", False)
        
        if "next week" in date_str.lower() and not has_specific_day:
            return True
        
        return False

    def _has_complete_booking_info(self, entities: Dict) -> bool:
        """Check if we have all info needed for booking"""
        required = ["title", "duration", "attendees_confirmed", "selected_time"]
        has_date = entities.get("parsed_date")
        
        return all(entities.get(key) for key in required) and has_date

    async def _ask_title_node(self, state: Dict) -> Dict:
        """Ask for meeting title"""
        print("📝 Asking for meeting title...")
        state["conversation_stage"] = "asking_title"
        return state

    async def _ask_duration_node(self, state: Dict) -> Dict:
        """Ask for meeting duration"""
        print("⏱️ Asking for meeting duration...")
        state["conversation_stage"] = "asking_duration"
        return state

    async def _ask_specific_day_node(self, state: Dict) -> Dict:
        """Ask for specific day when user says 'next week'"""
        print("📅 Asking for specific day...")
        state["conversation_stage"] = "asking_specific_day"
        return state

    async def _check_availability_node(self, state: Dict) -> Dict:
        """FIXED: Enhanced availability checking with proper alternative exclusion"""
        try:
            print("📅 Checking calendar availability...")
            entities = state.get("extracted_entities", {})
            
            # Get target date
            target_date = entities.get("parsed_date")
            if not target_date:
                target_date = datetime.now()
                entities["parsed_date"] = target_date
                entities["date"] = "today"

            # Get duration
            duration_str = entities.get("duration", "1 hour")
            duration_td = parse_duration(duration_str)

            # FIXED: Handle generic time defaults first
            default_time = entities.get("default_time")
            generic_time_used = entities.get("generic_time_used")
            
            if default_time and generic_time_used:
                print(f"🎯 Checking default time {default_time} for '{generic_time_used}'...")
                
                # Check if the default time is available
                is_available = await self._check_specific_time(target_date, default_time, duration_td)
                
                if is_available:
                    # Default time is available, set it as selected
                    entities["selected_time"] = default_time
                    entities["time_confirmed"] = True
                    entities["time_source"] = f"default_{generic_time_used}"
                    state["conversation_stage"] = "time_confirmed"
                    state["extracted_entities"] = entities
                    print(f"✅ Default time {default_time} is available for {generic_time_used}")
                    return state
                else:
                    print(f"❌ Default time {default_time} is not available for {generic_time_used}")
                    # Store the failed time to exclude from alternatives
                    entities["failed_default_time"] = default_time

            # Get available slots
            start_date = target_date.replace(hour=0, minute=0, second=0)
            end_date = target_date.replace(hour=23, minute=59, second=59)
            
            available_slots = await self.calendar_service.get_availability(start_date, end_date)
            
            # FIXED: Filter slots and exclude conflicted times
            suitable_slots = []
            failed_time = entities.get("failed_default_time")
            
            for slot in available_slots:
                slot_start = datetime.fromisoformat(slot['start'])
                slot_end = slot_start + duration_td
                
                # Check if this duration fits in our target date
                if slot_start.date() == target_date.date():
                    # FIXED: Exclude the failed default time from alternatives
                    if failed_time:
                        slot_time_str = slot_start.strftime('%I:%M %p').replace(' 0', ' ')
                        failed_time_formatted = self._format_time_for_comparison(failed_time)
                        if slot_time_str.lower() == failed_time_formatted.lower():
                            print(f"⚠️ Excluding failed time {slot_time_str} from alternatives")
                            continue
                    
                    # Verify slot is actually available (no conflicts)
                    if await self._is_slot_available(slot_start, slot_end):
                        suitable_slots.append({
                            'start': slot['start'],
                            'display': slot['display'],
                            'full_display': f"{slot_start.strftime('%A, %B %d')}: {slot['display']}"
                        })

            if suitable_slots:
                state["calendar_availability"] = suitable_slots[:8]  # Limit to 8 slots
                
                # FIXED: Set different stage based on whether we tried a default time
                if default_time and generic_time_used:
                    state["conversation_stage"] = "showing_alternative_slots"
                    state["default_time_failed"] = default_time
                    state["generic_time_failed"] = generic_time_used
                    print(f"🔄 Showing alternatives since {default_time} ({generic_time_used}) is taken")
                else:
                    state["conversation_stage"] = "showing_slots"
                    print(f"✅ Found {len(suitable_slots)} available slots")
            else:
                # No slots available
                state["calendar_availability"] = []
                state["conversation_stage"] = "no_availability"
                print("❌ No available slots found")
            
            state["extracted_entities"] = entities
            return state

        except Exception as e:
            print(f"❌ Error checking availability: {e}")
            state["calendar_availability"] = []
            state["conversation_stage"] = "availability_error"
            return state

    def _format_time_for_comparison(self, time_str: str) -> str:
        """Format time string for comparison"""
        try:
            parsed_time = self._parse_time(time_str)
            return parsed_time.strftime('%I:%M %p').replace(' 0', ' ')
        except:
            return time_str

    async def _check_specific_time(self, date: datetime, time_str: str, duration: timedelta) -> bool:
        """Check if specific time is available"""
        try:
            parsed_time = self._parse_time(time_str)
            start_time = date.replace(
                hour=parsed_time.hour,
                minute=parsed_time.minute,
                second=0,
                microsecond=0
            )
            end_time = start_time + duration

            # Get existing events for that day
            day_start = date.replace(hour=0, minute=0, second=0)
            day_end = date.replace(hour=23, minute=59, second=59)
            existing_events = await self.calendar_service.get_events(day_start, day_end)

            # Check for conflicts
            for event in existing_events:
                try:
                    event_start = datetime.fromisoformat(event['start_time'].replace('Z', '+00:00')).replace(tzinfo=None)
                    event_end = datetime.fromisoformat(event['end_time'].replace('Z', '+00:00')).replace(tzinfo=None)
                    
                    # Check for overlap
                    if start_time < event_end and end_time > event_start:
                        return False
                except Exception as e:
                    print(f"⚠️ Error parsing event time: {e}")
                    continue

            return True
        except Exception as e:
            print(f"❌ Error checking specific time: {e}")
            return False

    async def _is_slot_available(self, start_time: datetime, end_time: datetime) -> bool:
        """Check if a specific time slot is available"""
        try:
            # Get existing events for that day
            day_start = start_time.replace(hour=0, minute=0, second=0)
            day_end = start_time.replace(hour=23, minute=59, second=59)
            existing_events = await self.calendar_service.get_events(day_start, day_end)

            # Check for conflicts
            for event in existing_events:
                try:
                    event_start = datetime.fromisoformat(event['start_time'].replace('Z', '+00:00')).replace(tzinfo=None)
                    event_end = datetime.fromisoformat(event['end_time'].replace('Z', '+00:00')).replace(tzinfo=None)
                    
                    # Check for overlap
                    if start_time < event_end and end_time > event_start:
                        return False
                except Exception as e:
                    print(f"⚠️ Error parsing event time: {e}")
                    continue

            return True
        except Exception as e:
            print(f"❌ Error checking slot availability: {e}")
            return False

    async def _handle_conflict_node(self, state: Dict) -> Dict:
        """FIXED: Handle booking conflicts by showing proper alternatives"""
        try:
            print("⚠️ Handling booking conflict - finding alternatives...")
            entities = state.get("extracted_entities", {})
            
            target_date = entities.get("parsed_date")
            duration_str = entities.get("duration", "1 hour")
            duration_td = parse_duration(duration_str)
            conflicted_time = entities.get("selected_time", "")

            # Get fresh availability excluding the conflicted time
            start_date = target_date.replace(hour=0, minute=0, second=0)
            end_date = target_date.replace(hour=23, minute=59, second=59)
            
            available_slots = await self.calendar_service.get_availability(start_date, end_date)
            
            # FIXED: Filter available slots and exclude the conflicted time
            suitable_slots = []
            for slot in available_slots:
                slot_start = datetime.fromisoformat(slot['start'])
                slot_end = slot_start + duration_td
                
                if slot_start.date() == target_date.date():
                    # FIXED: Exclude the conflicted time
                    if conflicted_time:
                        slot_time_str = slot_start.strftime('%I:%M %p').replace(' 0', ' ')
                        conflicted_time_formatted = self._format_time_for_comparison(conflicted_time)
                        if slot_time_str.lower() == conflicted_time_formatted.lower():
                            print(f"⚠️ Excluding conflicted time {slot_time_str} from alternatives")
                            continue
                    
                    if await self._is_slot_available(slot_start, slot_end):
                        suitable_slots.append({
                            'start': slot['start'],
                            'display': slot['display'],
                            'full_display': f"{slot_start.strftime('%A, %B %d')}: {slot['display']}"
                        })

            if suitable_slots:
                state["calendar_availability"] = suitable_slots[:8]
                state["conversation_stage"] = "showing_alternative_slots"
                state["conflict_message"] = f"The selected time slot ({conflicted_time}) is no longer available"
                print(f"✅ Found {len(suitable_slots)} alternative slots")
            else:
                state["calendar_availability"] = []
                state["conversation_stage"] = "no_alternatives"
                state["conflict_message"] = f"The selected time slot ({conflicted_time}) is no longer available"
                print("❌ No alternative slots available")

            return state

        except Exception as e:
            print(f"❌ Error handling conflict: {e}")
            state["conversation_stage"] = "conflict_error"
            return state

    async def _ask_attendees_node(self, state: Dict) -> Dict:
        """Ask for meeting attendees"""
        print("👥 Asking for attendees...")
        state["conversation_stage"] = "asking_attendees"
        return state

    async def _confirm_booking_node(self, state: Dict) -> Dict:
        """Show booking confirmation with actual dates"""
        print("✅ Preparing booking confirmation...")
        entities = state.get("extracted_entities", {})
        
        selected_time = entities.get("selected_time", "")
        title = entities.get("title", "Meeting")
        duration = entities.get("duration", "1 hour")
        parsed_date = entities.get("parsed_date")
        attendees = entities.get("attendees", [])

        # Format actual date instead of generic text
        if parsed_date:
            formatted_date = parsed_date.strftime('%A, %B %d, %Y')
        else:
            formatted_date = "Not specified"

        # Format time properly for display
        if selected_time:
            try:
                parsed_time = self._parse_time(selected_time)
                formatted_time = parsed_time.strftime('%I:%M %p')
            except:
                formatted_time = selected_time
        else:
            formatted_time = "Not specified"

        booking_summary = {
            "title": title,
            "date": formatted_date,
            "time": formatted_time,
            "duration": duration,
            "attendees": attendees
        }

        state["booking_summary"] = booking_summary
        state["conversation_stage"] = "awaiting_confirmation"
        return state

    async def _create_booking_node(self, state: Dict) -> Dict:
        """Create actual calendar booking with enhanced conflict checking"""
        try:
            print("📝 Creating real calendar booking...")
            entities = state.get("extracted_entities", {})

            # Extract booking details
            title = entities.get("title", "Meeting")
            duration_str = entities.get("duration", "1 hour")
            selected_time = entities.get("selected_time", "")
            target_date = entities.get("parsed_date")
            attendees = entities.get("attendees", [])

            if not all([title, duration_str, selected_time, target_date]):
                raise ValueError("Missing required booking information")

            # Calculate start and end times
            duration_td = parse_duration(duration_str)
            parsed_time = self._parse_time(selected_time)
            
            start_time = target_date.replace(
                hour=parsed_time.hour,
                minute=parsed_time.minute,
                second=0,
                microsecond=0
            )
            end_time = start_time + duration_td

            # Final conflict check before booking
            print("🔍 Performing final conflict check...")
            is_available = await self._is_slot_available(start_time, end_time)
            
            if not is_available:
                print("❌ Conflict detected, setting up alternative flow...")
                state["conversation_stage"] = "booking_conflict"
                state["conflict_message"] = f"The selected time slot ({selected_time}) is no longer available"
                # FIXED: Don't return here, let it route to handle_conflict
                return state

            # Create booking request
            booking = BookingRequest(
                title=title,
                start_time=start_time,
                end_time=end_time,
                description=f"Meeting: {title}\nDuration: {duration_str}\nBooked via AI Assistant",
                attendees=attendees
            )

            # Create the actual event
            created_event = await self.calendar_service.create_event(booking)

            if created_event and created_event.get('id'):
                # Clean attendees data for schema validation
                clean_event = created_event.copy()
                if 'attendees' in clean_event:
                    clean_attendees = []
                    for attendee in clean_event['attendees']:
                        if isinstance(attendee, dict):
                            clean_attendees.append(attendee.get('email', ''))
                        else:
                            clean_attendees.append(str(attendee))
                    clean_event['attendees'] = clean_attendees

                state["current_booking"] = clean_event
                state["conversation_stage"] = "booking_confirmed"
                print(f"✅ Booking created: {created_event.get('id')}")
            else:
                state["conversation_stage"] = "booking_failed"
                print("❌ Failed to create booking")

        except Exception as e:
            print(f"❌ Error creating booking: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            state["conversation_stage"] = "booking_failed"
            state["error_message"] = str(e)

        return state

    async def _generate_response_node(self, state: Dict) -> Dict:
        """Generate appropriate response with IST timestamps"""
        try:
            print("💬 Generating response...")
            
            conversation_history = [
                {"role": msg["role"], "content": msg["content"]}
                for msg in state.get("messages", [])
            ]

            context = {
                "intent": state.get("user_intent"),
                "entities": state.get("extracted_entities", {}),
                "availability": state.get("calendar_availability"),
                "booking": state.get("current_booking"),
                "stage": state.get("conversation_stage", "initial"),
                "booking_summary": state.get("booking_summary"),
                "error_message": state.get("error_message"),
                "conflict_message": state.get("conflict_message"),
                "default_time_failed": state.get("default_time_failed"),
                "generic_time_failed": state.get("generic_time_failed")
            }

            response = await self.ai_service.generate_response(conversation_history, context)

            # FIXED: Use IST timestamp
            ist_time = get_ist_time()
            response_message = {
                "role": "assistant",
                "content": response,
                "timestamp": ist_time.isoformat()  # FIXED: IST timestamp
            }

            if "messages" not in state:
                state["messages"] = []
            state["messages"].append(response_message)

            print(f"✅ Generated response at {ist_time.strftime('%H:%M:%S IST')}: {response[:50]}...")
            return state

        except Exception as e:
            print(f"❌ Error generating response: {e}")
            ist_time = get_ist_time()
            fallback_response = {
                "role": "assistant",
                "content": "I'm here to help you schedule meetings. What would you like to book?",
                "timestamp": ist_time.isoformat()  # FIXED: IST timestamp
            }
            
            if "messages" not in state:
                state["messages"] = []
            state["messages"].append(fallback_response)
            return state

    def _parse_date(self, date_str: str) -> datetime:
        """Parse date string to datetime with better Friday handling"""
        today = datetime.now()
        date_str_lower = date_str.lower()
        
        if date_str_lower == "today":
            return today
        elif date_str_lower == "tomorrow":
            return today + timedelta(days=1)
        elif date_str_lower == "next week":
            return today + timedelta(days=7)
        elif date_str_lower in ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']:
            weekdays = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
            target_weekday = weekdays.index(date_str_lower)
            days_ahead = target_weekday - today.weekday()
            
            # If day has passed this week, get next week's occurrence
            if days_ahead <= 0:
                days_ahead += 7
            return today + timedelta(days=days_ahead)
        elif date_str_lower.startswith('this '):
            day_part = date_str_lower.replace('this ', '')
            if day_part in ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']:
                weekdays = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
                target_weekday = weekdays.index(day_part)
                days_ahead = target_weekday - today.weekday()
                
                # "this Friday" on Saturday should be next Friday
                if days_ahead <= 0:
                    days_ahead += 7
                return today + timedelta(days=days_ahead)
        elif date_str_lower.startswith('next '):
            day_part = date_str_lower.replace('next ', '')
            if day_part in ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']:
                weekdays = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
                target_weekday = weekdays.index(day_part)
                days_ahead = target_weekday - today.weekday() + 7
                return today + timedelta(days=days_ahead)
        
        return today

    def _parse_time(self, time_str: str) -> datetime:
        """Enhanced time parsing to handle various formats"""
        print(f"🕐 Parsing time: '{time_str}'")
        
        time_str = time_str.strip()
        
        patterns = [
            r'(\d{1,2}):(\d{2})\s*(am|pm)',  # 3:00 PM
            r'(\d{1,2})\s*(am|pm)',         # 3 PM
            r'(\d{1,2}):(\d{2})',           # 15:00
            r'^(\d{1,2})$'                  # 15
        ]
        
        for pattern in patterns:
            match = re.search(pattern, time_str.lower())
            if match:
                try:
                    if len(match.groups()) >= 3:  # Has am/pm
                        hour = int(match.group(1))
                        minute = int(match.group(2)) if len(match.groups()) > 2 and match.group(2) and match.group(2).isdigit() else 0
                        ampm = match.group(3) if len(match.groups()) > 2 else match.group(2)
                        
                        if ampm == 'pm' and hour != 12:
                            hour += 12
                        elif ampm == 'am' and hour == 12:
                            hour = 0
                    elif len(match.groups()) == 2:  # Hour and minute without am/pm
                        hour = int(match.group(1))
                        minute = int(match.group(2))
                        if 1 <= hour <= 5:
                            hour += 12
                    else:  # Just hour
                        hour = int(match.group(1))
                        minute = 0
                        if 1 <= hour <= 11:
                            hour += 12
                    
                    # Validate hour and minute
                    if 0 <= hour <= 23 and 0 <= minute <= 59:
                        return datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
                    else:
                        print(f"⚠️ Invalid hour/minute: {hour}:{minute}")
                        
                except ValueError as e:
                    print(f"⚠️ Error parsing time components: {e}")
                    continue
        
        # Handle generic time descriptions
        time_str_lower = time_str.lower()
        if 'afternoon' in time_str_lower:
            return datetime.now().replace(hour=14, minute=0, second=0, microsecond=0)  # 2 PM
        elif 'morning' in time_str_lower:
            return datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)  # 10 AM
        elif 'evening' in time_str_lower:
            return datetime.now().replace(hour=18, minute=0, second=0, microsecond=0)  # 6 PM
        
        # Default fallback
        print(f"⚠️ Could not parse time '{time_str}', using default 2 PM")
        return datetime.now().replace(hour=14, minute=0, second=0, microsecond=0)

    async def process_message(self, conversation_state: ConversationState) -> ConversationState:
        """Process message through the agent workflow"""
        try:
            print("🤖 Processing message through simplified workflow...")
            state_dict = self._conversation_state_to_dict(conversation_state)
            result_dict = await self.graph.ainvoke(state_dict)
            updated_conversation = self._dict_to_conversation_state(result_dict)
            print("✅ Processing completed")
            return updated_conversation
        except Exception as e:
            print(f"❌ Error in process_message: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            
            # Add fallback message
            fallback_message = ChatMessage(
                role=MessageRole.ASSISTANT,
                content="I'm here to help you schedule meetings. Could you tell me what kind of meeting you'd like to book?",
                timestamp=datetime.now()
            )
            conversation_state.messages.append(fallback_message)
            return conversation_state
