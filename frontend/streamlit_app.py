import streamlit as st
import requests
import json
from datetime import datetime
from typing import Dict, List
import os
import pytz
import time

# Page configuration
st.set_page_config(
    page_title="AI Calendar Assistant",
    page_icon="📅",
    layout="wide",
    initial_sidebar_state="expanded"
)


# Configuration
def get_backend_url():
    """Get backend URL based on environment"""
    # Check if running in Streamlit Cloud
    if hasattr(st, 'secrets') and 'BACKEND_URL' in st.secrets:
        return st.secrets['BACKEND_URL']
    # Check environment variable
    backend_url = os.getenv('BACKEND_URL')
    if backend_url:
        return backend_url
    # Production backend URL
    return "https://ai-calendar-assistant-grdx.onrender.com"

BACKEND_URL = get_backend_url()
SESSION_ID = "streamlit_session"

def init_session_state():
    """Initialize session state variables"""
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "backend_url" not in st.session_state:
        st.session_state.backend_url = BACKEND_URL
    if "last_booking_message_index" not in st.session_state:
        st.session_state.last_booking_message_index = -1
    if "last_suggestion_message_index" not in st.session_state:
        st.session_state.last_suggestion_message_index = -1
    if "button_clicked" not in st.session_state:
        st.session_state.button_clicked = False
    # Track which booking has shown balloons to prevent repetition
    if "balloons_shown_for_booking" not in st.session_state:
        st.session_state.balloons_shown_for_booking = set()
    # FIXED: Add state for handling time slot selection
    if "pending_time_selection" not in st.session_state:
        st.session_state.pending_time_selection = None
    if "confirmation_pending" not in st.session_state:
        st.session_state.confirmation_pending = None

def get_ist_time() -> datetime:
    """Get current time in IST"""
    ist_tz = pytz.timezone('Asia/Kolkata')
    utc_now = datetime.utcnow()
    return utc_now.replace(tzinfo=pytz.UTC).astimezone(ist_tz).replace(tzinfo=None)

def send_message_to_backend(message: str) -> Dict:
    """Send message to FastAPI backend with startup handling"""
    try:
        # FIXED: Use IST timestamp
        ist_time = get_ist_time()
        payload = {
            "role": "user",
            "content": message,
            "timestamp": ist_time.isoformat()
        }
        
        response = requests.post(
            f"{st.session_state.backend_url}/chat",
            json=payload,
            params={"session_id": SESSION_ID},
            timeout=30
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            return {
                "message": f"Error: {response.status_code} - {response.text}",
                "booking_data": None,
                "suggested_times": [],
                "requires_confirmation": False
            }
            
    except requests.exceptions.ReadTimeout as e:
        # FIXED: Handle backend startup timeout with user-friendly message
        return handle_backend_startup_error()
    except requests.exceptions.ConnectTimeout as e:
        # FIXED: Handle connection timeout (service starting up)
        return handle_backend_startup_error()
    except requests.exceptions.ConnectionError as e:
        error_msg = str(e).lower()
        if 'timeout' in error_msg or 'timed out' in error_msg:
            return handle_backend_startup_error()
        else:
            return {
                "message": f"Connection error: {str(e)}. Please check if the backend is running.",
                "booking_data": None,
                "suggested_times": [],
                "requires_confirmation": False
            }
    except requests.exceptions.RequestException as e:
        error_msg = str(e).lower()
        if 'timeout' in error_msg or 'timed out' in error_msg:
            return handle_backend_startup_error()
        else:
            return {
                "message": f"Connection error: {str(e)}. Please check if the backend is running.",
                "booking_data": None,
                "suggested_times": [],
                "requires_confirmation": False
            }

def handle_backend_startup_error() -> Dict:
    """FIXED: User-friendly message for backend startup delays"""
    return {
        "message": "🚀 **Service Starting Up**\n\n"
                  "The AI Calendar Assistant is waking up from sleep mode. This happens on free hosting services after periods of inactivity.\n\n"
                  "⏱️ **Please wait 30-60 seconds and try again.**\n\n"
                  "💡 **What's happening?**\n"
                  "- The backend service is starting up\n"
                  "- This usually takes 30-50 seconds\n"
                  "- Once it's running, responses will be fast\n\n"
                  "🔄 **Please try sending your message again in a moment!**",
        "booking_data": None,
        "suggested_times": [],
        "requires_confirmation": False,
        "is_startup_error": True
    }

def check_backend_health() -> Dict:
    """Check if backend is healthy and ready"""
    try:
        response = requests.get(
            f"{st.session_state.backend_url}/health",
            timeout=10
        )
        if response.status_code == 200:
            return {"status": "healthy", "data": response.json()}
        else:
            return {"status": "unhealthy", "error": f"Status: {response.status_code}"}
    except requests.exceptions.RequestException as e:
        return {"status": "unhealthy", "error": str(e)}

def display_startup_helper():
    """FIXED: Display helpful startup information"""
    st.warning("🚀 **Backend Service Starting**")
    
    # Create a progress bar simulation
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    # Simulate startup progress
    for i in range(101):
        progress_bar.progress(i)
        if i < 30:
            status_text.text("🔄 Waking up the service...")
        elif i < 60:
            status_text.text("⚙️ Initializing AI components...")
        elif i < 90:
            status_text.text("🔗 Connecting to Google Calendar...")
        else:
            status_text.text("✅ Almost ready...")
        time.sleep(0.5)  # 50 seconds total
    
    # Check if service is ready
    health_status = check_backend_health()
    
    if health_status["status"] == "healthy":
        st.success("✅ **Service is now ready!** You can send your message.")
        progress_bar.empty()
        status_text.empty()
    else:
        st.warning("⏳ Service still starting up. Please wait a bit more and try again.")
        progress_bar.empty()
        status_text.empty()

def enhanced_chat_input_handler():
    """FIXED: Enhanced chat input with startup detection"""
    if prompt := st.chat_input("Type your message here... (e.g., 'Schedule a meeting tomorrow at 3 PM')"):
        # FIXED: Use IST timestamp
        ist_time = get_ist_time()
        
        # Add user message to chat
        st.session_state.messages.append({
            "role": "user",
            "content": prompt,
            "timestamp": ist_time
        })
        
        # Display user message immediately
        with st.chat_message("user"):
            st.markdown(prompt)
            st.caption(f"🕐 {ist_time.strftime('%I:%M %p')} IST")
        
        # Get response from backend with startup handling
        with st.chat_message("assistant"):
            with st.spinner("Processing your request..."):
                response = send_message_to_backend(prompt)
            
            # FIXED: Check if this is a startup error
            if response.get("is_startup_error"):
                st.markdown(response["message"])
                
                # Show startup helper
                if st.button("🔄 Wait for Service Startup (50 seconds)", key="startup_wait"):
                    display_startup_helper()
                
                # Show manual retry option
                st.info("💡 **Alternative**: Wait 1-2 minutes and refresh the page, then try again.")
                
            else:
                # Normal response handling
                st.markdown(response["message"])
                
                # Handle response components properly
                message_index = len(st.session_state.messages)
                
                # Check what to display
                has_booking = response.get("booking_data") and response.get("booking_data", {}).get("id")
                has_suggestions = response.get("suggested_times") and len(response.get("suggested_times", [])) > 0
                needs_confirmation = response.get("requires_confirmation", False)
                
                # Show booking confirmation if we have a real booking
                if has_booking:
                    booking_id = response["booking_data"].get("id", "")
                    display_booking_confirmation(response["booking_data"], booking_id)
                    st.session_state.last_booking_message_index = message_index
                
                # Show confirmation prompt if needed (and no booking)
                elif needs_confirmation and not has_booking:
                    display_confirmation_prompt(message_index)
                
                # Show suggested times if available (and no booking or confirmation)
                elif has_suggestions and not has_booking and not needs_confirmation:
                    display_suggested_times(response["suggested_times"], message_index)
                    st.session_state.last_suggestion_message_index = message_index
        
        # Add assistant response to session
        st.session_state.messages.append({
            "role": "assistant",
            "content": response["message"],
            "timestamp": ist_time,
            "booking_data": response.get("booking_data"),
            "suggested_times": response.get("suggested_times", []),
            "requires_confirmation": response.get("requires_confirmation", False)
        })

def display_connection_status():
    """FIXED: Display connection status in sidebar"""
    with st.sidebar:
        st.header("🔗 Connection Status")
        
        if st.button("🔍 Test Backend Connection"):
            with st.spinner("Testing connection..."):
                health_status = check_backend_health()
                
                if health_status["status"] == "healthy":
                    st.success("✅ Backend is healthy and ready!")
                    
                    # Show health details
                    health_data = health_status.get("data", {})
                    if health_data:
                        calendar_status = health_data.get("calendar_status", "unknown")
                        
                        if calendar_status == "authenticated":
                            st.success("📅 Google Calendar: Connected")
                        elif calendar_status == "mock":
                            st.warning("📅 Google Calendar: Not connected (using mock)")
                            st.info("Click [here](https://ai-calendar-assistant-grdx.onrender.com/auth/login) to connect your calendar")
                        
                        server_time = health_data.get("server_time", "Unknown")
                        st.info(f"🕐 Server Time: {server_time}")
                else:
                    st.error("❌ Backend connection failed")
                    st.error(f"Error: {health_status.get('error', 'Unknown error')}")
                    
                    # Show startup instructions
                    st.warning("🚀 **If the service is starting up:**")
                    st.write("1. Wait 30-60 seconds")
                    st.write("2. Try the test again")
                    st.write("3. If it still fails, wait 2 minutes and refresh the page")

def display_booking_confirmation(booking_data: Dict, booking_id: str):
    """Display booking confirmation with controlled balloon animation"""
    if booking_data and booking_data.get("id"):
        st.success("✅ Appointment Successfully Booked!")
        
        with st.expander("📋 Booking Details", expanded=True):
            col1, col2 = st.columns(2)
            
            with col1:
                st.write("**📝 Title:**", booking_data.get("title", "Meeting"))
                
                # Better datetime formatting
                start_time = booking_data.get("start_time", "N/A")
                if start_time != "N/A":
                    try:
                        # Handle different datetime formats
                        if isinstance(start_time, str):
                            if start_time.endswith('Z'):
                                dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                            else:
                                dt = datetime.fromisoformat(start_time)
                        else:
                            dt = start_time
                        
                        # Convert to IST and format nicely
                        formatted_time = dt.strftime('%A, %B %d, %Y at %I:%M %p IST')
                        st.write("**📅 Date & Time:**", formatted_time)
                    except Exception as e:
                        st.write("**📅 Date & Time:**", start_time)
                else:
                    st.write("**📅 Date & Time:**", "Not specified")
            
            with col2:
                event_id = booking_data.get("id", "")
                if event_id:
                    st.write("**🆔 Event ID:**", event_id)
                
                status = booking_data.get("status", "confirmed")
                st.write("**📊 Status:**", status.title())
                
                html_link = booking_data.get("html_link", "")
                if html_link:
                    st.markdown(f"[📅 View in Google Calendar]({html_link})", unsafe_allow_html=True)
                else:
                    st.info("📅 Event added to your calendar")
        
        # Only show balloons once per booking
        if booking_id and booking_id not in st.session_state.balloons_shown_for_booking:
            st.balloons()
            st.session_state.balloons_shown_for_booking.add(booking_id)
            print(f"🎉 Balloons shown for booking: {booking_id}")
        
        st.success("🎉 Your appointment has been added to your Google Calendar!")

def handle_time_selection_callback(time_slot: str):
    """FIXED: Callback function for time slot selection"""
    print(f"🕐 Time slot selected via callback: {time_slot}")
    st.session_state.pending_time_selection = time_slot

def process_pending_time_selection():
    """FIXED: Process pending time selection"""
    if st.session_state.pending_time_selection:
        time_slot = st.session_state.pending_time_selection
        st.session_state.pending_time_selection = None
        
        print(f"🔄 Processing time selection: {time_slot}")
        
        # FIXED: Use IST timestamp
        ist_time = get_ist_time()
        
        # Add user selection to messages
        st.session_state.messages.append({
            "role": "user",
            "content": time_slot,
            "timestamp": ist_time,  # FIXED: IST timestamp
            "is_time_selection": True
        })
        
        # Process the selection
        response = send_message_to_backend(time_slot)
        
        # Add assistant response
        st.session_state.messages.append({
            "role": "assistant",
            "content": response["message"],
            "timestamp": ist_time,  # FIXED: IST timestamp
            "booking_data": response.get("booking_data"),
            "suggested_times": response.get("suggested_times", []),
            "requires_confirmation": response.get("requires_confirmation", False)
        })
        
        # Update tracking indices
        if response.get("booking_data"):
            st.session_state.last_booking_message_index = len(st.session_state.messages) - 1
        
        if response.get("suggested_times"):
            st.session_state.last_suggestion_message_index = len(st.session_state.messages) - 1
        
        # Trigger rerun
        st.rerun()

def display_suggested_times(suggested_times: List[str], message_index: int):
    """FIXED: Working time slot buttons with proper callback handling"""
    if suggested_times and len(suggested_times) > 0:
        st.info("🕐 **Available Time Slots**")
        st.write("Click on a time slot to select it:")
        
        # Create columns dynamically based on number of slots
        num_cols = min(len(suggested_times), 3)
        cols = st.columns(num_cols)
        
        for i, time_slot in enumerate(suggested_times):
            with cols[i % num_cols]:
                # FIXED: Use on_click callback instead of conditional logic
                unique_key = f"slot_{message_index}_{i}_{hash(time_slot)}"
                st.button(
                    f"📅 {time_slot}",
                    key=unique_key,
                    help=f"Select {time_slot} for your appointment",
                    use_container_width=True,
                    on_click=handle_time_selection_callback,
                    args=(time_slot,)
                )

def handle_confirmation_callback(response: str):
    """FIXED: Callback function for confirmation"""
    print(f"✅ Confirmation response via callback: {response}")
    st.session_state.confirmation_pending = response

def process_pending_confirmation():
    """FIXED: Process pending confirmation"""
    if st.session_state.confirmation_pending:
        user_message = st.session_state.confirmation_pending
        st.session_state.confirmation_pending = None
        
        print(f"🔄 Processing confirmation: {user_message}")
        
        # FIXED: Use IST timestamp
        ist_time = get_ist_time()
        
        st.session_state.messages.append({
            "role": "user",
            "content": user_message,
            "timestamp": ist_time,  # FIXED: IST timestamp
            "is_confirmation": True
        })
        
        response = send_message_to_backend(user_message)
        st.session_state.messages.append({
            "role": "assistant",
            "content": response["message"],
            "timestamp": ist_time,  # FIXED: IST timestamp
            "booking_data": response.get("booking_data"),
            "suggested_times": response.get("suggested_times", []),
            "requires_confirmation": response.get("requires_confirmation", False)
        })
        
        if response.get("booking_data"):
            st.session_state.last_booking_message_index = len(st.session_state.messages) - 1
        
        st.rerun()

def display_confirmation_prompt(message_index: int):
    """FIXED: Display confirmation prompt with callback handling"""
    st.warning("⚠️ **Confirmation Required**")
    st.write("Please confirm if you'd like to proceed with this booking:")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.button(
            "✅ Yes, Book It",
            key=f"confirm_yes_{message_index}",
            type="primary",
            use_container_width=True,
            on_click=handle_confirmation_callback,
            args=("yes",)
        )
    
    with col2:
        st.button(
            "❌ Cancel",
            key=f"confirm_no_{message_index}",
            use_container_width=True,
            on_click=handle_confirmation_callback,
            args=("no, cancel",)
        )

def should_show_suggestions(message_index: int, message: Dict) -> bool:
    """Smarter logic for when to show suggestions"""
    # Don't show if no suggestions
    if not message.get("suggested_times"):
        return False
    
    # Don't show if there's booking data
    if message.get("booking_data"):
        return False
    
    # Only show for assistant messages
    if message["role"] != "assistant":
        return False
    
    # Don't show if AI claims to have created/booked something
    message_content = message.get("content", "").lower()
    booking_claim_phrases = [
        "i've created", "i've made", "i've added", "created the event",
        "added to your calendar", "event created", "successfully booked",
        "appointment has been", "i'm creating", "let me create", "i've now booked"
    ]
    
    if any(phrase in message_content for phrase in booking_claim_phrases):
        print(f"🚫 Not showing time slots - AI claims booking is done: {message_content[:50]}...")
        return False
    
    # Check if this is the most recent message with suggestions
    for later_index in range(message_index + 1, len(st.session_state.messages)):
        later_msg = st.session_state.messages[later_index]
        if later_msg["role"] == "assistant" and (
            later_msg.get("suggested_times") or
            later_msg.get("booking_data") or
            later_msg.get("requires_confirmation")
        ):
            return False
    
    return True

def should_show_booking(message_index: int, message: Dict) -> bool:
    """Determine if booking confirmation should be shown"""
    # Must have booking data with valid ID
    if not message.get("booking_data") or not message.get("booking_data", {}).get("id"):
        return False
    
    # Only show for assistant messages
    if message["role"] != "assistant":
        return False
    
    # Only show for the most recent booking message
    return message_index == st.session_state.last_booking_message_index or message_index == len(st.session_state.messages) - 1

def should_show_confirmation(message_index: int, message: Dict) -> bool:
    """Determine if confirmation prompt should be shown"""
    # Must require confirmation
    if not message.get("requires_confirmation"):
        return False
    
    # Only show for assistant messages
    if message["role"] != "assistant":
        return False
    
    # Don't show if there's already booking data
    if message.get("booking_data"):
        return False
    
    # Only show for the most recent confirmation request
    for later_index in range(message_index + 1, len(st.session_state.messages)):
        later_msg = st.session_state.messages[later_index]
        if later_msg["role"] == "assistant" and (
            later_msg.get("booking_data") or
            later_msg.get("requires_confirmation")
        ):
            return False
    
    return True

def main():
    """Main Streamlit application with enhanced startup handling"""
    init_session_state()
    
    # FIXED: Process pending actions at the start of each run
    process_pending_time_selection()
    process_pending_confirmation()
    
    # Header
    st.title("🤖 AI Calendar Booking Assistant")
    st.write("I can help you schedule appointments, check availability, and manage your calendar!")
    
    # FIXED: Show startup notice if this is the first visit
    if len(st.session_state.messages) == 0:
        st.info("💡 **First time today?** The service might take 30-60 seconds to start up if it's been sleeping. Please be patient!")
    
    # Sidebar with connection status
    with st.sidebar:
        # FIXED: Add connection status
        display_connection_status()
        
        st.divider()
        
        # Quick actions
        st.header("⚡ Quick Actions")
        
        if st.button("📅 Check Today's Availability", use_container_width=True):
            quick_message = "What's my availability today?"
            st.session_state.messages.append({
                "role": "user",
                "content": quick_message,
                "timestamp": get_ist_time()
            })
            
            response = send_message_to_backend(quick_message)
            st.session_state.messages.append({
                "role": "assistant",
                "content": response["message"],
                "timestamp": get_ist_time(),
                "suggested_times": response.get("suggested_times", [])
            })
            st.rerun()
        
        if st.button("📞 Schedule a Call", use_container_width=True):
            quick_message = "I want to schedule a call"
            st.session_state.messages.append({
                "role": "user",
                "content": quick_message,
                "timestamp": get_ist_time()
            })
            
            response = send_message_to_backend(quick_message)
            st.session_state.messages.append({
                "role": "assistant",
                "content": response["message"],
                "timestamp": get_ist_time(),
                "suggested_times": response.get("suggested_times", [])
            })
            st.rerun()
        
        if st.button("🗓️ Schedule Meeting Tomorrow", use_container_width=True):
            quick_message = "Book a meeting tomorrow"
            st.session_state.messages.append({
                "role": "user",
                "content": quick_message,
                "timestamp": get_ist_time()
            })
            
            response = send_message_to_backend(quick_message)
            st.session_state.messages.append({
                "role": "assistant",
                "content": response["message"],
                "timestamp": get_ist_time(),
                "suggested_times": response.get("suggested_times", [])
            })
            st.rerun()
        
        st.divider()
        
        # Conversation management
        st.header("💬 Conversation")
        
        if st.button("🗑️ Clear Conversation", use_container_width=True):
            st.session_state.messages = []
            st.session_state.last_booking_message_index = -1
            st.session_state.last_suggestion_message_index = -1
            st.session_state.balloons_shown_for_booking = set()
            st.session_state.pending_time_selection = None
            st.session_state.confirmation_pending = None
            st.rerun()
        
        # Show conversation stats
        if st.session_state.messages:
            st.metric("Messages", len(st.session_state.messages))
            user_messages = sum(1 for msg in st.session_state.messages if msg["role"] == "user")
            assistant_messages = len(st.session_state.messages) - user_messages
            
            col1, col2 = st.columns(2)
            with col1:
                st.metric("👤 You", user_messages)
            with col2:
                st.metric("🤖 AI", assistant_messages)
    
    # Main chat interface
    chat_container = st.container()
    
    # Display conversation history
    with chat_container:
        for message_index, message in enumerate(st.session_state.messages):
            with st.chat_message(message["role"]):
                # Display message content
                st.markdown(message["content"])
                
                # Show timestamp for user messages
                if message["role"] == "user" and message.get("timestamp"):
                    try:
                        if isinstance(message["timestamp"], str):
                            ts = datetime.fromisoformat(message["timestamp"].replace('Z', '+00:00'))
                        else:
                            ts = message["timestamp"]
                        st.caption(f"🕐 {ts.strftime('%I:%M %p')} IST")
                    except:
                        pass
                
                # Only show booking confirmation for actual successful bookings
                if should_show_booking(message_index, message):
                    booking_id = message["booking_data"].get("id", "")
                    display_booking_confirmation(message["booking_data"], booking_id)
                
                # Only show confirmation prompt when needed
                elif should_show_confirmation(message_index, message):
                    display_confirmation_prompt(message_index)
                
                # Smart time slot display
                elif should_show_suggestions(message_index, message):
                    display_suggested_times(message["suggested_times"], message_index)
    
    # FIXED: Use enhanced chat input handler
    enhanced_chat_input_handler()
    
    # Footer with helpful information
    with st.expander("💡 Tips & Troubleshooting", expanded=False):
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("""
            **📅 Booking Examples:**
            - "Schedule a meeting tomorrow at 3 PM"
            - "Book a 30-minute call with john@example.com"
            - "I need a 2-hour workshop next Friday"
            - "Set up a quick sync for today"
            """)
        
        with col2:
            st.markdown("""
            **🔧 Troubleshooting:**
            - **Timeout errors**: Service is starting up, wait 1 minute
            - **No response**: Check connection status in sidebar
            - **Calendar not connected**: Use auth link in sidebar
            - **Slow responses**: First request after inactivity takes longer
            """)
        
        st.markdown("""
        **🚀 About Service Startup:**
        - This app uses free hosting that sleeps after inactivity
        - First request after sleep takes 30-60 seconds to wake up
        - Once running, all responses are fast
        - This is normal behavior for free hosting services
        """)

if __name__ == "__main__":
    main()
