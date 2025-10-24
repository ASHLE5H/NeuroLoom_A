
import datetime

import os
import PyPDF2
import requests

import re
import logging


from typing import Literal
from collections.abc import AsyncGenerator
from google.adk.agents import BaseAgent, LlmAgent, LoopAgent, SequentialAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.adk.planners import BuiltInPlanner
from google.adk.tools import google_search
from google.adk.tools.agent_tool import AgentTool
from google.genai import types as genai_types
from pydantic import BaseModel, Field

from .instructions import PLANNER_GENERATOR_PROMPT,INTERACTIVE_PLANNER_AGENT_PROMPT, SECTION_PLANNER_AGENT_PROMPT, BASE_RETRIVER_AGENT_PROMPT, BASE_CONTRA_AGENT_PROMPT, HYPOTHESIS_AGENT_PROMPT, REPORT_COMPOSER_AGENT_PROMPT
from .config import config


# --- Structured Output Models ---
class SearchQuery(BaseModel):
    """Model representing a specific search query for web search."""

    search_query: str = Field(
        description="A highly specific and targeted query for web search."
    )


class Feedback(BaseModel):
    """Model for providing evaluation feedback on research quality."""

    grade: Literal["pass", "fail"] = Field(
        description="Evaluation result. 'pass' if the research is sufficient, 'fail' if it needs revision."
    )
    comment: str = Field(
        description="Detailed explanation of the evaluation, highlighting strengths and/or weaknesses of the research."
    )
    follow_up_queries: list[SearchQuery] | None = Field(
        default=None,
        description="A list of specific, targeted follow-up search queries needed to fix research gaps. This should be null or empty if the grade is 'pass'.",
    )


# --- Tools ---
BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

BASE_PAPERS_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "papers"))

# --- Utility Functions ---
def search_papers(query: str, cursor_mark: str = "*", page_size: int = 25):
    """Search for papers using Europe PMC API."""
    params = {
        "query": query,
        "format": "json",
        "resultType": "core",
        "cursorMark": cursor_mark,
        "pageSize": page_size
    }
    response = requests.get(BASE_URL, params=params)
    response.raise_for_status()
    data = response.json()
    return data.get("resultList", {}).get("result", []), data.get("nextCursorMark")


def download_pdf(url: str, path: str):
    """Download PDF to specified path."""
    response = requests.get(url, stream=True, timeout=30)
    response.raise_for_status()
    if "pdf" not in response.headers.get("content-type", "").lower():
        raise Exception("Not a valid PDF file")
    with open(path, "wb") as f:
        for chunk in response.iter_content(8192):
            f.write(chunk)


def retrieve_papers(query: str, directory: str = BASE_PAPERS_PATH,
                    max_papers: int = 5, max_pages: int = 25):
    """Searches for and downloads scientific papers from Europe PMC."""
    try:
        cursor = "*"
        downloaded_count = 0
        papers_data = []

        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), directory))
        os.makedirs(base_dir, exist_ok=True)

        for _ in range(max_pages):
            results, cursor = search_papers(query, cursor_mark=cursor)
            if not results:
                break

            for paper in results:
                if downloaded_count >= max_papers:
                    return {"status": "success", "query": query, "papers": papers_data}

                title = paper.get("title", "Unknown Title")
                paper_id = paper.get("id", "unknown")
                year = paper.get("pubYear")
                author_list = paper.get("authorList", {}).get("author", [])
                authors = [a.get("fullName") for a in author_list if isinstance(a, dict)] if author_list else []
                journal = paper.get("journalTitle")

                # Get open-access PDF links
                full_texts = paper.get("fullTextUrlList", {}).get("fullTextUrl", [])
                pdf_links = [
                    u.get("url")
                    for u in full_texts
                    if u.get("documentStyle", "").lower() == "pdf"
                    and "open" in u.get("availability", "").lower()
                ]

                if not pdf_links:
                    continue

                pdf_url = pdf_links[0]
                pdf_name = f"{paper_id}.pdf"
                pdf_path = os.path.join(base_dir, pdf_name)

                try:
                    download_pdf(pdf_url, pdf_path)
                    downloaded_count += 1
                    papers_data.append({
                        "paperId": paper_id,
                        "title": title,
                        "year": year,
                        "authors": authors,
                        "journal": journal,
                        "pdf_name": pdf_name,
                        "pdf_url": pdf_url,
                    })
                except Exception:
                    continue

        return {"papers": papers_data}

    except Exception as e:
        return {"message": str(e)}
    

def load_all_pdfs(directory: str = BASE_PAPERS_PATH) -> dict:
    """
    Loads and extracts text from all PDF files in the specified directory.
    """
    # Normalize: if someone passes "./papers", convert to absolute
    directory = os.path.abspath(directory)
    print("Resolved PDF directory:", directory)

    if not os.path.exists(directory):
        raise FileNotFoundError(f"Directory not found: {directory}")

    pdf_texts = {}
    for fname in os.listdir(directory):
        if not fname.lower().endswith(".pdf"):
            continue
        pdf_path = os.path.join(directory, fname)
        text = ""
        try:
            with open(pdf_path, 'rb') as file:
                reader = PyPDF2.PdfReader(file)
                for page in reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
            pdf_texts[fname] = text
        except Exception as e:
            print(f"Error reading PDF {fname}: {e}")
    return pdf_texts


# --- Callbacks ---
def collect_retrieved_papers_callback(callback_context: CallbackContext) -> None:
    """
    Collects and organizes paper metadata from the Retriever Agent output.
    Works with both dict and JSON string outputs.
    Stores in callback_context.state["papers"] and maps paperId to short IDs.
    """
    import json

    retrieved_papers_raw = callback_context.state.get("retrieved_papers", {})

    # Convert from JSON string if necessary
    if isinstance(retrieved_papers_raw, str):
        try:
            retrieved_papers_raw = json.loads(retrieved_papers_raw)
        except json.JSONDecodeError:
            retrieved_papers_raw = {}

    retrieved_papers = retrieved_papers_raw.get("papers", [])

    paper_id_to_short_id = callback_context.state.get("paper_id_to_short_id", {})
    papers = callback_context.state.get("papers", {})
    id_counter = len(paper_id_to_short_id) + 1

    for paper in retrieved_papers:
        paper_id = paper.get("paperId")
        if not paper_id:
            continue

        if paper_id not in paper_id_to_short_id:
            short_id = f"paper-{id_counter}"
            paper_id_to_short_id[paper_id] = short_id
            id_counter += 1

            papers[short_id] = {
                "short_id": short_id,
                "paperId": paper_id,
                "title": paper.get("title"),
                "authors": paper.get("authors"),
                "year": paper.get("year"),
                "journal": paper.get("journal"),
                "pdf_name": paper.get("pdf_name"),
                "pdf_url": paper.get("pdf_url")
            }

    callback_context.state["paper_id_to_short_id"] = paper_id_to_short_id
    callback_context.state["papers"] = papers


def citation_replacement_callback(callback_context: CallbackContext) -> None:
    """
    Replaces <cite source="src-N"/> tags in the final report with
    readable text including PDF names, titles, and links.
    Handles contradictions, hypotheses, and ensures human-readable output.

    Updates `callback_context.state["final_report_with_citations"]`.
    """
    # Get the raw report
    final_report = callback_context.state.get("final_report", "")
    if not final_report:
        logging.warning("No 'final_report' found in state. Using empty string.")
        final_report = ""

    # Get the sources (papers) info
    sources = callback_context.state.get("papers", {})

    # Function to replace citation tags
    def tag_replacer(match: re.Match) -> str:
        short_id = match.group(1)
        source_info = sources.get(short_id)
        if not source_info:
            logging.warning(f"Invalid citation tag found and removed: {match.group(0)}")
            return "[Unknown Source]"
        
        # Include PDF name, title, and optional link
        pdf_name = source_info.get("pdf_name", "unknown.pdf")
        title = source_info.get("title", "Untitled Paper")
        url = source_info.get("pdf_url", "")
        if url:
            return f"[{title} ({pdf_name})]({url})"
        return f"{title} ({pdf_name})"

    # Replace all <cite> tags
    processed_report = re.sub(
        r'<cite\s+source\s*=\s*["\']?\s*(paper-\d+|src-\d+)\s*["\']?\s*/>',
        tag_replacer,
        final_report
    )

    # Clean up extra whitespace around punctuation
    processed_report = re.sub(r"\s+([.,;:])", r"\1", processed_report)

    # Store back in state
    callback_context.state["final_report_with_citations"] = processed_report


# --- Custom Agent for Loop Control ---
class EscalationChecker(BaseAgent):
    """Checks research evaluation and escalates to stop the loop if grade is 'pass'."""

    def __init__(self, name: str):
        super().__init__(name=name)

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        evaluation_result = ctx.session.state.get("research_evaluation")
        if evaluation_result and evaluation_result.get("grade") == "pass":
            logging.info(
                f"[{self.name}] Research evaluation passed. Escalating to stop loop."
            )
            yield Event(author=self.name, actions=EventActions(escalate=True))
        else:
            logging.info(
                f"[{self.name}] Research evaluation failed or not found. Loop will continue."
            )
            # Yielding an event without content or actions just lets the flow continue.
            yield Event(author=self.name)


# --- AGENT DEFINITIONS ---
plan_generator = LlmAgent(
    model=config.worker_model,
    name="plan_generator",
    description="Generates a fixed pipeline plan for NeuroLoom literature review and refinement based on user feedback.",
    instruction=PLANNER_GENERATOR_PROMPT
)



section_planner = LlmAgent(
    model=config.worker_model,
    name="section_planner",
    description="Builds the structured markdown outline for the NeuroLoom report, aligned with the fixed pipeline.",
    instruction=SECTION_PLANNER_AGENT_PROMPT,
    output_key="report_sections",
)

# # 3. Use an f-string to substitute the variable into the prompt
# RETRIVER_AGENT_PROMPT = BASE_RETRIVER_AGENT_PROMPT.format(
#     papers_path=BASE_PAPERS_PATH
# )

retriever_agent = LlmAgent(
    name="retriever_agent",
    model=config.worker_model,
    description="Retrieves relevant research papers (metadata + PDF info) for NeuroLoom pipeline.",
    instruction=BASE_RETRIVER_AGENT_PROMPT,
    tools=[retrieve_papers],
    output_key="retrieved_papers",
    after_agent_callback=collect_retrieved_papers_callback,
)

# CONTRA_AGENT_PROMPT = BASE_CONTRA_AGENT_PROMPT.format(
#     papers_path=BASE_PAPERS_PATH,
#     current_date=datetime.datetime.now().strftime("%Y-%m-%d")
# )
contra_agent = LlmAgent(
    name="contra_agent",
    model=config.worker_model,
    description="Analyzes all downloaded clinical research PDFs and identifies contradictions, agreements, and insights.",
    instruction=BASE_CONTRA_AGENT_PROMPT,
    tools=[load_all_pdfs],
    output_key="contradictions"
)


hypothesis_agent = LlmAgent(
    model=config.worker_model,
    name="hypothesis_agent",
    description="Generates possible hypotheses to explain contradictions detected across research papers.",
    planner=BuiltInPlanner(
        thinking_config=genai_types.ThinkingConfig(include_thoughts=True)
    ),
    instruction=HYPOTHESIS_AGENT_PROMPT,
    output_key="hypothesis"
)


report_composer = LlmAgent(
    model=config.worker_model,
    name="report_composer",
    include_contents="none",
    description="Composes Final Report based on the Report format and Output Key's",
    instruction=REPORT_COMPOSER_AGENT_PROMPT,
    output_key="final_report",
    after_agent_callback=citation_replacement_callback,
)



neuroloom_pipeline = SequentialAgent(
    name="neuroloom_pipeline",
    description="""
        Executes a research plan: downloads papers, extracts contradictions, generates hypotheses,and composes a final report.
    """,
    sub_agents=[
        section_planner,
        retriever_agent,
        contra_agent,
        hypothesis_agent, 
        report_composer,  
    ],
)



interactive_planner_agent = LlmAgent(
    name="interactive_planner_agent",
    model=config.worker_model,
    description=(
        "Collaborates with the user to create a research plan specifically for extracting "
        "contradictions across papers and generating hypotheses."
    ),
    instruction=INTERACTIVE_PLANNER_AGENT_PROMPT,
    sub_agents=[neuroloom_pipeline],
    tools=[AgentTool(plan_generator)],
    output_key="research_plan",
)
root_agent = interactive_planner_agent
