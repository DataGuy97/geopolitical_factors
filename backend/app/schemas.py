from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from typing import List, Optional


# Base properties for a threat
class ThreatBase(BaseModel):
    title: str
    region: str
    countries: Optional[List[str]] = Field(default=None, description="List of countries affected by the threat or None")
    category: str
    description: str
    potential_impact: str = Field(default=None,
                                  description="The potential impact of the threat on the maritime industry.")
    source_urls: Optional[List[str]] = Field(default=None, description="List of source URLs or None")
    date_mentioned: str

    @field_validator('countries', mode='before')
    @classmethod
    def validate_countries(cls, v):
        """Handle countries field - accepts None, empty list, single string, or list of strings"""
        if v is None:
            return None  # Keep as None/NULL in database
        if v == []:
            return []  # Empty list is valid
        if isinstance(v, str):
            if v.strip() == "":
                return None  # Empty string becomes None
            return [v]  # Single string becomes list
        if isinstance(v, list):
            # Filter out empty strings and None values
            filtered = [country for country in v if country and isinstance(country, str) and country.strip()]
            return filtered if filtered else None
        return v

    @field_validator('source_urls', mode='before')
    @classmethod
    def validate_source_urls(cls, v):
        """Handle source_urls field - accepts None or list of strings"""
        if v is None:
            return None
        if v == []:
            return []
        if isinstance(v, list):
            # Filter out None and empty strings
            filtered = [url for url in v if url and isinstance(url, str) and url.strip()]
            return filtered if filtered else None
        return v


# Properties needed to create a new threat
class ThreatCreate(ThreatBase):
    pass


# Properties to be returned when reading a threat from the API
class Threat(ThreatBase):
    id: int
    created_at: datetime

    # This allows the model to be created from a database object
    class Config:
        from_attributes = True