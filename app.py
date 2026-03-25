"""
Conversational Language Training App
Powered by Claude claude-opus-4-6
"""

import uuid
import json
import os
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv
load_dotenv(override=True)
from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
import numpy as np
import subprocess
import anthropic
import whisper
import imageio_ffmpeg
import httpx
from bs4 import BeautifulSoup

_FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()   # full path — no PATH dependency

# Load Whisper model once at startup
print("Loading Whisper model…")
_whisper_model = whisper.load_model("base")
print("Whisper ready.")

# ─────────────────────────────────────────────
# App setup
# ─────────────────────────────────────────────
app = FastAPI(title="Conversation Trainer")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
client = anthropic.Anthropic(
    timeout=120.0,   # 2-minute ceiling — summary/scenario calls can be slow
    max_retries=2,   # retry on transient 5xx / network errors
)

MAX_HISTORY_TURNS = 20  # pairs of user/assistant

# ─── Disk-backed session store (survives hot-reload) ───────────────────────
_SESSIONS_DIR = os.path.join(os.path.dirname(__file__), ".sessions")
_HISTORY_DIR  = os.path.join(os.path.dirname(__file__), ".history")
os.makedirs(_SESSIONS_DIR, exist_ok=True)
os.makedirs(_HISTORY_DIR,  exist_ok=True)


def _save_history_entry(session: dict, summary: dict) -> None:
    """Persist a completed session summary to the history store."""
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    sid = session.get("id", ts)
    fname = f"{ts}_{sid}.json"
    entry = {
        "session_id":      sid,
        "date":            datetime.utcnow().isoformat(),
        "target_language": session["target_language"],
        "native_language": session["native_language"],
        "level":           session["level"],
        "turn_count":      session["turn_count"],
        "summary":         summary,
    }
    with open(os.path.join(_HISTORY_DIR, fname), "w") as f:
        json.dump(entry, f, ensure_ascii=False, indent=2)


def _list_history() -> list[dict]:
    """Return history entries sorted newest-first (metadata only, no full transcript)."""
    entries = []
    for fname in sorted(os.listdir(_HISTORY_DIR), reverse=True):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(_HISTORY_DIR, fname)) as f:
                data = json.load(f)
            entries.append({
                "file":            fname,
                "session_id":      data.get("session_id"),
                "date":            data.get("date"),
                "target_language": data.get("target_language"),
                "native_language": data.get("native_language"),
                "level":           data.get("level"),
                "turn_count":      data.get("turn_count"),
                "closing_message": data.get("summary", {}).get("closing_message", ""),
            })
        except Exception:
            continue
    return entries

def _session_path(sid: str) -> str:
    return os.path.join(_SESSIONS_DIR, f"{sid}.json")

def _load_session(sid: str) -> dict | None:
    try:
        with open(_session_path(sid)) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None

def _save_session(sid: str, data: dict) -> None:
    with open(_session_path(sid), "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _delete_session(sid: str) -> None:
    try:
        os.unlink(_session_path(sid))
    except FileNotFoundError:
        pass


# ─────────────────────────────────────────────
# Pydantic models
# ─────────────────────────────────────────────
class SessionConfig(BaseModel):
    target_language: str
    language_code: str       # BCP-47 code, e.g. "es-ES"
    native_language: str
    level: str               # Beginner | Intermediate | Advanced | Fluent
    topic: Optional[str] = None
    scenario_type: Optional[str] = None    # scenario key or None
    scenario_context: Optional[str] = None  # URL or free text for job_interview / exec_self / presentations


class MessageRequest(BaseModel):
    session_id: str
    transcript: str
    enriched_transcript: Optional[str] = None  # pause/confidence markers for Advanced/Fluent
    speaking_rate_wpm:   Optional[int] = None   # words per minute from Whisper timing


class FeedbackItem(BaseModel):
    category: str
    issue: str
    original: Optional[str] = None
    correction: Optional[str] = None
    explanation: str


class FillerWord(BaseModel):
    word: str
    count: int
    suggestion: str


class ConversationResponse(BaseModel):
    reply: str
    reply_transliteration: Optional[str] = None
    feedback_items: list[FeedbackItem] = Field(default_factory=list)
    filler_words: list[FillerWord] = Field(default_factory=list)
    overall_assessment: str = ""
    confidence_score: int = Field(default=0, ge=0, le=10)
    suggested_phrases: list[str] = Field(default_factory=list)


# ─────────────────────────────────────────────
# Topic configuration (Beginner / Intermediate)
# ─────────────────────────────────────────────
TOPIC_CONFIGS = {
    # ── Beginner ──────────────────────────────
    "getting_by": {
        "label": "Getting By",
        "guidance": (
            "Set all situations in practical survival contexts: airports, check-in desks, hotels, "
            "asking for directions, buying tickets, transport, finding your way. "
            "Be the helpful local, hotel clerk, ticket agent, or fellow traveller. "
            "Open by asking where the learner is or where they're headed — build on their real situation."
        ),
    },
    "meeting": {
        "label": "Meeting People",
        "guidance": (
            "Focus on introductions and getting to know someone: "
            "names, where you're from, family, what you do, interests. "
            "Be warm and curious — play a new acquaintance at a party, on a train, or at a community event. "
            "Open with a friendly question about the learner themselves."
        ),
    },
    "smalltalk": {
        "label": "Small Talk",
        "guidance": (
            "Light, everyday conversation: weather, weekend plans, daily routines, local events. "
            "Model the rhythm of casual chat — short exchanges, friendly follow-ups, gentle humour. "
            "Open with something natural and invite the learner to share about their own day or week."
        ),
    },
    "food": {
        "label": "Food & Dining",
        "guidance": (
            "Everything around food: ordering at a restaurant or café, food preferences and allergies, "
            "asking for recommendations, favourite dishes, cooking at home. "
            "Play a waiter, fellow diner, or curious friend. "
            "Open by asking what the learner likes to eat or where they like to go."
        ),
    },
    "shopping": {
        "label": "Shopping & Services",
        "guidance": (
            "Practical shopping situations: prices, sizes, asking for help in a shop, "
            "returning items, at the pharmacy, at the post office. "
            "Play a shop assistant, pharmacist, or service desk person. "
            "Open with a natural greeting and offer to help."
        ),
    },
    # ── Intermediate ──────────────────────────
    "flirting": {
        "label": "Flirting & Romance",
        "guidance": (
            "Playful, warm exchanges: compliments, expressing interest, asking someone out, romantic banter. "
            "Fun, a little daring but always tasteful. "
            "Play an interesting stranger at a café, bar, or social event. "
            "Open with something charming — react naturally to what the learner shares."
        ),
    },
    "work": {
        "label": "Work & Studies",
        "guidance": (
            "Professional and academic life: job titles, daily tasks, industry, colleagues, "
            "work-life balance, career goals, studies. "
            "Conversational and relatable — not formal office language. "
            "Open by asking what the learner does and build on their real work or study context."
        ),
    },
    "leisure": {
        "label": "Leisure & Hobbies",
        "guidance": (
            "Sports, travel, culture, music, films, books, weekend activities — whatever the learner enjoys. "
            "Be genuinely curious about their actual interests. "
            "Open by asking what they do in their free time, then follow wherever they take it."
        ),
    },
    "relationships": {
        "label": "Relationships & Friendships",
        "guidance": (
            "Deeper personal conversations: family, friendships, relationships, feelings, plans together. "
            "Warm, emotionally present — play a close friend or trusted acquaintance. "
            "Open with a personal question that invites the learner to talk about people they care about."
        ),
    },
    "presentations": {
        "label": "Short Presentations",
        "guidance": (
            "Practice presenting yourself or your work in a structured but conversational way: "
            "your role, what your team does, a short project update, introducing yourself to a new colleague. "
            "Play a curious colleague or new team member who asks natural follow-up questions. "
            "If context is provided, use it to make the conversation specific to the learner's actual work."
        ),
    },
}

# ─────────────────────────────────────────────
# Level configuration
# ─────────────────────────────────────────────
LEVEL_CONFIGS = {
    "Beginner": {
        "conversation_style": (
            "Use only simple, high-frequency vocabulary. "
            "Keep sentences under 12 words. "
            "Ask exactly one simple yes/no or short-answer question per turn. "
            "Model correct forms naturally in your reply without explicitly pointing them out. "
            "Use present tense predominantly."
        ),
        "feedback_style": (
            "Identify at most 2 issues — do NOT overwhelm a beginner. "
            "Always lead with what was correct before noting errors. "
            "Suggest a corrected version of any wrong phrase. "
            "Do NOT comment on filler words or hesitations. "
            "Tone: warm, encouraging, patient."
        ),
        "topic_guidance": "Stick to everyday topics: greetings, family, food, weather, daily routines.",
        "show_confidence": False,
        "show_filler": False,
    },
    "Intermediate": {
        "conversation_style": (
            "Use natural conversational complexity. "
            "Embed 1-2 new vocabulary items naturally in your reply. "
            "Ask open-ended questions requiring 2-3 sentence answers. "
            "Use a variety of tenses naturally."
        ),
        "feedback_style": (
            "Focus on grammar accuracy with brief explanations (not just corrections). "
            "Note when a more precise or idiomatic word exists. "
            "Flag sentence structure issues such as word order or subordinate clause errors. "
            "Do NOT focus on filler words yet. "
            "Tone: constructive and peer-level."
        ),
        "topic_guidance": "Use moderately complex topics: travel, opinions, culture, current events.",
        "show_confidence": False,
        "show_filler": False,
    },
    "Advanced": {
        "conversation_style": (
            "Speak as a fluent native speaker — no simplification. "
            "Use idioms, collocations, and natural connected speech patterns. "
            "Ask challenging follow-up questions requiring nuanced answers. "
            "Push back on vague responses."
        ),
        "feedback_style": (
            "Deprioritize basic grammar unless it causes ambiguity. "
            "PRIMARY focus: detect filler words (um, uh, like, you know, sort of, basically, right?, "
            "I mean, I guess, kind of, honestly, actually when overused). "
            "Flag unnatural or non-idiomatic phrasing even if grammatically correct. "
            "Note hesitations and suggest confident reformulations. "
            "Comment on rhythm and flow. "
            "Tone: direct coaching, no sugar-coating."
        ),
        "topic_guidance": "Use complex topics: abstract ideas, professional scenarios, debates, storytelling.",
        "show_confidence": True,
        "show_filler": True,
    },
    "Fluent": {
        "conversation_style": (
            "You are a demanding executive communication coach for a near-native speaker. "
            "Use professional, high-stakes register. "
            "Default to scenarios: presenting an argument, negotiating, leading a discussion. "
            "Push back on weak claims, demand precise and confident language."
        ),
        "feedback_style": (
            "Focus exclusively on: verbal tics, filler word patterns, confidence register, "
            "persuasive effectiveness, and executive presence. "
            "Flag repeated tics (e.g., starting sentences with 'So...'). "
            "Flag weak hedging (kind of, maybe, I think when assertion is appropriate). "
            "Show how the same idea sounds more authoritative with a power reformulation. "
            "Comment on strategic communication effectiveness. "
            "Tone: executive coach — high expectations, specific, actionable."
        ),
        "topic_guidance": "Professional contexts: leadership, persuasion, negotiation, public discourse.",
        "show_confidence": True,
        "show_filler": True,
    },
}


# ─────────────────────────────────────────────
# System prompt builder
# ─────────────────────────────────────────────
def build_system_prompt(session: dict) -> str:
    cfg = LEVEL_CONFIGS[session["level"]]

    # Scenario block — injected when a scenario brief has been generated
    sc = session.get("scenario")
    if sc:
        stype = sc.get("type", "")
        coach = sc.get("coach_stance", "Engage naturally and push back where appropriate.")

        if stype == "discuss_depth":
            scenario_block = f"""DISCUSSION SCENARIO:
The learner will debate this statement: "{sc.get("statement", "")}"
Context: {sc.get("context", "")}

YOUR ROLE: {coach}
Push for precision, demand evidence, steelman counter-arguments. Do not let vague assertions pass.
Feedback: coach on argument structure, vocabulary precision, and how confidently they held their position.

"""
        elif stype == "job_interview":
            reqs = "\n".join(f"  • {r}" for r in sc.get("key_requirements", []))
            scenario_block = f"""JOB INTERVIEW SCENARIO:
  Role:            {sc.get("role", "")} at {sc.get("company", "")}
  Team context:    {sc.get("team_context", "")}
  Interview style: {sc.get("interview_style", "")}
  Key requirements:
{reqs}

YOUR ROLE: You are the interviewer. {coach}
Ask real, probing questions. Push back on vague answers. Ask for specific examples.
Feedback: coach on clarity of answers, how well they sold their experience, confident phrasing, and what the interviewer still needs to hear.

"""
        elif stype == "exec_self":
            scenario_block = f"""EXECUTIVE SELF-PRESENTATION SCENARIO:
  Setting:       {sc.get("setting", "")}
  Audience:      {sc.get("audience", "")}
  Objective:     {sc.get("objective", "")}
  Time pressure: {sc.get("time_pressure", "")}

YOUR ROLE: You are in the room. {coach}
Respond as the audience would — test their authority, brevity, and presence.
Feedback: coach on register, word economy, confidence, and whether they commanded the room.

"""
        else:
            # Standard scenario card
            bullets = "\n".join(f"  • {b}" for b in sc.get("bullet_points", []))
            scenario_block = f"""SCENARIO BRIEF:
  Title:      {sc.get("title", "")}
  Their role: {sc.get("your_role", "")}
  Audience:   {sc.get("audience", "")}
  Objective:  {sc.get("objective", "")}
  Material:
{bullets}

YOUR BEHAVIOUR AS AUDIENCE: {coach}
Play the audience role fully. Push back on weak arguments, demand clarity, ask probing questions.
Feedback: coach on how clearly each bullet was communicated, persuasiveness, word choice, pacing, and what the audience still needs.

"""
    else:
        scenario_block = ""

    if session["level"] in ("Advanced", "Fluent"):
        speech_block = """SPEECH TIMING MARKERS IN TRANSCRIPT:
The transcript may contain timing markers injected from audio analysis:
  [Xs pause]             — X seconds of silence at this point. ≥ 0.5s = genuine hesitation.
  [?word]                — Low recognition confidence; this word may have been misheard.
  [Speaking rate: N wpm] — Words per minute for this turn.

MARKER RULES:
- Use [Xs pause] markers as your PRIMARY evidence for hesitancy — never infer hesitation from text alone.
- NEVER give feedback on [?word] tokens — skip them entirely (they may be misheard).
- Multiple pauses in one turn = name the pattern (e.g. "three mid-sentence pauses").
- A single pause ≤ 2s before a complex word is normal processing — don't flag it.
- Speaking rate context: 100–130 wpm = deliberate; 130–160 = natural; 160–200 = fast; >200 = rushed.
- Do NOT include marker notation (e.g. "[1.2s pause]") in your "reply" field.

"""
    else:
        speech_block = ""

    return f"""You are an expert conversational language coach helping a learner practice {session["target_language"]}.

LEARNER PROFILE:
- Native language: {session["native_language"]}
- Target language: {session["target_language"]}
- Proficiency level: {session["level"].upper()}

CONVERSATION STYLE:
{cfg["conversation_style"]}

FEEDBACK STYLE:
{cfg["feedback_style"]}

TOPIC GUIDANCE:
{TOPIC_CONFIGS[session["topic"]]["guidance"] if session.get("topic") and session.get("topic") in TOPIC_CONFIGS else cfg["topic_guidance"]}

{scenario_block}CODE-SWITCHING RULE:
The learner may mix {session["native_language"]} words into their {session["target_language"]} sentences
when they don't know the target word. When this happens:
- In your reply, model the correct {session["target_language"]} phrase naturally (don't call it out mid-conversation).
- In feedback_items, add a "Vocabulary Gap" item: show the {session["native_language"]} word they used,
  give the {session["target_language"]} equivalent, and a short example sentence using it.

VERBATIM TRANSCRIPT RULE:
The transcript is produced by speech recognition and reflects EXACTLY what was said — including
wrong verb tenses, broken grammar, and non-native phrasing. Do NOT assume the learner meant something
correct. Analyse what was actually said and give feedback on it, even if it reads oddly.

{speech_block}CRITICAL RULES:
1. Your "reply" field MUST always be written entirely in {session["target_language"]}.
2. All feedback fields ("feedback_items", "overall_assessment") must be written in English.
3. "reply_transliteration" is ONLY needed for non-Latin scripts (Japanese, Arabic, Korean, Chinese, etc.).
4. If the learner wrote in English or their native language instead of {session["target_language"]},
   acknowledge it gently in your reply (still in {session["target_language"]}) and redirect them.
5. Keep replies engaging — end with a question or prompt to keep the conversation flowing.
6. ALWAYS provide at least 1-2 feedback_items — even for a good response. There is ALWAYS something
   to improve: a more idiomatic phrasing, a stronger word choice, a more natural word order, a richer
   vocabulary option, a more confident register. If the sentence was correct, use category "Upgrade"
   to show how a native speaker would say it more naturally or expressively. Never leave feedback empty.
7. "overall_assessment" must be a concrete 1-sentence coaching note, never just "great job" or "no issues".
   Name one specific strength AND one specific growth edge in every assessment.
8. The "confidence_score" reflects delivery confidence.
   Advanced/Fluent: base it on [Xs pause] count, filler words present, and speaking rate annotation.
   Other levels: base it on um/uh and "..." in text. Score 10 = fluent, no notable pauses.
9. "suggested_phrases" should be 2-3 phrases in {session["target_language"]} the learner
   could use in their NEXT turn, relevant to the current conversation topic.
"""


# ─────────────────────────────────────────────
# Tool schema for structured output
# ─────────────────────────────────────────────
RESPONSE_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {
            "type": "string",
            "description": "Conversational reply IN THE TARGET LANGUAGE. Natural and level-appropriate."
        },
        "reply_transliteration": {
            "type": "string",
            "description": "Romanization for non-Latin scripts only (Japanese, Arabic, etc.). Omit for Latin-script languages."
        },
        "feedback_items": {
            "type": "array",
            "description": "Language feedback items in English. ALWAYS include at least 1 item — even for correct speech use category 'Upgrade' to show a more native or expressive alternative.",
            "items": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "e.g. Grammar, Vocabulary, Sentence Structure, Filler Words, Unnatural Phrasing, Confidence Register, Verbal Tics, Persuasive Language"
                    },
                    "issue": {"type": "string", "description": "What the problem is, in English"},
                    "original": {"type": "string", "description": "The learner's original phrase (in target language)"},
                    "correction": {"type": "string", "description": "Improved version in target language"},
                    "explanation": {"type": "string", "description": "Why this matters, in English"}
                },
                "required": ["category", "issue", "explanation"]
            }
        },
        "filler_words": {
            "type": "array",
            "description": "Filler words detected. Relevant primarily at Advanced/Fluent levels.",
            "items": {
                "type": "object",
                "properties": {
                    "word": {"type": "string"},
                    "count": {"type": "integer", "description": "How many times it appeared"},
                    "suggestion": {"type": "string", "description": "What to do instead"}
                },
                "required": ["word", "count", "suggestion"]
            }
        },
        "overall_assessment": {
            "type": "string",
            "description": "1-2 sentence overall assessment in English. Always find something positive."
        },
        "confidence_score": {
            "type": "integer",
            "description": "Estimated delivery confidence 1-10. Based on hesitation markers in transcript.",
            "minimum": 1,
            "maximum": 10
        },
        "suggested_phrases": {
            "type": "array",
            "description": "2-3 phrases in target language the learner could use in their next turn.",
            "items": {"type": "string"}
        }
    },
    "required": ["reply", "feedback_items", "filler_words", "suggested_phrases", "overall_assessment", "confidence_score"]
}


# ─────────────────────────────────────────────
# API routes
# ─────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def serve_app(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/session/create")
async def create_session(config: SessionConfig):
    session_id = str(uuid.uuid4())
    _save_session(session_id, {
        "target_language": config.target_language,
        "language_code": config.language_code,
        "native_language": config.native_language,
        "level": config.level,
        "topic": config.topic,
        "scenario_type": config.scenario_type,
        "scenario_context": config.scenario_context,
        "scenario": None,   # filled in by /session/{id}/scenario
        "created_at": datetime.utcnow().isoformat(),
        "history": [],
        "turn_count": 0,
    })
    return {"session_id": session_id}


@app.post("/session/message")
async def send_message(req: MessageRequest):
    session = _load_session(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found. Please start a new session.")

    transcript = req.transcript.strip()
    if not transcript:
        raise HTTPException(status_code=400, detail="Empty transcript.")

    # Advanced/Fluent levels use the enriched transcript (with pause + confidence markers);
    # all other levels use the plain transcript to avoid cluttering beginner feedback.
    uses_enriched = session["level"] in ("Advanced", "Fluent")
    claude_content = (
        req.enriched_transcript.strip()
        if uses_enriched and req.enriched_transcript
        else transcript
    )

    # Add user message to history (Claude sees enriched; UI already has the raw version)
    session["history"].append({"role": "user", "content": claude_content})
    session["turn_count"] += 1

    # Trim history: keep first 2 entries (opening context) + recent entries
    history = session["history"]
    if len(history) > MAX_HISTORY_TURNS * 2:
        history = history[:2] + history[-(MAX_HISTORY_TURNS * 2 - 2):]

    try:
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1024,
            system=build_system_prompt(session),
            messages=history,
            tools=[{
                "name": "tutor_response",
                "description": "Structured language tutoring response with reply and feedback",
                "input_schema": RESPONSE_TOOL_SCHEMA
            }],
            tool_choice={"type": "tool", "name": "tutor_response"}
        )
    except anthropic.APIError as e:
        raise HTTPException(status_code=502, detail=f"Claude API error: {str(e)}")

    # Extract structured response from tool_use block
    tool_block = next((b for b in response.content if b.type == "tool_use"), None)
    if not tool_block:
        raise HTTPException(status_code=502, detail="Unexpected response format from Claude.")

    try:
        parsed = ConversationResponse.model_validate(tool_block.input)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Response parsing error: {str(e)}")

    # Store only the reply text in history (not the tool use machinery)
    session["history"].append({"role": "assistant", "content": parsed.reply})
    _save_session(req.session_id, session)

    return parsed


@app.get("/session/{session_id}/info")
async def get_session_info(session_id: str):
    session = _load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    return {
        "target_language": session["target_language"],
        "level": session["level"],
        "turn_count": session["turn_count"],
        "created_at": session["created_at"],
    }


@app.delete("/session/{session_id}")
async def delete_session(session_id: str):
    _delete_session(session_id)
    return {"status": "deleted"}


# ─────────────────────────────────────────────
# Scenario brief generation
# ─────────────────────────────────────────────

# Scenario types that get a full bullet-point brief card
CARD_SCENARIOS = {"pitch", "findings", "difficult", "story", "negotiate", "inspire", "brief", "crisis"}

# ── Tool schemas ──────────────────────────────────────────────────────────────

SCENARIO_CARD_SCHEMA = {
    "type": "object",
    "properties": {
        "title":        {"type": "string"},
        "your_role":    {"type": "string"},
        "audience":     {"type": "string", "description": "Who the learner is speaking to and their attitude"},
        "objective":    {"type": "string", "description": "What the learner must accomplish — 1 sentence"},
        "bullet_points":{"type": "array", "items": {"type": "string"},
                         "description": "3-5 concrete points the learner must communicate"},
        "coach_stance": {"type": "string", "description": "How Claude (as audience) should behave"},
    },
    "required": ["title", "your_role", "audience", "objective", "bullet_points", "coach_stance"]
}

DISCUSS_SCHEMA = {
    "type": "object",
    "properties": {
        "statement":    {"type": "string",
                         "description": "A single bold, provocative statement or question for the learner to react to. Max 20 words."},
        "context":      {"type": "string",
                         "description": "One sentence of background that makes the topic concrete."},
        "coach_stance": {"type": "string",
                         "description": "How Claude should engage: e.g. 'devil's advocate', 'demand evidence', 'steelman the opposite view'"},
    },
    "required": ["statement", "context", "coach_stance"]
}

INTERVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "role":          {"type": "string", "description": "Job title"},
        "company":       {"type": "string", "description": "Company name (invent if not in posting)"},
        "team_context":  {"type": "string", "description": "1 sentence about the team or product area"},
        "key_requirements": {"type": "array", "items": {"type": "string"},
                              "description": "3-5 requirements extracted from the posting or inferred from role"},
        "interview_style":  {"type": "string",
                              "description": "What kind of interview this is: e.g. 'competency-based', 'technical deep-dive', 'culture-fit + portfolio'"},
        "coach_stance":  {"type": "string",
                          "description": "How Claude (as interviewer) should behave: friendly, probing, push for specifics, etc."},
    },
    "required": ["role", "company", "team_context", "key_requirements", "interview_style", "coach_stance"]
}

EXEC_SELF_SCHEMA = {
    "type": "object",
    "properties": {
        "setting":       {"type": "string", "description": "Where this happens and who is in the room"},
        "audience":      {"type": "string", "description": "Who the learner is speaking to and what they care about"},
        "objective":     {"type": "string", "description": "What a successful self-presentation achieves here"},
        "time_pressure": {"type": "string", "description": "e.g. '90 seconds before the agenda moves on'"},
        "coach_stance":  {"type": "string", "description": "How Claude responds — skeptical, distracted, welcoming, etc."},
    },
    "required": ["setting", "audience", "objective", "time_pressure", "coach_stance"]
}

# ── URL fetcher ───────────────────────────────────────────────────────────────

async def fetch_url_text(url: str, max_chars: int = 4000) -> str:
    """Fetch a URL and return stripped plain text, capped at max_chars."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=12,
                                  headers={"User-Agent": "Mozilla/5.0"}) as client_http:
        resp = await client_http.get(url)
        resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    return text[:max_chars]

# ── Scenario endpoint ─────────────────────────────────────────────────────────

@app.post("/session/{session_id}/scenario")
async def generate_scenario(session_id: str):
    session = _load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    stype = session.get("scenario_type")
    if not stype:
        raise HTTPException(status_code=400, detail="No scenario type set for this session.")

    context_raw = session.get("scenario_context") or ""
    lang   = session["target_language"]
    level  = session["level"]

    # ── Route by scenario type ────────────────────────────────────────────────

    if stype in CARD_SCENARIOS:
        labels = {
            "pitch": "Pitch an idea", "findings": "Present findings",
            "difficult": "Handle a difficult conversation", "story": "Tell a compelling story",
            "negotiate": "Negotiate", "inspire": "Inspire & motivate",
            "brief": "Brief a team", "crisis": "Crisis & controversy",
        }
        prompt = f"""Generate a realistic scenario brief for a {level} language learner practising {lang}.

Scenario type: {labels.get(stype, stype)}

Rules:
- Concrete, specific — not generic corporate filler
- Fits a {lang}-speaking context naturally
- Clear communication challenge with real stakes

Use scenario_brief tool."""
        tool_name, schema = "scenario_brief", SCENARIO_CARD_SCHEMA

    elif stype == "discuss_depth":
        prompt = f"""Generate a single bold, provocative statement for a {level} {lang} learner to debate.

The statement should:
- Be genuinely controversial (reasonable people disagree)
- Be concrete enough to argue both sides with evidence
- Feel relevant to a {lang}-speaking context where possible
- Be max 20 words

Use the discuss_prompt tool."""
        tool_name, schema = "discuss_prompt", DISCUSS_SCHEMA

    elif stype == "job_interview":
        # Fetch job posting if a URL was provided
        job_text = context_raw
        if context_raw.startswith("http"):
            try:
                job_text = await fetch_url_text(context_raw)
            except Exception as e:
                job_text = f"[Could not fetch URL: {e}] Role hint from learner: {context_raw}"

        prompt = f"""Extract the key details from this job posting and generate an interview brief.
The interview will be conducted in {lang}.

JOB POSTING:
{job_text or "No posting provided — generate a realistic senior professional role."}

Use the interview_brief tool."""
        tool_name, schema = "interview_brief", INTERVIEW_SCHEMA

    elif stype == "exec_self":
        prompt = f"""Generate a high-stakes executive self-presentation scenario for a fluent {lang} speaker.

Learner's context: {context_raw or "No context provided — invent a plausible senior professional setting."}

The scenario should demand authority, brevity, and presence.
Use the exec_self_brief tool."""
        tool_name, schema = "exec_self_brief", EXEC_SELF_SCHEMA

    else:
        raise HTTPException(status_code=400, detail=f"Unknown scenario type: {stype}")

    try:
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=900,
            messages=[{"role": "user", "content": prompt}],
            tools=[{"name": tool_name, "description": "Structured scenario brief",
                    "input_schema": schema}],
            tool_choice={"type": "tool", "name": tool_name}
        )
    except anthropic.APIError as e:
        raise HTTPException(status_code=502, detail=f"Claude API error: {str(e)}")

    tool_block = next((b for b in response.content if b.type == "tool_use"), None)
    if not tool_block:
        raise HTTPException(status_code=502, detail="No scenario returned.")

    scenario = {"type": stype, **tool_block.input}
    session["scenario"] = scenario
    _save_session(session_id, session)
    return scenario


# ─────────────────────────────────────────────
# Session summary
# ─────────────────────────────────────────────
SUMMARY_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "strengths": {
            "type": "array",
            "description": "2-4 specific things the learner did well, with a concrete example from the conversation for each.",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "detail": {"type": "string", "description": "One sentence with a concrete example from the session."}
                },
                "required": ["title", "detail"]
            }
        },
        "development_areas": {
            "type": "array",
            "description": "2-4 recurring or important patterns to work on, each with a specific tip.",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "detail": {"type": "string", "description": "What was observed and why it matters."},
                    "tip": {"type": "string", "description": "One concrete, actionable improvement tip."}
                },
                "required": ["title", "detail", "tip"]
            }
        },
        "new_vocabulary": {
            "type": "array",
            "description": "Key target-language words or phrases introduced or corrected during the session. Include vocabulary gap fills (native→target word swaps).",
            "items": {
                "type": "object",
                "properties": {
                    "word": {"type": "string", "description": "The target-language word or phrase."},
                    "translation": {"type": "string", "description": "Meaning in the learner's native language."},
                    "example": {"type": "string", "description": "A short natural sentence using the word in the target language."}
                },
                "required": ["word", "translation", "example"]
            }
        },
        "level_recommendation": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["stay", "step_up", "step_down"],
                    "description": "Only suggest step_up or step_down when there is clear, consistent evidence. Default is stay."
                },
                "reasoning": {"type": "string", "description": "One sentence explaining why, or why not."}
            },
            "required": ["action", "reasoning"]
        },
        "closing_message": {
            "type": "string",
            "description": "A warm, personal 2-3 sentence closing note addressing the learner directly. Specific to this session, not generic."
        }
    },
    "required": ["strengths", "development_areas", "new_vocabulary", "level_recommendation", "closing_message"]
}


@app.post("/session/{session_id}/summary")
async def get_session_summary(session_id: str):
    session = _load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    if session["turn_count"] < 2:
        raise HTTPException(status_code=400, detail="Session too short to summarise.")

    # Build a compact transcript for the summary prompt
    history = session["history"]
    transcript_lines = []
    for i, msg in enumerate(history):
        speaker = "Learner" if msg["role"] == "user" else "Coach"
        transcript_lines.append(f"{speaker}: {msg['content']}")
    transcript_text = "\n".join(transcript_lines)

    summary_prompt = f"""You are reviewing a completed language training session.

LEARNER PROFILE:
- Native language: {session["native_language"]}
- Target language: {session["target_language"]}
- Level: {session["level"].upper()}
- Turns completed: {session["turn_count"]}

FULL SESSION TRANSCRIPT:
{transcript_text}

Produce a comprehensive session summary using the summary_report tool.
- Strengths and development areas must cite specific moments from the transcript.
- Vocabulary list should include words that were corrected, introduced, or swapped from native language.
- Level recommendation: only suggest change if there is clear, consistent evidence across multiple turns. Be conservative — most sessions should end with "stay".
- Closing message: personal and specific, not generic encouragement.
"""

    try:
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1500,
            messages=[{"role": "user", "content": summary_prompt}],
            tools=[{
                "name": "summary_report",
                "description": "Structured end-of-session learning summary",
                "input_schema": SUMMARY_TOOL_SCHEMA
            }],
            tool_choice={"type": "tool", "name": "summary_report"}
        )
    except anthropic.APIError as e:
        raise HTTPException(status_code=502, detail=f"Claude API error: {str(e)}")

    tool_block = next((b for b in response.content if b.type == "tool_use"), None)
    if not tool_block:
        raise HTTPException(status_code=502, detail="No summary returned.")

    summary = tool_block.input
    # Persist to history so learners can review past sessions
    session["id"] = session_id
    _save_history_entry(session, summary)
    return summary


# ─────────────────────────────────────────────
# History endpoints
# ─────────────────────────────────────────────
@app.get("/history")
async def list_history():
    return {"entries": _list_history()}


@app.get("/history/{file}")
async def get_history_entry(file: str):
    if ".." in file or "/" in file:
        raise HTTPException(status_code=400, detail="Invalid filename.")
    path = os.path.join(_HISTORY_DIR, file)
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Entry not found.")


@app.delete("/history/{file}")
async def delete_history_entry(file: str):
    if ".." in file or "/" in file:
        raise HTTPException(status_code=400, detail="Invalid filename.")
    path = os.path.join(_HISTORY_DIR, file)
    try:
        os.unlink(path)
        return {"status": "deleted"}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Entry not found.")


def decode_audio(data: bytes) -> np.ndarray:
    """Decode any browser audio format to a float32 mono 16 kHz numpy array using ffmpeg."""
    cmd = [
        _FFMPEG, "-nostdin", "-threads", "0",
        "-i", "pipe:0",                          # read from stdin
        "-f", "s16le", "-ac", "1", "-ar", "16000",
        "pipe:1"                                 # write raw PCM to stdout
    ]
    proc = subprocess.run(cmd, input=data, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode(errors="replace"))
    return np.frombuffer(proc.stdout, np.int16).astype(np.float32) / 32768.0


def build_speech_metadata(result: dict) -> dict:
    """Extract pauses, speaking rate, and low-confidence markers from a Whisper result dict."""
    LOW_LOGPROB = -0.8   # segment avg_logprob below this = flag words as [?word]
    PAUSE_S     = 0.5    # inter-word gap above this = notable pause

    words = []
    for seg in result.get("segments", []):
        low_conf = seg.get("avg_logprob", 0) < LOW_LOGPROB
        for w in seg.get("words", []):
            words.append({
                "word":     w["word"].strip(),
                "start":    w["start"],
                "end":      w["end"],
                "low_conf": low_conf,
            })

    if not words:
        return {"enriched_transcript": result.get("text", "").strip(),
                "speaking_rate_wpm": 0, "pause_count": 0}

    # Notable pauses between consecutive words
    pause_at: dict[int, float] = {}   # index of word *before* the pause → duration
    for i in range(1, len(words)):
        gap = round(words[i]["start"] - words[i - 1]["end"], 2)
        if gap >= PAUSE_S:
            pause_at[i - 1] = gap

    # Speaking rate (wpm)
    duration_s = words[-1]["end"] - words[0]["start"]
    wpm = int((len(words) / duration_s) * 60) if duration_s > 0 else 0

    # Build enriched transcript
    parts = []
    for i, w in enumerate(words):
        token = f"[?{w['word']}]" if w["low_conf"] else w["word"]
        parts.append(token)
        if i in pause_at:
            parts.append(f"[{pause_at[i]}s pause]")

    enriched = " ".join(parts)
    if wpm:
        enriched += f"  [Speaking rate: {wpm} wpm]"

    return {
        "enriched_transcript": enriched,
        "speaking_rate_wpm":   wpm,
        "pause_count":         len(pause_at),
    }


@app.post("/transcribe")
async def transcribe_audio(
    audio: UploadFile = File(...),
    target_language: str = "",
    native_language: str = "",
):
    """
    Decode audio → Whisper with bilingual learner priming.
    - No language lock: auto-detect handles code-switching between target + native.
    - initial_prompt tells Whisper to expect both languages and verbatim errors.
    - condition_on_previous_text=False prevents Whisper from 'correcting' broken speech.
    """
    data = await audio.read()
    try:
        audio_array = decode_audio(data)

        # Prime Whisper for bilingual learner speech
        prompt_parts = ["Language learner's speech."]
        if target_language:
            prompt_parts.append(f"Practicing {target_language}.")
        if native_language:
            prompt_parts.append(
                f"May switch to {native_language} mid-sentence when missing vocabulary."
            )
        prompt_parts.append(
            "Transcribe VERBATIM — including grammatical errors, wrong verb tenses, "
            "hesitations, and non-native phrasing. Do not correct or clean up."
        )
        initial_prompt = " ".join(prompt_parts)

        result = _whisper_model.transcribe(
            audio_array,
            language=None,                    # auto-detect → handles code-switching
            initial_prompt=initial_prompt,    # primes bilingual + verbatim mode
            condition_on_previous_text=False, # prevents "correction drift"
            temperature=0,                    # deterministic, no hallucination
            word_timestamps=True,             # per-word timing for pause extraction
            suppress_tokens=[],               # allow uh/um/eh/typ/liksom through
        )
        meta = build_speech_metadata(result)
        return {
            "transcript":          result["text"].strip(),  # raw — for UI display
            "enriched_transcript": meta["enriched_transcript"],
            "speaking_rate_wpm":   meta["speaking_rate_wpm"],
            "pause_count":         meta["pause_count"],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transcription error: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
