"""
Mock server for UI/design work.
No API keys, no Whisper, no heavy dependencies.
Returns realistic fake data so the full UI is exercisable.

Run:
    pip install fastapi uvicorn jinja2 python-multipart
    python mock_server.py
"""

import uuid
import json
import asyncio
import random
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, Request, UploadFile, File
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

app = FastAPI(title="Conversation Trainer — Mock")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ── In-memory session store ───────────────────────────────────────────────────
_sessions: dict = {}

# ── Pydantic models (mirror app.py) ──────────────────────────────────────────
class SessionConfig(BaseModel):
    target_language: str
    language_code: str
    native_language: str
    level: str
    topic: Optional[str] = None
    scenario_type: Optional[str] = None
    scenario_context: Optional[str] = None

class MessageRequest(BaseModel):
    session_id: str
    transcript: str
    enriched_transcript: Optional[str] = None
    speaking_rate_wpm: Optional[int] = None

# ── Mock data pools ───────────────────────────────────────────────────────────

MOCK_REPLIES = {
    "Portuguese": [
        "Que interessante! E você, onde aprendeu português? Tem viajado ao Brasil?",
        "Muito bem! Você está se saindo muito bem. O que te motivou a aprender português?",
        "Entendo perfeitamente! Então, o que você gosta de fazer no tempo livre?",
        "Boa pergunta! Isso é algo que muita gente se pergunta aqui também.",
    ],
    "Spanish": [
        "¡Muy bien! ¿Y tú, cuánto tiempo llevas estudiando español?",
        "Interesante. ¿Has visitado algún país hispanohablante?",
        "Me parece genial. ¿Qué te motivó a aprender español?",
    ],
    "Swedish": [
        "Intressant! Har du bott i Sverige länge?",
        "Bra jobbat! Vad fick dig att börja lära dig svenska?",
        "Det låter spännande. Vad gillar du att göra på fritiden?",
    ],
    "English": [
        "That's a great point! How long have you been working in this field?",
        "Interesting perspective. Could you elaborate on that?",
        "I see what you mean. What would you say is the biggest challenge?",
    ],
}

MOCK_FEEDBACK = [
    {
        "category": "Grammar",
        "issue": "Verb conjugation in past tense",
        "original": "eu foi ao mercado",
        "correction": "eu fui ao mercado",
        "explanation": "'Fui' is the correct first-person past tense of 'ir'. 'Foi' is third-person (he/she went)."
    },
    {
        "category": "Vocabulary",
        "issue": "More idiomatic word choice available",
        "original": "uma coisa muito boa",
        "correction": "algo excelente / algo incrível",
        "explanation": "'Uma coisa boa' is understood but native speakers would say 'algo incrível' or 'algo ótimo' for more expressive impact."
    },
    {
        "category": "Upgrade",
        "issue": "Correct but could be more natural",
        "original": "Eu gosto muito de isso",
        "correction": "Adoro isso / Isso me agrada muito",
        "explanation": "Your sentence was grammatically fine. A native speaker would drop 'muito' and use 'adoro' for stronger, more natural expression."
    },
    {
        "category": "Sentence Structure",
        "issue": "Word order in subordinate clause",
        "original": "Eu sei que vai ele chegar tarde",
        "correction": "Eu sei que ele vai chegar tarde",
        "explanation": "Subject (ele) must come before the verb phrase in subordinate clauses in Portuguese."
    },
    {
        "category": "Confidence Register",
        "issue": "Hedging weakens the statement",
        "original": "I think maybe this could potentially work",
        "correction": "This will work — here's why.",
        "explanation": "Three hedges in one sentence undercut your authority. Pick one qualifier maximum, or drop them entirely when you're making a recommendation."
    },
    {
        "category": "Filler Words",
        "issue": "Overuse of 'basically'",
        "original": "basically we basically need to basically restructure",
        "correction": "We need to restructure the approach.",
        "explanation": "'Basically' appeared 3 times in one sentence. It signals uncertainty. Cut it entirely — your point is stronger without it."
    },
]

MOCK_FILLER_WORDS = [
    {"word": "um", "count": 3, "suggestion": "Pause silently instead — it reads as considered, not uncertain."},
    {"word": "basically", "count": 2, "suggestion": "Cut entirely. Your point stands without it."},
    {"word": "like", "count": 4, "suggestion": "Replace with 'such as' when listing, or silence when used as a filler."},
]

MOCK_PHRASES = [
    ["Na minha opinião…", "Isso me faz pensar em…", "Você poderia me explicar…"],
    ["Por outro lado…", "Vale a pena mencionar que…", "O que me impressionou foi…"],
    ["Gostaria de acrescentar que…", "Em resumo…", "Discordo um pouco porque…"],
]

MOCK_ASSESSMENTS = [
    "Strong vocabulary range and natural sentence rhythm — work on tightening the verb agreement in subordinate clauses.",
    "Good fluency and confident delivery. The word 'basically' appeared twice; cut it and your authority goes up noticeably.",
    "Clear ideas and good pacing. Push yourself to use the subjunctive — you're ready for it at this level.",
    "Excellent word choice throughout. The one growth edge: your intonation drops at the end of declarative sentences, which can read as uncertain.",
]

# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/")
async def serve_app(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/session/create")
async def create_session(config: SessionConfig):
    sid = str(uuid.uuid4())
    _sessions[sid] = {
        "session_id": sid,
        "target_language": config.target_language,
        "language_code": config.language_code,
        "native_language": config.native_language,
        "level": config.level,
        "topic": config.topic,
        "scenario_type": config.scenario_type,
        "created_at": datetime.utcnow().isoformat(),
        "turn_count": 0,
    }
    return {"session_id": sid}


@app.post("/session/message")
async def send_message(req: MessageRequest):
    session = _sessions.get(req.session_id)
    if not session:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Session not found. Please start a new session.")

    await asyncio.sleep(0.8)  # simulate API latency
    session["turn_count"] = session.get("turn_count", 0) + 1

    lang = session.get("target_language", "Portuguese")
    replies = MOCK_REPLIES.get(lang, MOCK_REPLIES["Portuguese"])
    level = session.get("level", "Intermediate")

    # Pick 1–2 feedback items, cycling through the pool
    turn = session["turn_count"]
    feedback = [MOCK_FEEDBACK[turn % len(MOCK_FEEDBACK)]]
    if turn % 3 == 0:
        feedback.append(MOCK_FEEDBACK[(turn + 2) % len(MOCK_FEEDBACK)])

    show_filler = level in ("Advanced", "Fluent")

    return {
        "reply": replies[turn % len(replies)],
        "reply_transliteration": None,
        "feedback_items": feedback,
        "filler_words": random.sample(MOCK_FILLER_WORDS, 2) if show_filler and turn % 2 == 0 else [],
        "overall_assessment": MOCK_ASSESSMENTS[turn % len(MOCK_ASSESSMENTS)],
        "confidence_score": random.randint(5, 9) if show_filler else 0,
        "suggested_phrases": MOCK_PHRASES[turn % len(MOCK_PHRASES)],
    }


@app.post("/session/{session_id}/scenario")
async def generate_scenario(session_id: str):
    session = _sessions.get(session_id)
    stype = session.get("scenario_type") if session else "pitch"
    await asyncio.sleep(1.0)

    if stype == "discuss_depth":
        return {
            "type": "discuss_depth",
            "statement": "Remote work has permanently broken the conditions for real collaboration.",
            "context": "A topic dividing leadership teams and knowledge workers across industries.",
            "coach_stance": "Devil's advocate — defend remote work's benefits if challenged, but demand evidence."
        }
    elif stype == "job_interview":
        return {
            "type": "job_interview",
            "role": "Senior Product Designer",
            "company": "Forma Health",
            "team_context": "A 6-person product team building a B2B wellness platform scaling from 50 to 500 enterprise clients.",
            "key_requirements": [
                "5+ years product design experience",
                "Strong systems thinking and design systems ownership",
                "Experience with complex B2B workflows",
                "Comfortable with ambiguity in a scaling startup",
            ],
            "interview_style": "Competency-based with portfolio walkthrough",
            "coach_stance": "Friendly but probing — push for specific examples, challenge vague answers."
        }
    elif stype == "exec_self":
        return {
            "type": "exec_self",
            "setting": "First board meeting as newly appointed Chief Product Officer, 12 board members present",
            "audience": "Experienced board with strong financial backgrounds, skeptical of product-led growth claims",
            "objective": "Establish credibility and set the tone for your tenure in under 90 seconds",
            "time_pressure": "90 seconds before the chairperson moves to the next agenda item",
            "coach_stance": "Attentive but impatient — two board members are checking their phones."
        }
    else:
        return {
            "type": stype or "pitch",
            "title": "Q3 Retention Recovery Plan",
            "your_role": "Head of Product presenting to the leadership team",
            "audience": "Skeptical leadership team questioning whether the product roadmap addresses the core churn drivers",
            "objective": "Convince the team to approve the Q4 roadmap reallocation before the budget freeze on Friday",
            "bullet_points": [
                "User retention dropped 11% in Q3, recovering to -4% by end of September",
                "Exit survey data: 67% cite 'too complex to onboard' as primary reason for churn",
                "Competitor Loom simplified onboarding in August — saw 22% signup increase",
                "Proposed fix: dedicate 60% of Q4 engineering to a new guided setup flow",
                "Projected impact: reduce churn by 8% and cut support tickets by 30%",
            ],
            "coach_stance": "Skeptical but persuadable — needs hard numbers, pushes back on scope."
        }


@app.get("/session/{session_id}/info")
async def session_info(session_id: str):
    session = _sessions.get(session_id, {})
    return {
        "target_language": session.get("target_language", "Portuguese"),
        "level": session.get("level", "Intermediate"),
        "turn_count": session.get("turn_count", 0),
        "created_at": session.get("created_at", datetime.utcnow().isoformat()),
    }


@app.post("/session/{session_id}/summary")
async def get_summary(session_id: str):
    await asyncio.sleep(1.5)
    return {
        "strengths": [
            {"title": "Natural sentence rhythm", "detail": "Your pacing felt conversational throughout — notably in the third exchange where you used 'por outro lado' as a connector without prompting."},
            {"title": "Confident vocabulary range", "detail": "You reached for 'surpreendentemente' and 'no entanto' correctly, showing Intermediate-Upper range."},
        ],
        "development_areas": [
            {"title": "Verb tense agreement", "detail": "Past tense errors appeared in 3 of 5 turns — particularly 'foi' vs 'fui'.", "tip": "Practice the 'ir' conjugation table daily for one week. It's the most common irregular verb in conversation."},
            {"title": "Overuse of 'muito'", "detail": "'Muito bom', 'muito interessante', 'muito legal' appeared in every turn.", "tip": "Replace every third 'muito' with a specific adjective: 'fantástico', 'surpreendente', or 'incrível'."},
        ],
        "new_vocabulary": [
            {"word": "no entanto", "translation": "however / nevertheless", "example": "Gostei da ideia; no entanto, o prazo é muito curto."},
            {"word": "fui", "translation": "I went (past tense of ir)", "example": "Fui ao mercado ontem de manhã."},
            {"word": "surpreendentemente", "translation": "surprisingly", "example": "Surpreendentemente, o projeto foi aprovado na primeira revisão."},
        ],
        "level_recommendation": {
            "action": "stay",
            "reasoning": "Consistent fluency with clear vocabulary ambition — one more session focusing on past tense before moving up."
        },
        "closing_message": "You held the conversation well and showed real range today — especially that connector use in turn three. The verb tense errors are the one thing standing between you and a clean Intermediate session. Fix 'fui' and you'll feel the difference immediately."
    }


@app.delete("/session/{session_id}")
async def delete_session(session_id: str):
    _sessions.pop(session_id, None)
    return {"status": "deleted"}


@app.post("/transcribe")
async def transcribe(audio: UploadFile = File(...), target_language: str = "", native_language: str = ""):
    """Return a mock transcript — no Whisper needed."""
    await asyncio.sleep(0.6)
    phrases = [
        "Eu quero praticar português com você hoje.",
        "Acho que é muito importante aprender idiomas.",
        "Pode me ajudar com a pronúncia dessa palavra?",
        "Ontem eu fui ao supermercado e comprei muitas coisas.",
        "Na minha opinião, aprender uma língua nova é sempre útil.",
    ]
    return {"transcript": random.choice(phrases)}


@app.get("/history")
async def get_history():
    return {"sessions": []}


# ── Dev server ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    print("🎨 Mock server running — no API key or Whisper needed")
    print("   Open http://localhost:8001")
    uvicorn.run("mock_server:app", host="0.0.0.0", port=8001, reload=True)
