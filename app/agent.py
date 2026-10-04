# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
import json
import os
import urllib.request
import uuid
from zoneinfo import ZoneInfo

from a2ui.basic_catalog.provider import BasicCatalog
from a2ui.schema.manager import A2uiSchemaManager
from google import genai
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.memory.vertex_ai_memory_bank_service import VertexAiMemoryBankService
from google.adk.models import Gemini
from google.adk.tools import ToolContext
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.cloud import firestore, storage
from google.genai import types

from .a2ui_utils import a2ui_callback

# Hardcoded project ID and bucket name required for Agent Platform deployment safety
PROJECT_ID = "qwiklabs-gcp-03-f94ecd44b48d"
BUCKET_NAME = "isolv-assets-qwiklabs-gcp-03-f94ecd44b48d"
MEMORY_BANK_ID = "5106149041821974528"

db = firestore.Client(project=PROJECT_ID)
storage_client = storage.Client(project=PROJECT_ID)
genai_client = genai.Client(vertexai=True, project=PROJECT_ID, location="global")


async def generate_memories_callback(callback_context: CallbackContext):
    """WRITE: After each conversation turn, extracts and sends session events to Vertex AI Memory Bank."""
    try:
        await callback_context.add_session_to_memory()
    except Exception as e:
        pass
    return None


def memory_bank_service_builder():
    """Builds VertexAiMemoryBankService for deployed container runtime."""
    return VertexAiMemoryBankService(
        project=PROJECT_ID,
        location="us-central1",
        agent_engine_id=MEMORY_BANK_ID,
    )


def list_requirements(status_filter: str = "") -> list[dict]:
    """Retrieves all business requirements and architecture component mappings from Firestore.

    Args:
        status_filter: Optional filter by coverage status ('Covered', 'Partial', 'Gap'). If empty, returns all requirements.

    Returns:
        A list of dictionaries representing requirements and their mapping details.
    """
    collection_ref = db.collection("requirements")
    docs = collection_ref.stream()
    results = []
    for doc in docs:
        data = doc.to_dict()
        if status_filter and data.get("coverage_status", "").lower() != status_filter.lower():
            continue
        results.append(data)
    return results


def get_requirement_by_id(requirement_id: str) -> dict:
    """Retrieves a single requirement and its architecture mapping by ID.

    Args:
        requirement_id: The ID of the requirement (e.g. 'REQ-101', 'REQ-102').

    Returns:
        A dictionary with the requirement details or an error dictionary if not found.
    """
    doc_ref = db.collection("requirements").document(requirement_id)
    doc = doc_ref.get()
    if doc.exists:
        return doc.to_dict()
    return {"error": f"Requirement '{requirement_id}' not found."}


def update_requirement_mapping(
    requirement_id: str,
    business_goal: str,
    mapped_component: str,
    coverage_status: str,
    risk_level: str = "Low",
    remediation_notes: str = "",
) -> dict:
    """Updates or adds a requirement and its solution architecture component mapping in Firestore.

    Args:
        requirement_id: Unique ID for the requirement (e.g. 'REQ-105').
        business_goal: Brief description of the business requirement or goal.
        mapped_component: Name of the solution architecture component addressing this requirement.
        coverage_status: Coverage state ('Covered', 'Partial', 'Gap').
        risk_level: Risk level if uncovered or partial ('Low', 'Medium', 'High', 'Critical').
        remediation_notes: Recommended actions or design notes to resolve gaps.

    Returns:
        A dictionary confirming the saved requirement mapping.
    """
    data = {
        "requirement_id": requirement_id,
        "business_goal": business_goal,
        "mapped_component": mapped_component,
        "coverage_status": coverage_status,
        "risk_level": risk_level,
        "remediation_notes": remediation_notes,
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    db.collection("requirements").document(requirement_id).set(data)
    return {"status": "success", "saved_requirement": data}


def calculate_traceability_metrics() -> dict:
    """Calculates quantitative solution traceability and gap metrics across all requirements in Firestore.

    Returns:
        A dictionary containing total requirements, coverage percentages (Covered, Partial, Gap),
        risk breakdown counts, and a list of high-risk unassigned requirements.
    """
    collection_ref = db.collection("requirements")
    docs = collection_ref.stream()

    total_count = 0
    coverage_counts = {"covered": 0, "partial": 0, "gap": 0}
    risk_counts = {"low": 0, "medium": 0, "high": 0, "critical": 0}
    high_risk_gaps = []

    for doc in docs:
        data = doc.to_dict()
        total_count += 1

        status = data.get("coverage_status", "").lower()
        if status in coverage_counts:
            coverage_counts[status] += 1

        risk = data.get("risk_level", "").lower()
        if risk in risk_counts:
            risk_counts[risk] += 1

        if status in ["gap", "partial"] and risk in ["high", "critical"]:
            high_risk_gaps.append(
                {
                    "requirement_id": data.get("requirement_id"),
                    "business_goal": data.get("business_goal"),
                    "coverage_status": data.get("coverage_status"),
                    "risk_level": data.get("risk_level"),
                    "remediation_notes": data.get("remediation_notes"),
                }
            )

    if total_count == 0:
        return {"message": "No requirements found in Firestore to calculate metrics."}

    covered_pct = round((coverage_counts["covered"] / total_count) * 100, 1)
    partial_pct = round((coverage_counts["partial"] / total_count) * 100, 1)
    gap_pct = round((coverage_counts["gap"] / total_count) * 100, 1)

    return {
        "total_requirements": total_count,
        "coverage_summary": {
            "covered_count": coverage_counts["covered"],
            "covered_percentage": f"{covered_pct}%",
            "partial_count": coverage_counts["partial"],
            "partial_percentage": f"{partial_pct}%",
            "gap_count": coverage_counts["gap"],
            "gap_percentage": f"{gap_pct}%",
        },
        "risk_summary": risk_counts,
        "critical_gaps_requiring_attention": high_risk_gaps,
    }


def check_component_security_vulnerabilities(
    package_name: str, ecosystem: str = "PyPI"
) -> dict:
    """Queries Google's OSV (Open Source Vulnerabilities) public API to assess security risks for open-source architecture components.

    Args:
        package_name: The name of the package/component to audit (e.g. 'jinja2', 'tensorflow', 'gunicorn').
        ecosystem: Package ecosystem ('PyPI', 'npm', 'Go', 'Maven', 'crates.io'). Defaults to 'PyPI'.

    Returns:
        A summary dictionary containing known CVE/GHSA vulnerabilities and risk details for the component.
    """
    url = "https://api.osv.dev/v1/query"
    payload = json.dumps({"package": {"name": package_name.strip(), "ecosystem": ecosystem}}).encode(
        "utf-8"
    )

    api_key = os.environ.get("OSV_API_KEY", "")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            vulns = data.get("vulns", [])
            summary_list = []
            for v in vulns[:5]:
                summary_list.append(
                    {
                        "id": v.get("id"),
                        "summary": v.get("summary", "No summary provided"),
                        "details": v.get("details", "")[:150] + "...",
                    }
                )
            return {
                "package_name": package_name,
                "ecosystem": ecosystem,
                "vulnerability_count": len(vulns),
                "top_vulnerabilities": summary_list,
            }
    except Exception as e:
        return {"error": f"Failed to query OSV vulnerability API for '{package_name}': {str(e)}"}


async def generate_architecture_diagram(
    prompt: str,
    filename: str = "architecture_diagram.jpg",
    tool_context: ToolContext = None,
) -> dict:
    """Generates an enterprise architecture diagram image using gemini-3.1-flash-lite-image in global region.

    Saves the image as an artifact in Playground and uploads bytes directly to public Cloud Storage bucket.

    Args:
        prompt: Detailed description of the architecture diagram or system topology to generate.
        filename: Name for saving the generated image artifact (e.g., 'payment_architecture.jpg').
        tool_context: The ADK ToolContext instance provided automatically by the runtime.

    Returns:
        A dictionary containing the public GCS URL of the generated image and status metadata.
    """
    if not prompt:
        prompt = "High-level enterprise solution architecture diagram showing microservices, API gateways, database clusters, and cloud security controls."

    try:
        response = genai_client.models.generate_content(
            model="gemini-3.1-flash-lite-image",
            contents=prompt,
            config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
        )

        image_bytes = None
        mime_type = "image/jpeg"
        if response.candidates and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if part.inline_data:
                    image_bytes = part.inline_data.data
                    if part.inline_data.mime_type:
                        mime_type = part.inline_data.mime_type
                    break

        if not image_bytes:
            return {"error": "Failed to extract image bytes from model response."}

        # (1) Save image artifact in Playground's Artifacts panel
        if tool_context and hasattr(tool_context, "save_artifact"):
            artifact_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
            await tool_context.save_artifact(filename=filename, artifact=artifact_part)

        # (2) Upload image bytes directly to public GCS bucket (without writing to a local file)
        object_name = f"{uuid.uuid4().hex[:8]}_{filename}"
        if not object_name.endswith(".jpg") and not object_name.endswith(".png"):
            object_name += ".jpg"

        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(object_name)
        blob.upload_from_string(image_bytes, content_type=mime_type)

        public_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{object_name}"

        return {
            "status": "success",
            "public_url": public_url,
            "filename": filename,
            "prompt_used": prompt,
            "message": "Architecture diagram generated, saved as Playground artifact, and uploaded to GCS.",
        }

    except Exception as e:
        return {"error": f"Failed to generate architecture diagram image: {str(e)}"}


def get_weather(query: str) -> str:
    """Simulates a web search. Use it get information on weather.

    Args:
        query: A string containing the location to get weather information for.

    Returns:
        A string with the simulated weather information for the queried location.
    """
    if "sf" in query.lower() or "san francisco" in query.lower():
        return "It's 60 degrees and foggy."
    return "It's 90 degrees and sunny."


def get_current_time(query: str) -> str:
    """Simulates getting the current time for a city.

    Args:
        query: The name of the city to get the current time for.

    Returns:
        A string with the current time information.
    """
    if "sf" in query.lower() or "san francisco" in query.lower():
        tz_identifier = "America/Los_Angeles"
    else:
        return f"Sorry, I don't have timezone information for query: {query}."

    tz = ZoneInfo(tz_identifier)
    now = datetime.datetime.now(tz)
    return f"The current time for query {query} is {now.strftime('%Y-%m-%d %H:%M:%S %Z%z')}"


# Build system prompt with A2uiSchemaManager version 0.8 and Basic Catalog
schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

instruction = schema_manager.generate_system_prompt(
    role_description=(
        "You are isolv, an Enterprise Solution Architecture & Traceability assistant. "
        "You help Solution Architects map business requirements to architecture components, "
        "evaluate security risks for software components using OSV, generate architecture diagram images, "
        "and calculate solution coverage metrics using your tools."
    ),
    workflow_description=(
        "Analyze the request and return structured UI when appropriate. "
        "CROSS-SESSION MEMORY INSTRUCTIONS: You have long-term memory enabled via Vertex AI Memory Bank. "
        "You MUST actively listen for, record, and remember all user allergies, health restrictions, "
        "dietary needs, and personal constraints stated by the user across conversations. "
        "Always incorporate these stored allergies into your responses, recommendations, and solution planning."
    ),
    ui_description=(
        "Keep every surface tiny and flat: ONE Card > ONE Column > a few Text rows. "
        "Never nest a Card inside a Card. "
        "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use "
        "Table or Heading (unsupported), or Buttons, actions, or forms (they do "
        "nothing in adk web). "
        "You may include one Image component, but only when you have a public https "
        "URL for the image (for example the URL an image tool returns after uploading "
        "to a public bucket). Set the Image url to that exact https link, for example "
        '{"Image": {"url": {"literalString": "https://..."}}}. Never point an '
        "Image at a bare filename, an artifact name, or a non-http(s) path. If you do "
        "not have a public URL, add a short Text line noting the image instead. "
        "No markdown in text; use the usageHint property ('h1', 'h2', 'body') for "
        "headings and emphasis. "
        "Output ONLY the raw A2UI JSON array — no prose, and never wrap it in "
        "<a2a_datapart_json> tags or 'kind'/'data'/'metadata' objects."
    ),
    include_schema=True,
    include_examples=True,
)

root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model="gemini-2.5-flash",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=instruction,
    tools=[
        PreloadMemoryTool(),
        list_requirements,
        get_requirement_by_id,
        update_requirement_mapping,
        calculate_traceability_metrics,
        check_component_security_vulnerabilities,
        generate_architecture_diagram,
        get_weather,
        get_current_time,
    ],
    after_agent_callback=generate_memories_callback,
    after_model_callback=a2ui_callback,
)

app = App(
    root_agent=root_agent,
    name="app",
)
