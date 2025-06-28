import logging
import traceback
from fastapi import FastAPI, HTTPException, Query

from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
import os
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

# FIXED: CORS configuration for production
allowed_origins = [
    "http://localhost:3000",
    "http://localhost:8501",
    "https://*.streamlit.app",
    "https://*.onrender.com",
]

# Add environment-specific origins
if os.getenv("FRONTEND_URL"):
    allowed_origins.append(os.getenv("FRONTEND_URL"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For development - restrict in production
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


# Initialize agent with error handling
try:
    calendar_agent = CalendarBookingAgent()
    logger.info("✅ CalendarBookingAgent initialized successfully")
except Exception as e:
    logger.error(f"❌ Failed to initialize CalendarBookingAgent: {e}")
    calendar_agent = None

# In-memory conversation storage
conversations = {}

# Root endpoint
@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "AI Calendar Booking Agent API",
        "status": "running",
        "docs": "/docs"
    }

@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(message: ChatMessage, session_id: str = Query(default="default")):
    """ENHANCED: Chat endpoint with proper conflict handling and alternatives display"""
    try:
        logger.info(f"📨 Received message: {message.content[:100]}... for session: {session_id}")
        
        if calendar_agent is None:
            logger.error("❌ Calendar agent not initialized")
            raise HTTPException(
                status_code=503,
                detail="Calendar agent service unavailable. Please check server logs."
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

        logger.info(f"💬 Conversation has {len(conversation.messages)} existing messages")

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

        # FIXED: Enhanced response data extraction for conflicts and alternatives
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

            # FIXED: Show suggested times for ALL showing slots stages including alternatives
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


# Add health check with more details
@app.get("/health")
async def health_check():
    """Enhanced health check endpoint"""
    try:
        agent_status = "healthy" if calendar_agent is not None else "unavailable"
        conversation_count = len(conversations)
        
        return {
            "status": "healthy",
            "service": "AI Calendar Booking Agent",
            "agent_status": agent_status,
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
