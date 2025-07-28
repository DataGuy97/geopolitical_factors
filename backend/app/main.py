import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, status, Header
import os
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from typing import List
import logging

from . import crud, models, schemas
from .database import SessionLocal, engine
from .services import rag_agent
from .services.teams_notifier import send_threat_to_teams

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SECRET_KEY = os.getenv("API_SECRET_KEY")


async def verify_secret_key(x_api_key: str = Header(..., description="API Secret Key")):
    """
    Dependency to verify the secret key provided in the X-API-Key header.
    """
    if x_api_key != SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key",
        )
    return x_api_key


# This queue will hold new threats to be sent to clients as notifications
notification_queue = asyncio.Queue()

# Global scheduler instance
scheduler: AsyncIOScheduler = None


# --- Database Dependency ---
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --- Background Task (The Agent Runner) ---
async def run_threat_discovery_and_save():
    """Background task to discover and save maritime threats"""
    logger.info("Scheduler triggered: Starting RAG agent to discover threats...")

    # Create a new database session for this background task
    db = SessionLocal()
    try:
        threat_reports = await rag_agent.find_maritime_threats()
        if not threat_reports:
            logger.info("Agent finished: No new threats found.")
            return

        logger.info(f"Found {len(threat_reports)} potential threats")

        for report in threat_reports:
            try:
                # Create threat in database
                new_threat_orm = crud.create_threat(db=db, threat_data=report)
                logger.info(f"New threat saved to DB: {new_threat_orm.title}")

                # Convert to Pydantic schema for notifications
                new_threat_schema = schemas.Threat.model_validate(new_threat_orm)

                # Add to notification queue
                await notification_queue.put(new_threat_schema)

                # Send Teams notification
                try:
                    await send_threat_to_teams(new_threat_schema)
                    logger.info(f"Teams notification sent for threat: {new_threat_orm.title}")
                except Exception as e:
                    logger.error(f"Failed to send Teams notification: {e}")

            except Exception as e:
                logger.error(f"Error processing threat report: {e}")
                continue

    except Exception as e:
        logger.error(f"Error in threat discovery process: {e}")
    finally:
        db.close()
        logger.info("Threat discovery process completed")


# --- Lifespan Event Handler ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup Logic ---
    logger.info("Application startup initiated.")

    try:
        # 1. Create database tables
        logger.info("Creating database tables...")
        models.Base.metadata.create_all(bind=engine)
        logger.info("Database tables created/verified.")

        # 2. Initialize and start the scheduler
        global scheduler
        scheduler = AsyncIOScheduler()

        # Add the cron job - runs daily at 6 AM UTC
        scheduler.add_job(
            run_threat_discovery_and_save,
            trigger=CronTrigger(hour=5, minute=10, timezone='UTC'),
            id='threat_discovery_job',
            name='Daily Threat Discovery',
            replace_existing=True,
            max_instances=1  # Prevent overlapping runs
        )

        # For testing - add a job that runs every 5 minutes (remove in production)
        # scheduler.add_job(
        #     run_threat_discovery_and_save,
        #     'interval',
        #     minutes=5,
        #     id='test_threat_discovery',
        #     name='Test Threat Discovery',
        #     replace_existing=True,
        #     max_instances=1
        # )

        scheduler.start()
        logger.info("Scheduler started successfully.")
        logger.info(f"Next run scheduled for: {scheduler.get_job('threat_discovery_job').next_run_time}")

        logger.info("Application startup complete.")

    except Exception as e:
        logger.error(f"Error during startup: {e}")
        raise

    yield  # Application starts serving requests

    # --- Shutdown Logic ---
    logger.info("Application shutdown initiated.")
    try:
        if scheduler and scheduler.running:
            scheduler.shutdown(wait=True)
            logger.info("Scheduler stopped.")
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")

    logger.info("Application shutdown complete.")


# Initialize FastAPI application with the lifespan handler
app = FastAPI(title="Maritime Geopolitical Threats API", lifespan=lifespan)

# --- CORS Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, change this to your frontend's URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- API Endpoints ---

@app.get("/")
def read_root():
    return {"message": "Welcome to the Maritime Threats API"}


@app.get("/health")
def health_check():
    """Health check endpoint for GCP"""
    scheduler_status = "running" if scheduler and scheduler.running else "stopped"
    next_run = None
    if scheduler and scheduler.running:
        job = scheduler.get_job('threat_discovery_job')
        next_run = str(job.next_run_time) if job else "No job found"

    return {
        "status": "healthy",
        "scheduler": scheduler_status,
        "next_run": next_run
    }


@app.get("/api/threats/", response_model=List[schemas.Threat])
def get_all_threats(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """
    Endpoint to get a list of all threats from the database.
    """
    threats = crud.get_threats(db, skip=skip, limit=limit)
    return threats


# --- Real-Time Notification Endpoint ---
from sse_starlette.sse import EventSourceResponse
import json


async def notification_generator():
    """
    Yields new threats from the queue as they arrive.
    """
    while True:
        try:
            # Wait for a new threat to appear in the queue
            new_threat = await notification_queue.get()
            # Send the threat data as a JSON string
            yield json.dumps(new_threat.dict())
        except asyncio.CancelledError:
            logger.info("Client disconnected from notifications.")
            break
        except Exception as e:
            logger.error(f"Error in notification generator: {e}")
            break


@app.get("/api/notifications")
async def stream_notifications():
    """
    Endpoint for clients to subscribe to real-time threat notifications.
    """
    return EventSourceResponse(notification_generator())


@app.get("/api/discover-threats", dependencies=[Depends(verify_secret_key)])
async def discover_threats():
    """
    Endpoint to manually trigger the threat discovery process.
    Protected by a secret key.
    """
    try:
        await run_threat_discovery_and_save()
        return {"message": "Threat discovery completed successfully."}
    except Exception as e:
        logger.error(f"Manual threat discovery failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Threat discovery failed: {str(e)}"
        )


@app.get("/api/scheduler/status")
async def get_scheduler_status():
    """
    Get the current status of the scheduler and jobs.
    """
    if not scheduler:
        return {"status": "not_initialized"}

    if not scheduler.running:
        return {"status": "stopped"}

    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run_time": str(job.next_run_time),
            "trigger": str(job.trigger)
        })

    return {
        "status": "running",
        "jobs": jobs
    }