import os
import json
import re
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_tavily import TavilySearch
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from typing import List

# Load .env file only if it exists (for local development)
if os.path.exists('.env'):
    load_dotenv()

# This class defines the structure of the report we want the AI to generate.
class ThreatReport(BaseModel):
    """Data structure for a single identified threat."""
    title: str = Field(description="A concise, informative title for the threat.")
    region: str = Field(description="The geographical region the threat applies to (e.g., Red Sea, Strait of Malacca).")
    countries: List[str] = Field(description="List of countries affected by the threat.")
    category: str = Field(description="The category of the threat (e.g., Piracy, Military Conflict, Sanctions, Terrorist Attack).")
    description: str = Field(description="A detailed description of the threat based on the sources found.")
    potential_impact: str = Field(description="The potential impact of the threat on the maritime industry.")
    source_urls: List[str] = Field(description="A list of URLs for the sources used to identify the threat.")
    date_mentioned: str = Field(description="The date when the threat was mentioned in the sources. Usually a date on top for the article.")

# Get API key from environment variables
gemini_api_key = os.getenv("GEMINI_API_KEY")
if not gemini_api_key:
    raise ValueError("GEMINI_API_KEY environment variable not set")




# Initialize the Gemini model
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.1)

# Initialize the search tool
search_tool = TavilySearch(max_results=10)
tools = [search_tool]

# This is the detailed instruction manual (prompt) for our AI agent.
PROMPT = """
You are an expert maritime geopolitical. Your task is to identify and summarize current geopolitical 
threats to the maritime industry and tariffs fluctuations based on the provided search results.
Use only data from the last two weeks. Use the latest news articles and reports. Use various sources.
Extract the following information for each relevant threat:
- title: A concise title for the threat or tariff fluctuation.
- region: The primary geographical region affected (e.g., "Red Sea", "South China Sea", "Global").
- countries: List of countries impacted by the threat (e.g., ["Iran", "Saudi Arabia", "UAE"])
- category: A broad category for the threat (e.g., "Geopolitical Instability", "Piracy", "Environmental", "Cyber Attack", "Geopolitical Competition").
- description: A brief summary (2-3 sentences) of the threat.
- potential_impact: A brief description of the potential impact on the maritime industry (e.g., "Increased shipping costs", 
- Disruption of trade routes", "Increased risk of attacks on vessels").
- source_urls: A list of URLs from the search results that support this threat.
- date_mentioned: The date when the threat was mentioned in the sources. If no date is available, use "Not specified". Usually a date on top for the article.

Format your response as a JSON object with a single key "reports" containing a list of threat objects.

Example JSON format:
{{
  "reports": [
    {{
      "title": "Houthi Attacks in Red Sea",
      "region": "Red Sea",
      "countries": "["Yemen", "Saudi Arabia", "Egypt"]",
      "category": "Military Conflict",
      "description": "Houthi rebels continue attacking commercial vessels in the Red Sea.",
      "potential_impact": "Increased shipping costs and route diversions around Africa.",
      "source_urls": ["http://example.com/source1"],
      "date_mentioned": "July 23, 2025"  # Use a date in any format or "Not specified" if no date is available
    }},

    {{
      "title": "Example Tariffs Fluctuation Title 1",
      "region": "Example Region 1",
      "countries": "["Jordan", "Iran", "Saudi Arabia"]",
      "category": "Trump Tariffs",
      "description": "This is the description of the first tariff fluctuation.",
      "potential_impact": "This tariff fluctuation could lead to increased shipping costs and delays.",
      "source_urls": ["http://example.com/source1"]
      "date_mentioned": "June 19, 2025"  # Use a date in any format or "Not specified" if no date is available
    }}
  ]
}}

If you find no new, credible threats, return a JSON object with an empty list: {{"reports": []}}.
"""

# Create the agent
prompt_template = ChatPromptTemplate.from_messages([
    ("system", PROMPT),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])

agent = create_tool_calling_agent(llm, tools, prompt_template)
agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True) # verbose=True lets us see the agent's "thoughts"


async def find_maritime_threats() -> List[ThreatReport]:
    """
    Runs the RAG agent to find and structure maritime threats.
    Returns a list of ThreatReport objects.
    """
    query = "Find recent geopolitical threats to the maritime industry."

    response = await agent_executor.ainvoke({"input": query})

    # print(f"Agent response 1: {response}")  # Debugging output

    # Try to parse the agent's final answer
    try:
        raw_output = response.get("output", "{}")

        # Extract JSON content from a ```json fenced block using regex
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_output, re.DOTALL)
        if match:
            json_str = match.group(1)
            output_data = json.loads(json_str)
        else:
            # Fall back to normal loading (if no code block found)
            output_data = json.loads(raw_output)

        report_list = output_data.get("reports", [])

        # ADD FALLBACK HERE - Before creating ThreatReport objects
        print("🔍 DEBUG: Processing reports...")
        for i, report in enumerate(report_list):
            print(f"Report {i} before processing: {report}")

            # Handle missing or empty countries field
            if 'countries' not in report or not report['countries']:
                report['countries'] = ['Unknown']
                print(f"  ✅ Added default countries: {report['countries']}")
            elif isinstance(report['countries'], str):
                # If AI returned a string instead of list, convert it
                report['countries'] = [report['countries']]
                print(f"  ✅ Converted string to list: {report['countries']}")

            # Ensure all required fields exist with defaults
            if 'title' not in report:
                report['title'] = 'Unknown Threat'
            if 'region' not in report:
                report['region'] = 'Unknown'
            if 'category' not in report:
                report['category'] = 'Unknown'
            if 'description' not in report:
                report['description'] = 'No description available'
            if 'potential_impact' not in report:
                report['potential_impact'] = 'Impact unknown'
            if 'source_urls' not in report:
                report['source_urls'] = []
            if 'date_mentioned' not in report:
                report['date_mentioned'] = 'Not specified'

            print(f"Report {i} after processing: {report}")

        # Convert the raw dictionaries into our ThreatReport Pydantic models
        return [ThreatReport(**report) for report in report_list]

    except (json.JSONDecodeError, TypeError) as e:
        print(f"Error: Could not parse LLM response. Error: {e}")
        print(f"Received response: {response.get('output')}")
        return []