import logging
import traceback
import tempfile
import json
import os
import pickle
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, HTMLResponse
from google_auth_oauthlib.flow import Flow
from typing import List, Optional
from datetime import datetime
from dotenv import load_dotenv

from .models.schemas import ChatMessage, ChatResponse, ConversationState, MessageRole
from .agents.calendar_agent import CalendarBookingAgent

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="AI Calendar Booking Agent",
    description="Conversational AI for Google Calendar appointment booking",
    version="1.0.0"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"Global exception handler caught: {exc}")
    logger.error(f"Traceback: {traceback.format_exc()}")
    return {"error": "Internal server error", "detail": str(exc)}

# Initialize agent
try:
    calendar_agent = CalendarBookingAgent()
    logger.info("✅ CalendarBookingAgent initialized successfully")
except Exception as e:
    logger.error(f"❌ Failed to initialize CalendarBookingAgent: {e}")
    calendar_agent = None

# In-memory conversation storage
conversations = {}

@app.get("/")
async def root():
    """Root endpoint with setup instructions"""
    try:
        auth_required = True
        if calendar_agent and hasattr(calendar_agent, 'calendar_service'):
            if hasattr(calendar_agent.calendar_service, 'service'):
                if 'Mock' not in calendar_agent.calendar_service.service.__class__.__name__:
                    auth_required = False
        
        return {
            "message": "AI Calendar Booking Agent API",
            "status": "running",
            "setup_required": auth_required,
            "auth_url": "/auth/login" if auth_required else None,
            "docs": "/docs"
        }
    except Exception as e:
        return {
            "message": "AI Calendar Booking Agent API",
            "status": "running",
            "setup_required": True,
            "auth_url": "/auth/login",
            "docs": "/docs"
        }

@app.get("/auth/login")
async def auth_login():
    """Start OAuth flow for production"""
    try:
        logger.info("🔐 Starting OAuth flow...")
        
        # Create credentials from environment variables
        creds_dict = {
            "web": {
                "client_id": os.getenv('GOOGLE_CLIENT_ID'),
                "client_secret": os.getenv('GOOGLE_CLIENT_SECRET'),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["https://ai-calendar-assistant-grdx.onrender.com/auth/callback"]
            }
        }
        
        # Validate environment variables
        if not creds_dict["web"]["client_id"] or not creds_dict["web"]["client_secret"]:
            logger.error("❌ Missing Google OAuth credentials in environment variables")
            return HTMLResponse("""
            <h1>❌ Configuration Error</h1>
            <p>Google OAuth credentials are not properly configured.</p>
            <p>Please check the environment variables GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.</p>
            """)
        
        # Create temporary credentials file
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            json.dump(creds_dict, f)
            temp_creds_file = f.name
        
        try:
            flow = Flow.from_client_secrets_file(
                temp_creds_file,
                scopes=['https://www.googleapis.com/auth/calendar', 'https://www.googleapis.com/auth/calendar.events']
            )
            flow.redirect_uri = "https://ai-calendar-assistant-grdx.onrender.com/auth/callback"
            
            authorization_url, state = flow.authorization_url(
                access_type='offline',
                include_granted_scopes='true',
                prompt='consent'
            )
            
            logger.info(f"🔗 Redirecting to: {authorization_url}")
            return RedirectResponse(url=authorization_url)
            
        finally:
            # Clean up temp file
            try:
                os.unlink(temp_creds_file)
            except:
                pass
        
    except Exception as e:
        logger.error(f"❌ OAuth start failed: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return HTMLResponse(f"""
        <h1>❌ OAuth Setup Failed</h1>
        <p>Error: {str(e)}</p>
        <p><a href="/">Return to Home</a></p>
        """)

@app.get("/auth/callback")
async def auth_callback(code: str = None, state: str = None, error: str = None):
    """Handle OAuth callback"""
    try:
        if error:
            logger.error(f"❌ OAuth error: {error}")
            return HTMLResponse(f"""
            <h1>❌ Authorization failed</h1>
            <p>Error: {error}</p>
            <p><a href="/auth/login">Try Again</a></p>
            """)
            
        if not code:
            logger.error("❌ No authorization code received")
            return HTMLResponse("""
            <h1>❌ Authorization failed</h1>
            <p>No authorization code received</p>
            <p><a href="/auth/login">Try Again</a></p>
            """)
        
        logger.info("🔐 Processing OAuth callback...")
        
        # Recreate the flow
        creds_dict = {
            "web": {
                "client_id": os.getenv('GOOGLE_CLIENT_ID'),
                "client_secret": os.getenv('GOOGLE_CLIENT_SECRET'),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["https://ai-calendar-assistant-grdx.onrender.com/auth/callback"]
            }
        }
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            json.dump(creds_dict, f)
            temp_creds_file = f.name
        
        flow = Flow.from_client_secrets_file(
            temp_creds_file,
            scopes=['https://www.googleapis.com/auth/calendar', 'https://www.googleapis.com/auth/calendar.events']
        )
        flow.redirect_uri = "https://ai-calendar-assistant-grdx.onrender.com/auth/callback"

        # Exchange code for token
        flow.fetch_token(code=code)
        logger.info("✅ Token exchange successful")

        # Save credentials
        with open('token.pickle', 'wb') as token:
            pickle.dump(flow.credentials, token)
        logger.info("💾 Credentials saved")

        # Generate persistent token for environment storage
        if flow.credentials:
            try:
                token_info = {
                    'token': flow.credentials.token,
                    'refresh_token': flow.credentials.refresh_token,
                    'token_uri': flow.credentials.token_uri,
                    'client_id': flow.credentials.client_id,
                    'client_secret': flow.credentials.client_secret,
                    'scopes': flow.credentials.scopes
                }
                import base64
                token_json = json.dumps(token_info)
                token_b64 = base64.b64encode(token_json.encode('utf-8')).decode('utf-8')
                logger.info("💾 Persistent token generated")
                logger.info(f"📋 GOOGLE_TOKEN_DATA={token_b64}")
                # FIXED: Also save to environment for immediate use
                os.environ['GOOGLE_TOKEN_DATA'] = token_b64
                print(f"🔧 Token saved to environment for immediate use")
            except Exception as e:
                logger.error(f"⚠️ Error generating persistent token: {e}")

        # FIXED: Properly reinitialize calendar agent
        global calendar_agent
        try:
            # Reload the calendar service specifically
            if calendar_agent and hasattr(calendar_agent, 'calendar_service'):
                logger.info("🔄 Reloading calendar service with new credentials...")
                calendar_agent.calendar_service.reload_service()
                logger.info("✅ Calendar service reloaded successfully")
            else:
                # Full reinitialize if needed
                calendar_agent = CalendarBookingAgent()
                logger.info("🔄 Calendar agent fully reinitialized")
        except Exception as e:
            logger.error(f"⚠️ Error reinitializing calendar agent: {e}")
            # Still continue, service should work now

        return HTMLResponse("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Calendar Connected</title>
            <style>
                body { font-family: Arial, sans-serif; text-align: center; padding: 50px; background: #f5f5f5; }
                .success { color: #28a745; font-size: 24px; }
                .container { max-width: 500px; margin: 0 auto; background: white; padding: 40px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
                .btn { background: #007bff; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; display: inline-block; margin-top: 20px; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1 class="success">✅ Calendar Connected Successfully!</h1>
                <p>Your Google Calendar has been connected to the AI Assistant.</p>
                <p>You can now:</p>
                <ul style="text-align: left; margin: 20px 0;">
                    <li>✅ Book real meetings</li>
                    <li>✅ Send email invitations</li>
                    <li>✅ Check availability</li>
                    <li>✅ Manage your calendar</li>
                </ul>
                <a href="/" class="btn">View API Status</a>
                <p style="margin-top: 20px; color: #666;">You can now use your frontend application!</p>
            </div>
            <script>
                setTimeout(() => window.close(), 5000);
            </script>
        </body>
        </html>
        """)
            
        # Clean up temp file
        try:
            os.unlink(temp_creds_file)
        except Exception:
            pass
        
    except Exception as e:
        logger.error(f"❌ OAuth callback failed: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return HTMLResponse(f"""
        <!DOCTYPE html>
        <html>
        <head><title>Authorization Failed</title></head>
        <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
            <h1>❌ Authorization failed</h1>
            <p>Error: {str(e)}</p>
            <p><a href="/auth/login">Try Again</a></p>
        </body>
        </html>
        """)

@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(message: ChatMessage, session_id: str = Query(default="default")):
    """Chat endpoint with authentication check"""
    try:
        logger.info(f"📨 Received message: {message.content[:100]}... for session: {session_id}")
        
        if calendar_agent is None:
            logger.error("❌ Calendar agent not initialized")
            raise HTTPException(
                status_code=503,
                detail="Calendar agent service unavailable. Please check server logs."
            )

        # Check if calendar is authenticated
        is_mock = False
        try:
            if hasattr(calendar_agent, 'calendar_service') and hasattr(calendar_agent.calendar_service, 'service'):
                if calendar_agent.calendar_service.service and 'Mock' in calendar_agent.calendar_service.service.__class__.__name__:
                    is_mock = True
        except:
            is_mock = True

        if is_mock:
            return ChatResponse(
                message="🔐 **Calendar Setup Required**\n\nPlease connect your Google Calendar first by clicking: [Connect Calendar](https://ai-calendar-assistant-grdx.onrender.com/auth/login)\n\nAfter connecting, you can start booking real meetings!",
                booking_data=None,
                suggested_times=[],
                requires_confirmation=False
            )

        # Get or create conversation state
        if session_id not in conversations:
            conversations[session_id] = ConversationState()
            logger.info(f"🆕 Created new conversation for session: {session_id}")
        
        conversation = conversations[session_id]

        # Check if we should reset conversation after successful booking
        if (hasattr(conversation, 'conversation_stage') and 
            conversation.conversation_stage == "booking_confirmed" and
            message.content.lower() not in ['yes', 'no', 'ok', 'thanks', 'thank you']):
            
            logger.info("🔄 Auto-resetting conversation after successful booking")
            conversation.extracted_entities = {}
            conversation.calendar_availability = None
            conversation.current_booking = None
            conversation.conversation_stage = "initial"
            conversation.user_intent = None

        # Add user message with timestamp
        user_message = ChatMessage(
            role=MessageRole.USER,
            content=message.content,
            timestamp=datetime.now()
        )
        conversation.messages.append(user_message)

        # Process through agent
        try:
            logger.info("🤖 Processing message through calendar agent...")
            updated_conversation = await calendar_agent.process_message(conversation)
            logger.info("✅ Agent processing completed successfully")
        except Exception as agent_error:
            logger.error(f"❌ Agent processing failed: {agent_error}")
            logger.error(f"Agent error traceback: {traceback.format_exc()}")
            
            # Add fallback message
            fallback_message = ChatMessage(
                role=MessageRole.ASSISTANT,
                content="I'm here to help you schedule meetings. What would you like to book?",
                timestamp=datetime.now()
            )
            conversation.messages.append(fallback_message)
            updated_conversation = conversation

        # Update stored conversation
        conversations[session_id] = updated_conversation

        # Get the latest assistant response
        assistant_messages = [
            msg for msg in updated_conversation.messages
            if msg.role == MessageRole.ASSISTANT
        ]
        
        if assistant_messages:
            latest_response = assistant_messages[-1].content
            logger.info(f"📤 Assistant response: {latest_response[:100]}...")
        else:
            latest_response = "I'm here to help you schedule meetings. What would you like to book?"
            logger.info("📤 Using default response")

        # Enhanced response data extraction
        booking_data = None
        suggested_times = []
        requires_confirmation = False

        try:
            # Only show booking data when actually confirmed AND has valid ID
            if (hasattr(updated_conversation, 'current_booking') and 
                updated_conversation.current_booking and
                isinstance(updated_conversation.current_booking, dict) and
                updated_conversation.current_booking.get('id') and
                hasattr(updated_conversation, 'conversation_stage') and
                updated_conversation.conversation_stage == "booking_confirmed"):
                
                booking_data = updated_conversation.current_booking
                logger.info(f"📅 CONFIRMED Booking: {booking_data.get('id')}")

            # Show suggested times for availability stages
            elif (hasattr(updated_conversation, 'calendar_availability') and
                  updated_conversation.calendar_availability and
                  hasattr(updated_conversation, 'conversation_stage') and
                  updated_conversation.conversation_stage in ["showing_slots", "showing_alternative_slots"]):
                
                suggested_times = [
                    slot.get("display", slot.get("start", "Available"))
                    for slot in updated_conversation.calendar_availability[:8]
                    if isinstance(slot, dict)
                ]
                logger.info(f"🕐 Showing {len(suggested_times)} available time slots (stage: {updated_conversation.conversation_stage})")

            # Show confirmation when awaiting confirmation
            elif (hasattr(updated_conversation, 'conversation_stage') and
                  updated_conversation.conversation_stage == "awaiting_confirmation"):
                requires_confirmation = True
                logger.info("⚠️ Requires user confirmation")

        except Exception as extraction_error:
            logger.error(f"❌ Error extracting response data: {extraction_error}")

        # Prepare response
        response = ChatResponse(
            message=latest_response,
            booking_data=booking_data,
            suggested_times=suggested_times,
            requires_confirmation=requires_confirmation
        )

        logger.info(f"✅ Response prepared - Booking: {'Yes' if booking_data else 'No'}, Slots: {len(suggested_times)}, Confirmation: {requires_confirmation}")
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Unexpected error in chat endpoint: {e}")
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Failed to process message",
                "message": "I'm experiencing technical difficulties. Please try again.",
                "debug_info": str(e) if os.getenv("DEBUG", "false").lower() == "true" else None
            }
        )

@app.get("/health")
async def health_check():
    """Enhanced health check endpoint"""
    try:
        agent_status = "healthy" if calendar_agent is not None else "unavailable"
        
        # Check if using real or mock calendar service
        calendar_status = "mock"
        if calendar_agent and hasattr(calendar_agent, 'calendar_service'):
            if hasattr(calendar_agent.calendar_service, 'service') and calendar_agent.calendar_service.service:
                if 'Mock' not in calendar_agent.calendar_service.service.__class__.__name__:
                    calendar_status = "authenticated"
                    
        conversation_count = len(conversations)
        
        return {
            "status": "healthy",
            "service": "AI Calendar Booking Agent",
            "agent_status": agent_status,
            "calendar_status": calendar_status,
            "auth_required": calendar_status == "mock",
            "auth_url": "/auth/login" if calendar_status == "mock" else None,
            "active_conversations": conversation_count,
            "timestamp": datetime.now().isoformat(),
            "environment": os.getenv("ENVIRONMENT", "development"),
            "version": "1.0.0"
        }
    except Exception as e:
        logger.error(f"❌ Health check failed: {e}")
        raise HTTPException(status_code=503, detail=f"Service unhealthy: {str(e)}")

@app.get("/conversation/{session_id}")
async def get_conversation(session_id: str):
    """Get conversation history"""
    try:
        if session_id in conversations:
            conversation = conversations[session_id]
            return {
                "session_id": session_id,
                "message_count": len(conversation.messages),
                "conversation": conversation,
                "last_updated": datetime.now().isoformat()
            }
        else:
            return {
                "session_id": session_id,
                "message_count": 0,
                "conversation": ConversationState(),
                "status": "new_session"
            }
    except Exception as e:
        logger.error(f"❌ Error retrieving conversation {session_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve conversation: {str(e)}")

@app.delete("/conversation/{session_id}")
async def clear_conversation(session_id: str):
    """Clear conversation history"""
    try:
        if session_id in conversations:
            del conversations[session_id]
            logger.info(f"🗑️ Cleared conversation for session: {session_id}")
            return {"message": f"Conversation {session_id} cleared successfully"}
        else:
            return {"message": f"No conversation found for session {session_id}"}
    except Exception as e:
        logger.error(f"❌ Error clearing conversation {session_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to clear conversation: {str(e)}")

# Startup event
@app.on_event("startup")
async def startup_event():
    """Application startup tasks"""
    logger.info("🚀 Starting AI Calendar Booking Agent...")
    logger.info(f"📊 Environment: {os.getenv('ENVIRONMENT', 'development')}")
    logger.info(f"🔧 Debug mode: {os.getenv('DEBUG', 'false')}")
    
    if calendar_agent is None:
        logger.warning("⚠️ Calendar agent failed to initialize during startup")
    else:
        logger.info("✅ Calendar agent ready")

# Shutdown event
@app.on_event("shutdown")
async def shutdown_event():
    """Application shutdown tasks"""
    logger.info("🛑 Shutting down AI Calendar Booking Agent...")
    logger.info(f"📊 Final conversation count: {len(conversations)}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
