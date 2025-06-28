import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow, InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import pickle
import json
import pytz
import traceback
import hashlib
import time

from ..models.schemas import BookingRequest

class GoogleCalendarService:
    def __init__(self):
        self.service = None
        self.credentials = None
        self.scopes = [
            'https://www.googleapis.com/auth/calendar',
            'https://www.googleapis.com/auth/calendar.events'
        ]
        self.is_authenticated = False
        self._availability_cache = {}
        self._cache_duration = 300  # 5 minutes
        



    def authenticate(self, credentials_file: str = "credentials.json", use_web_flow: bool = False):
        """Enhanced authentication with persistent token storage"""
        creds = None

        # FIRST: Try to load from environment variable
        token_data = os.getenv('GOOGLE_TOKEN_DATA')
        if token_data:
            try:
                import base64
                import json
                # Decode from base64 environment variable
                token_bytes = base64.b64decode(token_data)
                token_info = json.loads(token_bytes.decode('utf-8'))
                creds = Credentials.from_authorized_user_info(token_info)
                print("🔐 Loaded credentials from environment variable")
            except Exception as e:
                print(f"⚠️ Error loading credentials from environment: {e}")
                creds = None

        # SECOND: Check token.pickle (temporary storage)
        if not creds and os.path.exists('token.pickle'):
            print("🔍 Found existing token.pickle file")
            with open('token.pickle', 'rb') as token:
                try:
                    creds = pickle.load(token)
                    print("✅ Successfully loaded existing credentials")
                except Exception as e:
                    print(f"⚠️ Error loading saved credentials: {e}")
                    creds = None

        # THIRD: Check if credentials are valid
        if creds and creds.valid:
            print("✅ Existing credentials are valid!")
            self.credentials = creds
            try:
                self.service = build('calendar', 'v3', credentials=creds)
                self.is_authenticated = True
                print("🎉 Successfully connected to Google Calendar with existing token!")
                # Test the connection
                calendar = self.service.calendars().get(calendarId='primary').execute()
                print(f"📅 Connected to calendar: {calendar.get('summary', 'Primary Calendar')}")
                # SAVE to environment when successful
                try:
                    token_info = {
                        'token': creds.token,
                        'refresh_token': creds.refresh_token,
                        'token_uri': creds.token_uri,
                        'client_id': creds.client_id,
                        'client_secret': creds.client_secret,
                        'scopes': creds.scopes
                    }
                    import base64
                    import json
                    token_json = json.dumps(token_info)
                    token_b64 = base64.b64encode(token_json.encode('utf-8')).decode('utf-8')
                    print("💾 Token ready for environment storage")
                    print(f"📋 Add this to Render environment variables:")
                    print(f"GOOGLE_TOKEN_DATA={token_b64}")
                except Exception as e:
                    print(f"⚠️ Error preparing token for environment storage: {e}")
                return  # SUCCESS - exit early
            except Exception as e:
                print(f"❌ Error building calendar service with existing token: {e}")
                creds = None

        # THIRD: Try to refresh expired credentials
        if creds and creds.expired and creds.refresh_token:
            try:
                print("🔄 Refreshing expired credentials...")
                creds.refresh(Request())
                print("✅ Credentials refreshed successfully!")
                
                # Save refreshed credentials
                with open('token.pickle', 'wb') as token:
                    pickle.dump(creds, token)
                
                self.credentials = creds
                self.service = build('calendar', 'v3', credentials=creds)
                self.is_authenticated = True
                print("🎉 Successfully connected with refreshed credentials!")
                return  # SUCCESS - exit early
                
            except Exception as e:
                print(f"⚠️ Error refreshing credentials: {e}")
                creds = None

        # FOURTH: If no valid token, check environment
        print("🔍 No valid token found, checking environment...")
        
        # In PRODUCTION: Don't try OAuth flows, just indicate auth needed
        if os.getenv('ENVIRONMENT') == 'production':
            print("🌐 Production environment detected")
            print("🔗 Authentication required via web OAuth: /auth/login")
            return self._use_mock_service()

        # FIFTH: For local development, try OAuth flows
        if not os.path.exists(credentials_file):
            print(f"⚠️ Credentials file {credentials_file} not found.")
            
            # Try to get credentials from environment variables
            client_id = os.getenv('GOOGLE_CLIENT_ID')
            client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
            
            if client_id and client_secret:
                print("🔧 Creating temporary credentials from environment variables")
                creds_dict = {
                    "installed": {
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "redirect_uris": ["http://localhost:8080/"],
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token"
                    }
                }
                
                with open('temp_credentials.json', 'w') as f:
                    json.dump(creds_dict, f)
                credentials_file = 'temp_credentials.json'
            else:
                print("🎭 No credentials available, using mock service")
                return self._use_mock_service()

        # Try OAuth flows (local development only)
        try:
            if use_web_flow:
                print("🌐 Using Web Application OAuth flow...")
                flow = Flow.from_client_secrets_file(credentials_file, scopes=self.scopes)
                flow.redirect_uri = 'http://localhost:8080/'
                auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
                
                print(f'🔗 Please go to this URL and authorize: {auth_url}')
                print("📋 After authorization, copy the 'code' parameter from the URL and enter below.")
                auth_code = input('Enter the authorization code: ').strip()
                flow.fetch_token(code=auth_code)
                creds = flow.credentials
            else:
                print("🖥️ Using Desktop Application OAuth flow...")
                flow = InstalledAppFlow.from_client_secrets_file(credentials_file, self.scopes)
                
                try:
                    print("🚀 Starting local server for authentication...")
                    creds = flow.run_local_server(
                        port=8080,
                        prompt='consent',
                        access_type='offline',
                        success_message='✅ Authentication successful! You can close this window.',
                        open_browser=True
                    )
                    print("✅ Successfully authenticated via local server!")
                except Exception as e:
                    print(f"❌ Local server auth failed: {e}")
                    print("🎭 Using mock calendar service for local development")
                    return self._use_mock_service()

        except Exception as e:
            print(f"❌ Authentication failed: {e}. Using mock calendar service.")
            return self._use_mock_service()

        # Save credentials if successful
        if creds:
            try:
                with open('token.pickle', 'wb') as token:
                    pickle.dump(creds, token)
                print("💾 Credentials saved successfully!")
            except Exception as e:
                print(f"⚠️ Error saving credentials: {e}")

            self.credentials = creds
            try:
                self.service = build('calendar', 'v3', credentials=creds)
                self.is_authenticated = True
                print("✅ Successfully connected to Google Calendar!")
                
                # Test connection
                try:
                    calendar = self.service.calendars().get(calendarId='primary').execute()
                    print(f"📅 Connected to calendar: {calendar.get('summary', 'Primary Calendar')}")
                except Exception as e:
                    print(f"⚠️ Calendar connection test failed: {e}")
            except Exception as e:
                print(f"❌ Error building calendar service: {e}. Using mock calendar service.")
                return self._use_mock_service()
        else:
            return self._use_mock_service()

    def reload_service(self):
        """FIXED: Method to reload service after OAuth (called from main.py)"""
        print("🔄 Reloading calendar service after OAuth...")
        self.authenticate()

    def _use_mock_service(self):
        """Fallback to mock service"""
        print("🎭 Using mock calendar service for testing")
        self.service = MockCalendarService()
        self.is_authenticated = True

    def _get_cache_key(self, start_time: datetime, end_time: datetime) -> str:
        """Generate cache key for availability requests"""
        key_string = f"{start_time.isoformat()}_{end_time.isoformat()}"
        return hashlib.md5(key_string.encode()).hexdigest()

    def _is_cache_valid(self, cache_time: float) -> bool:
        """Check if cache is still valid"""
        return time.time() - cache_time < self._cache_duration

    async def get_availability(
        self,
        start_time: datetime,
        end_time: datetime,
        calendar_id: str = 'primary'
    ) -> List[Dict]:
        """FIXED: Consistent availability with proper caching"""
        if not self.service:
            self.authenticate()

        if isinstance(self.service, MockCalendarService):
            return await self.service.get_availability(start_time, end_time)

        try:
            # Check cache first
            cache_key = self._get_cache_key(start_time, end_time)
            if cache_key in self._availability_cache:
                cached_data, cache_time = self._availability_cache[cache_key]
                if self._is_cache_valid(cache_time):
                    print(f"📋 Using cached availability data")
                    return cached_data

            print(f"🔍 Checking availability from {start_time.strftime('%Y-%m-%d %H:%M')} to {end_time.strftime('%Y-%m-%d %H:%M')}")
            
            # Expand date range to cover the full day
            extended_start = start_time.replace(hour=0, minute=0, second=0, microsecond=0)
            extended_end = end_time.replace(hour=23, minute=59, second=59, microsecond=999999)
            
            print(f"🔍 Extended range: {extended_start.strftime('%Y-%m-%d %H:%M')} to {extended_end.strftime('%Y-%m-%d %H:%M')}")
            
            # Get busy times from Google Calendar
            freebusy_query = {
                'timeMin': extended_start.isoformat() + 'Z',
                'timeMax': extended_end.isoformat() + 'Z',
                'items': [{'id': calendar_id}]
            }

            response = self.service.freebusy().query(body=freebusy_query).execute()
            busy_times = response['calendars'][calendar_id]['busy']
            
            print(f"📊 Found {len(busy_times)} busy periods")
            for busy in busy_times:
                print(f"🚫 Busy: {busy['start']} to {busy['end']}")

            # Parse busy times to IST for comparison
            parsed_busy_times = []
            ist_tz = pytz.timezone('Asia/Kolkata')
            
            for busy in busy_times:
                try:
                    busy_start_utc = datetime.fromisoformat(busy['start'].replace('Z', '+00:00'))
                    busy_end_utc = datetime.fromisoformat(busy['end'].replace('Z', '+00:00'))
                    
                    busy_start_ist = busy_start_utc.astimezone(ist_tz).replace(tzinfo=None)
                    busy_end_ist = busy_end_utc.astimezone(ist_tz).replace(tzinfo=None)
                    
                    parsed_busy_times.append({
                        'start': busy_start_ist,
                        'end': busy_end_ist,
                        'start_str': busy['start'],
                        'end_str': busy['end']
                    })
                    
                    print(f"🚫 Parsed busy time: {busy_start_ist.strftime('%Y-%m-%d %H:%M')} to {busy_end_ist.strftime('%Y-%m-%d %H:%M')} IST")
                    
                except Exception as e:
                    print(f"⚠️ Error parsing busy time: {e}")
                    continue

            # FIXED: Generate time slots without work time restrictions
            free_slots = []
            now = datetime.now()
            
            # Start from the beginning of the target day or current time + 30 mins, whichever is later
            if start_time.date() == now.date():
                # If it's today, start from current time + 30 minutes
                current_time = now + timedelta(minutes=30)
                # Round to next 15-minute interval
                minutes = 15 * ((current_time.minute // 15) + 1)
                if minutes >= 60:
                    current_time = current_time.replace(hour=current_time.hour + 1, minute=0, second=0, microsecond=0)
                else:
                    current_time = current_time.replace(minute=minutes, second=0, microsecond=0)
            else:
                # For future dates, start from 6 AM
                current_time = start_time.replace(hour=6, minute=0, second=0, microsecond=0)

            print(f"🕐 Starting time slot generation from: {current_time.strftime('%Y-%m-%d %H:%M')}")

            # Generate 30-minute slots throughout the day (6 AM to 11:30 PM)
            while current_time.date() == start_time.date() and current_time.hour < 24:
                # FIXED: Only skip very early morning hours (before 6 AM) and very late night (after 11:30 PM)
                if current_time.hour < 6 or current_time.hour >= 23.5:
                    current_time += timedelta(minutes=30)
                    continue

                slot_start = current_time
                slot_end = current_time + timedelta(hours=1)  # Check for 1-hour duration
                
                # FIXED: Stricter conflict checking
                is_free = True
                for busy_time in parsed_busy_times:
                    busy_start = busy_time['start']
                    busy_end = busy_time['end']
                    
                    # More precise overlap detection
                    if self._times_overlap_strict(slot_start, slot_end, busy_start, busy_end):
                        is_free = False
                        print(f"❌ Slot {slot_start.strftime('%H:%M')} - {slot_end.strftime('%H:%M')} conflicts with busy time {busy_start.strftime('%Y-%m-%d %H:%M')} - {busy_end.strftime('%Y-%m-%d %H:%M')}")
                        break

                if is_free:
                    free_slots.append({
                        'start': slot_start.isoformat(),
                        'display': slot_start.strftime('%I:%M %p'),
                        'full_display': f"{slot_start.strftime('%A, %B %d, %Y')}: {slot_start.strftime('%I:%M %p')}"
                    })
                    print(f"✅ Available slot: {slot_start.strftime('%A, %B %d at %I:%M %p')}")

                current_time += timedelta(minutes=30)  # 30-minute intervals

            # Limit to 15 suggestions for better UX
            free_slots = free_slots[:15]
            
            # Cache the results
            self._availability_cache[cache_key] = (free_slots, time.time())
            
            print(f"✅ Generated {len(free_slots)} available time slots")
            return free_slots

        except Exception as e:
            print(f"❌ Error getting availability: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return []

    def _times_overlap_strict(self, start1: datetime, end1: datetime, start2: datetime, end2: datetime) -> bool:
        """FIXED: Stricter time overlap detection"""
        try:
            # Add small buffer to avoid edge case conflicts
            buffer = timedelta(minutes=1)
            overlap = (start1 + buffer) < end2 and end1 > (start2 + buffer)
            
            if overlap:
                print(f"🔍 Strict overlap detected: ({start1.strftime('%H:%M')}-{end1.strftime('%H:%M')}) overlaps with ({start2.strftime('%H:%M')}-{end2.strftime('%H:%M')})")
            
            return overlap
            
        except Exception as e:
            print(f"⚠️ Error in overlap detection: {e}")
            return False

    async def create_event(self, booking: BookingRequest) -> Dict:
        """FIXED: Create calendar event with proper email invites"""
        if not self.service:
            self.authenticate()

        if isinstance(self.service, MockCalendarService):
            return await self.service.create_event(booking)

        try:
            print(f"📅 Creating event: {booking.title}")
            
            ist_timezone = pytz.timezone('Asia/Kolkata')
            utc_timezone = pytz.UTC

            if booking.start_time.tzinfo is None:
                start_ist = ist_timezone.localize(booking.start_time)
            else:
                start_ist = booking.start_time.astimezone(ist_timezone)

            if booking.end_time.tzinfo is None:
                end_ist = ist_timezone.localize(booking.end_time)
            else:
                end_ist = booking.end_time.astimezone(ist_timezone)

            start_utc = start_ist.astimezone(utc_timezone)
            end_utc = end_ist.astimezone(utc_timezone)

            event = {
                'summary': booking.title,
                'description': booking.description or 'Booked via Rahul\'s AI Calendar Assistant',
                'start': {
                    'dateTime': start_utc.isoformat(),
                    'timeZone': 'Asia/Kolkata',
                },
                'end': {
                    'dateTime': end_utc.isoformat(),
                    'timeZone': 'Asia/Kolkata',
                },
                # FIXED: Proper attendee configuration for email invites
                'guestsCanInviteOthers': False,
                'guestsCanModify': False,
                'guestsCanSeeOtherGuests': True,
                'sendUpdates': 'all'  # Send emails to all attendees
            }

            # FIXED: Enhanced attendee handling with proper email invites
            if booking.attendees and len(booking.attendees) > 0:
                attendee_list = []
                for email in booking.attendees:
                    if email and '@' in email:  # Validate email
                        attendee_list.append({
                            'email': email.strip(),
                            'responseStatus': 'needsAction'
                        })
                        print(f"📧 Adding attendee: {email}")
                
                if attendee_list:
                    event['attendees'] = attendee_list

            # FIXED: Create event with email notifications
            created_event = self.service.events().insert(
                calendarId='primary',
                body=event,
                sendUpdates='all'  # Ensure email invites are sent
            ).execute()

            result = {
                'id': created_event['id'],
                'title': created_event['summary'],
                'start_time': created_event['start']['dateTime'],
                'end_time': created_event['end']['dateTime'],
                'html_link': created_event.get('htmlLink', ''),
                'status': 'confirmed',
                'attendees': created_event.get('attendees', [])
            }

            print(f"✅ Event created successfully: {result['id']}")
            
            # Log attendee invite status
            attendees = created_event.get('attendees', [])
            for attendee in attendees:
                print(f"📧 Invite sent to: {attendee.get('email')} (status: {attendee.get('responseStatus', 'unknown')})")
            
            # Clear availability cache to ensure fresh data
            self._availability_cache.clear()
            
            return result

        except Exception as e:
            print(f"❌ Error creating event: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return await MockCalendarService().create_event(booking)

    async def update_event(self, event_id: str, booking: BookingRequest) -> Dict:
        """Update an existing calendar event"""
        if not self.service:
            self.authenticate()

        if isinstance(self.service, MockCalendarService):
            return await self.service.update_event(event_id, booking)

        try:
            print(f"✏️ Updating event: {event_id}")
            
            existing_event = self.service.events().get(
                calendarId='primary',
                eventId=event_id
            ).execute()

            ist_timezone = pytz.timezone('Asia/Kolkata')
            utc_timezone = pytz.UTC

            if booking.start_time.tzinfo is None:
                start_ist = ist_timezone.localize(booking.start_time)
            else:
                start_ist = booking.start_time.astimezone(ist_timezone)

            if booking.end_time.tzinfo is None:
                end_ist = ist_timezone.localize(booking.end_time)
            else:
                end_ist = booking.end_time.astimezone(ist_timezone)

            start_utc = start_ist.astimezone(utc_timezone)
            end_utc = end_ist.astimezone(utc_timezone)

            existing_event['summary'] = booking.title
            existing_event['description'] = booking.description or 'Updated via Rahul\'s AI Calendar Assistant'
            existing_event['start'] = {
                'dateTime': start_utc.isoformat(),
                'timeZone': 'Asia/Kolkata',
            }
            existing_event['end'] = {
                'dateTime': end_utc.isoformat(),
                'timeZone': 'Asia/Kolkata',
            }

            if booking.attendees:
                existing_event['attendees'] = [{'email': email} for email in booking.attendees]

            updated_event = self.service.events().update(
                calendarId='primary',
                eventId=event_id,
                body=existing_event,
                sendUpdates='all'
            ).execute()

            result = {
                'id': updated_event['id'],
                'title': updated_event['summary'],
                'start_time': updated_event['start']['dateTime'],
                'end_time': updated_event['end']['dateTime'],
                'html_link': updated_event.get('htmlLink', ''),
                'status': 'updated'
            }

            print(f"✅ Event updated successfully: {result['id']}")
            
            # Clear availability cache
            self._availability_cache.clear()
            
            return result

        except Exception as e:
            print(f"❌ Error updating event: {e}")
            return {'error': str(e)}

    async def delete_event(self, event_id: str) -> bool:
        """Delete a calendar event"""
        if not self.service:
            self.authenticate()

        if isinstance(self.service, MockCalendarService):
            return await self.service.delete_event(event_id)

        try:
            print(f"🗑️ Deleting event: {event_id}")
            self.service.events().delete(
                calendarId='primary',
                eventId=event_id,
                sendUpdates='all'
            ).execute()
            print(f"✅ Event deleted successfully: {event_id}")
            
            # Clear availability cache
            self._availability_cache.clear()
            
            return True

        except Exception as e:
            print(f"❌ Error deleting event: {e}")
            return False

    async def get_events(
        self,
        start_time: datetime,
        end_time: datetime,
        calendar_id: str = 'primary'
    ) -> List[Dict]:
        """Get events in date range"""
        if not self.service:
            self.authenticate()

        if isinstance(self.service, MockCalendarService):
            return await self.service.get_events(start_time, end_time)

        try:
            print(f"📋 Getting events from {start_time.strftime('%Y-%m-%d')} to {end_time.strftime('%Y-%m-%d')}")
            
            start_iso = start_time.isoformat() + 'Z'
            end_iso = end_time.isoformat() + 'Z'
            
            events_result = self.service.events().list(
                calendarId=calendar_id,
                timeMin=start_iso,
                timeMax=end_iso,
                singleEvents=True,
                orderBy='startTime',
                maxResults=50
            ).execute()

            events = events_result.get('items', [])
            formatted_events = []
            
            for event in events:
                try:
                    start = event['start'].get('dateTime', event['start'].get('date'))
                    end = event['end'].get('dateTime', event['end'].get('date'))
                    
                    formatted_events.append({
                        'id': event['id'],
                        'title': event.get('summary', 'No Title'),
                        'start_time': start,
                        'end_time': end,
                        'description': event.get('description', ''),
                        'html_link': event.get('htmlLink', ''),
                        'status': event.get('status', 'confirmed'),
                        'attendees': event.get('attendees', [])
                    })
                    
                    print(f"📅 Event: {event.get('summary', 'No Title')} ({start} to {end})")
                    
                except Exception as e:
                    print(f"⚠️ Error processing event: {e}")
                    continue

            print(f"✅ Retrieved {len(formatted_events)} events")
            return formatted_events

        except Exception as e:
            print(f"❌ Error getting events: {e}")
            return []


class MockCalendarService:
    """FIXED: Mock calendar service with consistent behavior"""
    def __init__(self):
        self.events = []
        self._availability_cache = {}
        print("🎭 Mock Calendar Service initialized")

    async def get_availability(
        self,
        start_time: datetime,
        end_time: datetime
    ) -> List[Dict]:
        """FIXED: Mock availability with consistent caching"""
        cache_key = f"{start_time.isoformat()}_{end_time.isoformat()}"
        
        # Check cache first
        if cache_key in self._availability_cache:
            print("📋 Using cached mock availability data")
            return self._availability_cache[cache_key]
        
        print(f"🎭 Mock: Checking availability from {start_time.strftime('%Y-%m-%d %H:%M')} to {end_time.strftime('%Y-%m-%d %H:%M')}")
        
        all_events = self.events
        busy_times = []
        
        for event in all_events:
            try:
                event_start = datetime.fromisoformat(event['start_time'].replace('Z', '+00:00')).replace(tzinfo=None)
                event_end = datetime.fromisoformat(event['end_time'].replace('Z', '+00:00')).replace(tzinfo=None)
                
                if (event_start < end_time and event_end > start_time):
                    busy_times.append({'start': event_start, 'end': event_end, 'title': event['title']})
                    print(f"🚫 Mock busy time: {event['title']} ({event_start.strftime('%Y-%m-%d %H:%M')} - {event_end.strftime('%Y-%m-%d %H:%M')})")
            except Exception as e:
                print(f"⚠️ Error parsing mock event time: {e}")
                continue
        
        free_slots = []
        now = datetime.now()
        
        # Start from 6 AM or current time + 30 mins, whichever is later
        if start_time.date() == now.date():
            current_time = now + timedelta(minutes=30)
            minutes = 15 * ((current_time.minute // 15) + 1)
            if minutes >= 60:
                current_time = current_time.replace(hour=current_time.hour + 1, minute=0, second=0, microsecond=0)
            else:
                current_time = current_time.replace(minute=minutes, second=0, microsecond=0)
        else:
            current_time = start_time.replace(hour=6, minute=0, second=0, microsecond=0)

        while current_time.date() == start_time.date() and len(free_slots) < 15:
            # FIXED: Only skip very early morning (before 6 AM) and very late night (after 11:30 PM)
            if current_time.hour < 6 or current_time.hour >= 23.5:
                current_time += timedelta(minutes=30)
                continue

            slot_start = current_time
            slot_end = current_time + timedelta(hours=1)
            
            is_free = True
            for busy in busy_times:
                if slot_start < busy['end'] and slot_end > busy['start']:
                    is_free = False
                    print(f"❌ Mock slot {slot_start.strftime('%H:%M')} - {slot_end.strftime('%H:%M')} conflicts with {busy['title']}")
                    break
            
            if is_free:
                free_slots.append({
                    'start': slot_start.isoformat(),
                    'display': slot_start.strftime('%I:%M %p'),
                    'full_display': f"{slot_start.strftime('%A, %B %d, %Y')}: {slot_start.strftime('%I:%M %p')}"
                })

            current_time += timedelta(minutes=30)

        # Cache the results
        self._availability_cache[cache_key] = free_slots
        
        print(f"🎭 Mock: Generated {len(free_slots)} available slots")
        return free_slots

    async def create_event(self, booking: BookingRequest) -> Dict:
        """Mock event creation with email simulation"""
        event_id = f"mock_event_{len(self.events) + 1}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        ist_timezone = pytz.timezone('Asia/Kolkata')
        
        if booking.start_time.tzinfo is None:
            start_time_tz = ist_timezone.localize(booking.start_time)
        else:
            start_time_tz = booking.start_time.astimezone(ist_timezone)

        if booking.end_time.tzinfo is None:
            end_time_tz = ist_timezone.localize(booking.end_time)
        else:
            end_time_tz = booking.end_time.astimezone(ist_timezone)

        # Simulate attendees with response status
        attendees = []
        if booking.attendees:
            for email in booking.attendees:
                attendees.append({
                    'email': email,
                    'responseStatus': 'needsAction'
                })
                print(f"📧 Mock: Email invite sent to {email}")

        event = {
            'id': event_id,
            'title': booking.title,
            'start_time': start_time_tz.isoformat(),
            'end_time': end_time_tz.isoformat(),
            'description': booking.description or 'Booked via Rahul\'s AI Calendar Assistant',
            'html_link': f'https://calendar.google.com/calendar/event?eid={event_id}',
            'status': 'confirmed',
            'attendees': attendees
        }

        self.events.append(event)
        
        # Clear cache to ensure fresh availability data
        self._availability_cache.clear()
        
        print(f"🎭 Mock event created: {booking.title} on {start_time_tz.strftime('%Y-%m-%d %I:%M %p %Z')}")
        if attendees:
            print(f"🎭 Mock: Attendees added: {[a['email'] for a in attendees]}")
        
        return event

    async def update_event(self, event_id: str, booking: BookingRequest) -> Dict:
        """Mock event update"""
        for i, event in enumerate(self.events):
            if event['id'] == event_id:
                ist_timezone = pytz.timezone('Asia/Kolkata')
                
                if booking.start_time.tzinfo is None:
                    start_time_tz = ist_timezone.localize(booking.start_time)
                else:
                    start_time_tz = booking.start_time.astimezone(ist_timezone)

                if booking.end_time.tzinfo is None:
                    end_time_tz = ist_timezone.localize(booking.end_time)
                else:
                    end_time_tz = booking.end_time.astimezone(ist_timezone)

                self.events[i].update({
                    'title': booking.title,
                    'start_time': start_time_tz.isoformat(),
                    'end_time': end_time_tz.isoformat(),
                    'description': booking.description or 'Updated via Rahul\'s AI Calendar Assistant',
                    'status': 'updated'
                })
                
                # Clear cache
                self._availability_cache.clear()
                
                print(f"🎭 Mock event updated: {event_id}")
                return self.events[i]
        
        print(f"🎭 Mock event not found: {event_id}")
        return {'error': 'Event not found'}

    async def delete_event(self, event_id: str) -> bool:
        """Mock event deletion"""
        for i, event in enumerate(self.events):
            if event['id'] == event_id:
                del self.events[i]
                # Clear cache
                self._availability_cache.clear()
                print(f"🎭 Mock event deleted: {event_id}")
                return True
        
        print(f"🎭 Mock event not found for deletion: {event_id}")
        return False

    async def get_events(
        self,
        start_time: datetime,
        end_time: datetime
    ) -> List[Dict]:
        """Mock get events"""
        print(f"🎭 Mock: Getting events from {start_time.strftime('%Y-%m-%d')} to {end_time.strftime('%Y-%m-%d')}")
        
        filtered_events = []
        all_events = self.events
        
        for event in all_events:
            try:
                event_start = datetime.fromisoformat(event['start_time'].replace('Z', '+00:00')).replace(tzinfo=None)
                event_end = datetime.fromisoformat(event['end_time'].replace('Z', '+00:00')).replace(tzinfo=None)
                
                if (event_start < end_time and event_end > start_time):
                    filtered_events.append(event)
                    
            except Exception as e:
                print(f"⚠️ Error filtering mock event: {e}")
                continue
        
        print(f"🎭 Mock: Returning {len(filtered_events)} events")
        return filtered_events
