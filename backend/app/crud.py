from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from . import models, schemas
from .database import mongo_db
import logging

logger = logging.getLogger(__name__)


# --- PostgreSQL Functions ---

def get_threats(db: Session, skip: int = 0, limit: int = 100):
    """
    Retrieves a list of threats from the PostgreSQL database, newest first.
    """
    try:
        return db.query(models.Threat).order_by(models.Threat.created_at.desc()).offset(skip).limit(limit).all()
    except SQLAlchemyError as e:
        logger.error(f"Error retrieving threats: {e}")
        db.rollback()
        raise


def create_threat(db: Session, threat_data: schemas.ThreatCreate):
    """
    Creates a new threat in the PostgreSQL database and logs the source URLs in MongoDB.
    Returns the newly created threat object.
    """
    db_threat = None
    try:
        # Create the main threat record in PostgreSQL
        db_threat = models.Threat(
            title=threat_data.title,
            region=threat_data.region,
            countries=threat_data.countries,
            category=threat_data.category,
            description=threat_data.description,
            potential_impact=threat_data.potential_impact,
            source_urls=threat_data.source_urls,
            date_mentioned=threat_data.date_mentioned
        )

        db.add(db_threat)
        db.commit()
        db.refresh(db_threat)

        logger.info(f"✅ Threat created in PostgreSQL: {db_threat.title} (ID: {db_threat.id})")

        # --- MongoDB Logging (with error handling) ---
        try:
            log_entry = {
                "postgres_id": db_threat.id,
                "title": threat_data.title,
                "source_urls": threat_data.source_urls,
                "created_at": db_threat.created_at.isoformat() if db_threat.created_at else None,
                "region": threat_data.region,
                "countries": threat_data.countries,
                "category": threat_data.category,
                "description": threat_data.description,
                "potential_impact": threat_data.potential_impact,
                "date_mentioned": threat_data.date_mentioned
            }

            # Insert into MongoDB (synchronous operation)
            result = mongo_db.threat_logs.insert_one(log_entry)
            logger.info(f"✅ Threat logged to MongoDB: {result.inserted_id}")

        except Exception as mongo_error:
            # Don't fail the whole operation if MongoDB logging fails
            logger.error(f"❌ MongoDB logging failed (but PostgreSQL save succeeded): {mongo_error}")

        return db_threat

    except SQLAlchemyError as e:
        logger.error(f"❌ PostgreSQL error creating threat: {e}")
        db.rollback()
        raise
    except Exception as e:
        logger.error(f"❌ Unexpected error creating threat: {e}")
        db.rollback()
        raise


def create_threat_safe(db: Session, threat_data):
    """
    Safe version that handles ThreatReport objects directly (from rag_agent)
    """
    try:
        # Convert ThreatReport to dict if needed
        if hasattr(threat_data, 'dict'):
            threat_dict = threat_data.dict()
        elif hasattr(threat_data, '__dict__'):
            threat_dict = threat_data.__dict__
        else:
            threat_dict = threat_data

        # Create ThreatCreate schema
        threat_create = schemas.ThreatCreate(**threat_dict)

        # Use the main create function
        return create_threat(db, threat_create)

    except Exception as e:
        logger.error(f"❌ Error in create_threat_safe: {e}")
        logger.error(f"   Data type: {type(threat_data)}")
        logger.error(f"   Data: {threat_data}")
        raise