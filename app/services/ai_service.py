import json
from typing import Dict, List, Any, Optional
import os
from datetime import datetime, timedelta
import re
import time

class AIService:
    def __init__(self):
        # Support both Gemini and OpenRouter
        self.gemini_api_key = os.getenv("GEMINI_API_KEY")
        self.openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
        
        # Determine which service to use
        self.use_openrouter = False
        self.use_gemini = False
        
        # Try OpenRouter first if key starts with sk-or-v1
        if self.gemini_api_key and self.gemini_api_key.startswith("sk-or-v1"):
            print("🔄 Detected OpenRouter API key, switching to OpenRouter...")
            self.openrouter_api_key = self.gemini_api_key
            self.gemini_api_key = None
            self.use_openrouter = True
        elif self.gemini_api_key:
            self.use_gemini = True
        elif self.openrouter_api_key:
            self.use_openrouter = True
        else:
            raise ValueError("Either GEMINI_API_KEY or OPENROUTER_API_KEY is required")

        # Initialize the appropriate service
        if self.use_openrouter:
            self._init_openrouter()
        elif self.use_gemini:
            self._init_gemini()

        self.request_count = 0
        self.last_reset = datetime.now()
        self.max_requests_per_minute = 20

    def _init_openrouter(self):
        """Initialize OpenRouter service"""
        try:
            import requests
            self.openrouter_available = True
            print("✅ OpenRouter service initialized")
        except Exception as e:
            print(f"⚠️ OpenRouter not available: {e}")
            self.openrouter_available = False

    def _init_gemini(self):
        """Initialize Gemini service"""
        try:
            from google import genai
            from google.genai import types
            self.client = genai.Client(api_key=self.gemini_api_key)
            self.genai_available = True
            print("✅ Gemini API initialized")
        except Exception as e:
            print(f"⚠️ Gemini API not available: {e}")
            self.genai_available = False

    def _check_rate_limit(self) -> bool:
        """Check if we're within rate limits"""
        now = datetime.now()
        if (now - self.last_reset).total_seconds() >= 60:
            self.request_count = 0
            self.last_reset = now
        return self.request_count < self.max_requests_per_minute

    def _increment_request_count(self):
        """Increment request counter"""
        self.request_count += 1

    async def extract_intent_and_entities(self, message: str) -> Dict:
        """Extract intent and entities from user message"""
        # Handle simple confirmations
        if self._is_simple_confirmation(message):
            return {
                "intent": "confirm_booking",
                "entities": {}
            }

        # Handle simple rejections
        if self._is_simple_rejection(message):
            return {
                "intent": "reject",
                "entities": {}
            }

        # Check rate limits
        if not self._check_rate_limit():
            print("⚠️ Rate limit reached, using rule-based extraction")
            return self._rule_based_extraction(message)

        # Try AI service
        if self.use_openrouter and self.openrouter_available:
            try:
                self._increment_request_count()
                return await self._try_openrouter_extraction(message)
            except Exception as e:
                print(f"❌ OpenRouter error: {e}")
        elif self.use_gemini and self.genai_available:
            try:
                self._increment_request_count()
                return await self._try_gemini_extraction(message)
            except Exception as e:
                print(f"❌ Gemini error: {e}")

        # Fallback to rule-based
        return self._rule_based_extraction(message)

    def _is_simple_confirmation(self, message: str) -> bool:
        """Check if message is a simple confirmation"""
        message_lower = message.lower().strip()
        confirmations = ['yes', 'yep', 'yeah', 'confirm', 'book it', 'schedule it', 'ok', 'okay', 'sure', 'go ahead']
        return message_lower in confirmations

    def _is_simple_rejection(self, message: str) -> bool:
        """Check if message is a simple rejection"""
        message_lower = message.lower().strip()
        rejections = ['no', 'nope', 'cancel', 'nevermind', 'not now']
        return message_lower in rejections

    async def _try_openrouter_extraction(self, message: str) -> Dict:
        """Extract using OpenRouter API"""
        import requests

        prompt = f"""
Extract booking information from this message. Return valid JSON only.

Message: "{message}"

Return JSON with:
{{
  "intent": "book_appointment|check_availability|provide_info|confirm_booking",
  "entities": {{
    "title": "meeting topic or null",
    "date": "date mentioned or null", 
    "time": "time mentioned or null",
    "duration": "duration mentioned or null",
    "attendees": ["email addresses found or empty array"]
  }}
}}

Examples:
- "Book a meeting about AI" -> {{"intent": "book_appointment", "entities": {{"title": "AI"}}}}
- "tomorrow at 3pm" -> {{"intent": "provide_info", "entities": {{"date": "tomorrow", "time": "3pm"}}}}
- "1 hour" -> {{"intent": "provide_info", "entities": {{"duration": "1 hour"}}}}
"""

        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.openrouter_api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "google/gemini-flash-1.5",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 300
                },
                timeout=15
            )

            if response.status_code == 200:
                content = response.json()["choices"][0]["message"]["content"]
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group())
                    return self._clean_entities(result)
        except Exception as e:
            print(f"❌ OpenRouter extraction failed: {e}")

        return self._rule_based_extraction(message)

    async def _try_gemini_extraction(self, message: str) -> Dict:
        """Extract using Gemini API"""
        from google.genai import types

        prompt = f"""
Extract booking information from: "{message}"

Return only valid JSON with intent and entities. Be precise and concise.
"""

        try:
            response = self.client.models.generate_content(
                model="gemini-1.5-flash",
                contents=[
                    types.Content(
                        role="user",
                        parts=[types.Part(text=prompt)]
                    )
                ],
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=300
                )
            )

            content = response.text.strip()
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                return self._clean_entities(result)
        except Exception as e:
            print(f"❌ Gemini extraction failed: {e}")

        return self._rule_based_extraction(message)

    def _rule_based_extraction(self, message: str) -> Dict:
        """Rule-based entity extraction as fallback"""
        message_lower = message.lower().strip()
        entities = {}

        # Extract title
        title = self._extract_title(message)
        if title:
            entities["title"] = title

        # Extract duration
        duration = self._extract_duration(message)
        if duration:
            entities["duration"] = duration

        # Extract time
        time_found = self._extract_time(message)
        if time_found:
            entities["time"] = time_found

        # Extract date
        date_found = self._extract_date(message)
        if date_found:
            entities["date"] = date_found

        # Extract emails
        emails = self._extract_emails(message)
        if emails:
            entities["attendees"] = emails

        # Determine intent
        intent = self._determine_intent(message, entities)

        return {"intent": intent, "entities": entities}

    def _extract_title(self, message: str) -> Optional[str]:
        """FIXED: Extract meeting title from message with better simple title detection"""
        message_lower = message.lower().strip()
        
        # Handle explicit title statements first
        if "purpose" in message_lower or "topic" in message_lower:
            # Extract from "the purpose is X" or "topic is X"
            purpose_patterns = [
                r'(?:purpose|topic)\s+is\s+(.+)',
                r'(?:it\'s|its)\s+(?:about|for)\s+(.+)',
                r'(?:the\s+)?(?:purpose|topic):\s*(.+)',
                r'"(.+)"\s+is\s+the\s+(?:purpose|topic)'
            ]
            
            for pattern in purpose_patterns:
                match = re.search(pattern, message_lower)
                if match:
                    title = match.group(1).strip().strip('"\'')
                    return title.title()
        
        # Common patterns for titles in longer sentences
        patterns = [
            r'(?:meeting|call|session)\s+(?:about|regarding|on)\s+([^,\.]+)',
            r'(?:schedule|book)\s+(?:a\s+)?(?:meeting|call)\s+(?:about|regarding|on)\s+([^,\.]+)',
            r'discuss\s+([^,\.]+)',
            r'talk\s+about\s+([^,\.]+)',
            r'(?:have\s+a\s+)?(?:meeting|call)\s+(?:to\s+)?(?:discuss\s+)?([^,\.]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, message_lower)
            if match:
                title = match.group(1).strip()
                # Clean up the title
                title = re.sub(r'\s+', ' ', title)  # Remove extra spaces
                return title.title()

        # FIXED: Better simple word/phrase detection
        words = message.strip().split()
        
        # Skip obvious non-titles
        skip_words = ['time', 'hour', 'minute', 'pm', 'am', 'today', 'tomorrow', 'yes', 'no', 'ok', 'okay']
        
        # If it's 1-4 words and doesn't contain time-related words
        if 1 <= len(words) <= 4:
            # Check if any word is in skip_words
            if not any(word.lower() in skip_words for word in words):
                # Additional check: avoid sentences with question words
                question_words = ['what', 'when', 'where', 'how', 'why', 'who', 'which']
                if not any(word.lower() in question_words for word in words):
                    # FIXED: This should catch "casual call", "project review", etc.
                    title = message.strip()
                    print(f"🎯 Detected simple title: '{title}'")
                    return title.title()
        
        # Handle quoted text as titles
        quoted_match = re.search(r'"([^"]+)"', message)
        if quoted_match:
            return quoted_match.group(1).title()
        
        # Single word titles (but avoid obvious non-titles)
        if len(words) == 1 and words[0].lower() not in skip_words and len(words[0]) > 2:
            return words[0].title()
        
        return None

    def _extract_duration(self, message: str) -> Optional[str]:
        """Extract duration from message"""
        message_lower = message.lower()
        
        # Duration patterns
        patterns = [
            r'(\d+(?:\.\d+)?)\s*hours?',
            r'(\d+)\s*hrs?',
            r'(\d+)\s*minutes?',
            r'(\d+)\s*mins?',
            r'an?\s+hour',
            r'half\s+(?:an\s+)?hour',
            r'(\d+)hour',  # Handle "1hour" format
        ]
        
        for pattern in patterns:
            match = re.search(pattern, message_lower)
            if match:
                if 'hour' in pattern:
                    if 'half' in pattern:
                        return "30 minutes"
                    elif match.group(1) if match.lastindex else None:
                        num = match.group(1)
                        return f"{num} hour{'s' if float(num) != 1 else ''}"
                    else:
                        return "1 hour"
                elif 'minute' in pattern:
                    num = match.group(1)
                    return f"{num} minutes"
        
        return None

    def _extract_time(self, message: str) -> Optional[str]:
        """Extract time from message"""
        patterns = [
            r'(\d{1,2}:\d{2}\s*(?:am|pm))',
            r'(\d{1,2}\s*(?:am|pm))',
            r'(\d{1,2})(?::\d{2})?\s*(?:o\'?clock)?',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, message.lower())
            if match:
                return match.group(1)
        
        return None

    def _extract_date(self, message: str) -> Optional[str]:
        """Extract date from message"""
        message_lower = message.lower()
        
        date_patterns = [
            'today', 'tomorrow', 'next week', 'this friday', 'next friday',
            'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'
        ]
        
        for pattern in date_patterns:
            if pattern in message_lower:
                return pattern
        
        return None

    def _extract_emails(self, message: str) -> List[str]:
        """Extract email addresses from message"""
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        emails = re.findall(email_pattern, message)
        return emails

    def _determine_intent(self, message: str, entities: Dict) -> str:
        """Determine user intent"""
        message_lower = message.lower()
        
        if any(word in message_lower for word in ['book', 'schedule', 'arrange', 'set up']):
            return "book_appointment"
        elif any(word in message_lower for word in ['available', 'free', 'check']):
            return "check_availability"
        elif any(word in message_lower for word in ['yes', 'confirm', 'book it']):
            return "confirm_booking"
        else:
            return "provide_info"

    def _clean_entities(self, result: Dict) -> Dict:
        """Clean and validate extracted entities"""
        entities = result.get("entities", {})
        cleaned = {}
        
        for key, value in entities.items():
            if value and str(value).strip() and str(value) not in ["null", "None", ""]:
                if key == "title" and isinstance(value, list):
                    cleaned[key] = " ".join(value)
                else:
                    cleaned[key] = value
        
        result["entities"] = cleaned
        return result

    async def generate_response(self, conversation_history: List[Dict], context: Optional[Dict] = None) -> str:
        """ENHANCED: Generate response with better OpenRouter integration and actual data"""
        if not context:
            return "Hi! I'm your AI calendar assistant. What meeting would you like to schedule?"

        stage = context.get("stage", "")
        entities = context.get("entities", {})
        availability = context.get("availability", [])
        booking = context.get("booking")
        error_message = context.get("error_message")
        conflict_message = context.get("conflict_message")

        # Handle errors
        if error_message:
            return f"I encountered an issue: {error_message}. Let's try again."

        # Handle conflicts with alternative suggestions
        if conflict_message:
            if availability and len(availability) > 0:
                return f"{conflict_message}. Here are some alternative times available for your '{entities.get('title', 'meeting')}':"
            else:
                return f"{conflict_message}. Unfortunately, there are no other available slots for that day. Would you like to try a different date?"

        # FIXED: Use OpenRouter for dynamic responses with ACTUAL DATA
        if stage in ["asking_title", "asking_duration", "asking_attendees"]:
            if self.use_openrouter and self.openrouter_available and self._check_rate_limit():
                try:
                    self._increment_request_count()
                    dynamic_response = await self._try_openrouter_response_for_stage(conversation_history, context, stage)
                    if dynamic_response:
                        print(f"🤖 OpenRouter response for {stage}: {dynamic_response[:50]}...")
                        return dynamic_response
                except Exception as e:
                    print(f"❌ OpenRouter failed for {stage}: {e}")

        # Handle different stages with templates
        if stage == "asking_title":
            return "What's the purpose or topic of your meeting?"

        elif stage == "asking_duration":
            title = entities.get("title", "meeting")
            return f"How long should your '{title}' be? (e.g., 30 minutes, 1 hour, 2 hours)"

        elif stage == "asking_specific_day":
            title = entities.get("title", "meeting")
            duration = entities.get("duration", "meeting")
            return f"Which day next week would you like to schedule your '{title}' ({duration})? (e.g., Monday, Tuesday, Wednesday, Thursday, Friday)"

        elif stage in ["showing_slots", "showing_alternative_slots"]:
            title = entities.get("title", "meeting")
            duration = entities.get("duration", "1 hour")
            
            # Get formatted date
            parsed_date = entities.get("parsed_date")
            if parsed_date:
                date_display = parsed_date.strftime('%A, %B %d')
            else:
                date_display = entities.get("date", "the selected day")
            
            if availability and len(availability) > 0:
                if stage == "showing_alternative_slots":
                    default_time_failed = context.get("default_time_failed")
                    generic_time_failed = context.get("generic_time_failed")
                    
                    if default_time_failed and generic_time_failed:
                        return f"The {generic_time_failed} slot ({default_time_failed}) is already taken. Here are other available {duration} slots for your '{title}' on {date_display}:"
                    else:
                        return f"Here are alternative {duration} slots available for your '{title}' on {date_display}. Please select a time:"
                else:
                    return f"Here are available {duration} slots for your '{title}' on {date_display}. Please select a time:"
            else:
                return f"I'm checking availability for your '{title}' on {date_display}..."

        elif stage == "asking_attendees":
            title = entities.get("title", "meeting")
            selected_time = entities.get("selected_time", "")
            
            # Get formatted date
            parsed_date = entities.get("parsed_date")
            if parsed_date:
                date_display = parsed_date.strftime('%A, %B %d')
            else:
                date_display = entities.get("date", "the selected day")
                
            if selected_time:
                return f"Great! I'll schedule your '{title}' for {selected_time} on {date_display}. Who should I invite? (Enter email addresses, or say 'no' if it's just you)"
            else:
                return f"Who should I invite to your '{title}' meeting? (Enter email addresses, or say 'no' if it's just you)"

        elif stage == "awaiting_confirmation":
            # FIXED: Use actual data instead of placeholders
            summary = context.get("booking_summary", {})
            title = summary.get("title", "Meeting")
            date = summary.get("date", "")
            time = summary.get("time", "")
            duration = summary.get("duration", "")
            attendees = summary.get("attendees", [])
            
            attendees_text = ", ".join(attendees) if attendees else "Just you"
            
            # FIXED: No location mentioned, use actual data
            return f"Please confirm your booking:\n\n**{title}**\nDate: {date}\nTime: {time}\nDuration: {duration}\nAttendees: {attendees_text}\n\nShould I book this meeting?"

        elif stage == "booking_confirmed":
            if booking and booking.get('id'):
                return "✅ **Meeting Successfully Booked!**\n\nYour meeting has been added to your calendar. Invitations have been sent to all attendees."
            else:
                return "✅ Your meeting has been scheduled successfully!"

        elif stage == "booking_failed":
            return "❌ I couldn't complete the booking. Let's try again. What meeting would you like to schedule?"

        # FIXED: Handle cancellation properly
        elif stage == "booking_cancelled":
            return "❌ **Booking Cancelled**\n\nNo worries! Let's start fresh. What meeting would you like to schedule?"

        # Try AI generation for other stages
        if not self._check_rate_limit():
            return self._generate_fallback_response(context)

        if self.use_openrouter and self.openrouter_available:
            try:
                self._increment_request_count()
                return await self._try_openrouter_response(conversation_history, context)
            except Exception as e:
                print(f"❌ OpenRouter response error: {e}")
        elif self.use_gemini and self.genai_available:
            try:
                self._increment_request_count()
                return await self._try_gemini_response(conversation_history, context)
            except Exception as e:
                print(f"❌ Gemini response error: {e}")

        return self._generate_fallback_response(context)

    async def _try_openrouter_response_for_stage(self, conversation_history: List[Dict], context: Dict, stage: str) -> str:
        """FIXED: Generate stage-specific response using OpenRouter with NO placeholders"""
        import requests
        
        entities = context.get("entities", {})
        
        # Create stage-specific prompts with actual data
        stage_prompts = {
            "asking_title": "The user wants to book a meeting but hasn't specified the purpose. Ask them what the meeting is about in a friendly, professional way. Be concise.",
            "asking_duration": f"The user wants to book a meeting about '{entities.get('title', 'their topic')}'. Ask them how long the meeting should be. Suggest common durations like 30 minutes, 1 hour, etc. Be concise.",
            "asking_attendees": f"The user wants to book a '{entities.get('title', 'meeting')}' meeting for {entities.get('duration', '1 hour')} on {entities.get('date', 'a selected day')}. Ask who should be invited. Mention they can provide email addresses or say 'no' if it's just them. Be concise and do NOT mention location."
        }
        
        prompt = stage_prompts.get(stage, "Help the user with their calendar booking request.")
        
        messages = [
            {"role": "system", "content": "You are a helpful AI calendar assistant. Be concise, professional, and friendly. Your responses should be 1-2 sentences maximum. Never mention location or use placeholders like [Name] or [Date]. Use actual data provided."},
            {"role": "user", "content": prompt}
        ]
        
        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.openrouter_api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "google/gemini-flash-1.5",
                    "messages": messages,
                    "temperature": 0.7,
                    "max_tokens": 100
                },
                timeout=15
            )
            
            if response.status_code == 200:
                content = response.json()["choices"][0]["message"]["content"]
                # FIXED: Remove any placeholders that might slip through
                content = content.replace("[Name]", "").replace("[Date]", "").replace("[Time]", "").replace("[Location]", "")
                content = content.replace("in [Location]", "").replace("at [Location]", "")
                return content.strip()
        except Exception as e:
            print(f"❌ OpenRouter API call failed: {e}")
            return None

    def _generate_template_response(self, context: Dict) -> str:
        """Fallback template responses"""
        stage = context.get("stage", "")
        entities = context.get("entities", {})
        availability = context.get("availability", [])
        booking = context.get("booking")
        error_message = context.get("error_message")
        conflict_message = context.get("conflict_message")

        # Handle errors
        if error_message:
            return f"I encountered an issue: {error_message}. Let's try again."

        # Handle conflicts with alternative suggestions
        if conflict_message:
            if availability and len(availability) > 0:
                return f"{conflict_message}. Here are some alternative times available for your '{entities.get('title', 'meeting')}':"
            else:
                return f"{conflict_message}. Unfortunately, there are no other available slots for that day. Would you like to try a different date?"

        if stage == "asking_title":
            return "What's the purpose or topic of your meeting?"
        elif stage == "asking_duration":
            title = entities.get("title", "meeting")
            return f"How long should your '{title}' be? (e.g., 30 minutes, 1 hour, 2 hours)"
        elif stage == "asking_specific_day":
            title = entities.get("title", "meeting")
            duration = entities.get("duration", "meeting")
            return f"Which day next week would you like to schedule your '{title}' ({duration})? (e.g., Monday, Tuesday, Wednesday, Thursday, Friday)"
        elif stage in ["showing_slots", "showing_alternative_slots"]:
            title = entities.get("title", "meeting")
            duration = entities.get("duration", "1 hour")
            parsed_date = entities.get("parsed_date")
            if parsed_date:
                date_display = parsed_date.strftime('%A, %B %d')
            else:
                date_display = entities.get("date", "the selected day")
            if availability and len(availability) > 0:
                if stage == "showing_alternative_slots":
                    default_time_failed = context.get("default_time_failed")
                    generic_time_failed = context.get("generic_time_failed")
                    if default_time_failed and generic_time_failed:
                        return f"The {generic_time_failed} slot ({default_time_failed}) is already taken. Here are other available {duration} slots for your '{title}' on {date_display}:"
                    else:
                        return f"Here are alternative {duration} slots available for your '{title}' on {date_display}. Please select a time:"
                else:
                    return f"Here are available {duration} slots for your '{title}' on {date_display}. Please select a time:"
            else:
                return f"I'm checking availability for your '{title}' on {date_display}..."
        elif stage == "no_availability":
            title = entities.get("title", "meeting")
            parsed_date = entities.get("parsed_date")
            if parsed_date:
                date_display = parsed_date.strftime('%A, %B %d')
            else:
                date_display = entities.get("date", "that day")
            return f"I couldn't find any available slots for your '{title}' on {date_display}. Would you like to try a different date?"
        elif stage == "no_alternatives":
            return "I couldn't find any alternative time slots for that day. Would you like to try a different date?"
        elif stage == "asking_attendees":
            title = entities.get("title", "meeting")
            selected_time = entities.get("selected_time", "")
            parsed_date = entities.get("parsed_date")
            if parsed_date:
                date_display = parsed_date.strftime('%A, %B %d')
            else:
                date_display = entities.get("date", "the selected day")
            if selected_time:
                return f"Great! I'll schedule your '{title}' for {selected_time} on {date_display}. Who should I invite? (Enter email addresses, or say 'no' if it's just you)"
            else:
                return f"Who should I invite to your '{title}' meeting? (Enter email addresses, or say 'no' if it's just you)"
        elif stage == "awaiting_confirmation":
            summary = context.get("booking_summary", {})
            title = summary.get("title", "Meeting")
            date = summary.get("date", "")
            time = summary.get("time", "")
            duration = summary.get("duration", "")
            attendees = summary.get("attendees", [])
            attendees_text = ", ".join(attendees) if attendees else "Just you"
            return f"Please confirm your booking:\n\n**{title}**\nDate: {date}\nTime: {time}\nDuration: {duration}\nAttendees: {attendees_text}\n\nShould I book this meeting?"
        elif stage == "booking_confirmed":
            if booking and booking.get('id'):
                return "✅ **Meeting Successfully Booked!**\n\nYour meeting has been added to your calendar. Invitations have been sent to all attendees."
            else:
                return "✅ Your meeting has been scheduled successfully!"
        elif stage == "booking_failed":
            return "❌ I couldn't complete the booking. Let's try again. What meeting would you like to schedule?"
        # Fallback for other stages
        return self._generate_fallback_response(context)

    async def _try_openrouter_response(self, conversation_history: List[Dict], context: Dict) -> str:
        """FIXED: Generate response using OpenRouter with NO placeholders"""
        import requests
        
        # FIXED: Enhanced system prompt to avoid placeholders and location
        system_prompt = """You are a helpful AI calendar assistant. Be concise and professional.
    Help users schedule meetings by asking for: title, duration, time, and attendees.
    Always confirm before booking. Never mention location or use placeholders like [Name], [Date], [Time], etc.
    Use actual data from the conversation. Be specific and helpful."""

        messages = [{"role": "system", "content": system_prompt}]
        
        # Add recent conversation context
        for msg in conversation_history[-3:]:
            messages.append({"role": msg["role"], "content": msg["content"]})

        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.openrouter_api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "google/gemini-flash-1.5",
                    "messages": messages,
                    "temperature": 0.7,
                    "max_tokens": 200
                },
                timeout=15
            )
            
            if response.status_code == 200:
                content = response.json()["choices"][0]["message"]["content"]
                # FIXED: Remove any placeholders that might slip through
                content = content.replace("[Name]", "").replace("[Date]", "").replace("[Time]", "").replace("[Location]", "")
                content = content.replace("in [Location]", "").replace("at [Location]", "")
                content = content.replace("[User Name]", "")
                return content.strip()
        except Exception as e:
            print(f"❌ OpenRouter response failed: {e}")
            return self._generate_fallback_response(context)

    async def _try_gemini_response(self, conversation_history: List[Dict], context: Dict) -> str:
        """Generate response using Gemini"""
        from google.genai import types

        prompt = "Generate a helpful response for booking a meeting. Be concise."
        
        try:
            response = self.client.models.generate_content(
                model="gemini-1.5-flash",
                contents=[
                    types.Content(
                        role="user",
                        parts=[types.Part(text=prompt)]
                    )
                ],
                config=types.GenerateContentConfig(
                    temperature=0.7,
                    max_output_tokens=200
                )
            )
            return response.text.strip()
        except Exception as e:
            print(f"❌ Gemini response failed: {e}")

        return self._generate_fallback_response(context)

    def _generate_fallback_response(self, context: Dict) -> str:
        """Generate fallback response"""
        stage = context.get("stage", "")
        
        fallback_responses = {
            "asking_title": "What would you like to discuss in this meeting?",
            "asking_duration": "How long should the meeting be?",
            "asking_specific_day": "Which day would you prefer?",
            "showing_slots": "I'm checking available time slots for you.",
            "showing_alternative_slots": "Here are some alternative times:",
            "no_availability": "No slots available for that day. Try another date?",
            "asking_attendees": "Who should I invite to this meeting?",
            "awaiting_confirmation": "Should I go ahead and book this meeting?",
            "booking_confirmed": "✅ Your meeting has been booked!",
            "booking_failed": "❌ I couldn't book the meeting. Let's try again."
        }
        
        return fallback_responses.get(stage, "How can I help you schedule a meeting?")
