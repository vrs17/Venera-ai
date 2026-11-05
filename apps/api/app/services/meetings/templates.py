"""Xulosa shablonlari va bo'lim sarlavhalari (spetsifikatsiya 6.4).

HAR SHABLON UMUMIY YADRONI SAQLAYDI: overview, topics, keyPoints, decisions,
actionItems, openQuestions, risks, numbers, dates, nextSteps, nextMeeting,
highlights, participants, keywords, sentiment. Shablon faqat promptga urg'u
paragrafini, `templateSections` kalitlarini va bo'limlar tartibini qo'shadi.
Sabab: Plaud qamraydigan hamma narsa HAR xulosada bo'lsin - shablon tanlovi
noto'g'ri bo'lsa ham vazifa yoki qaror yo'qolmasin.

SARLAVHALAR KODDA, modelda emas (`SECTION_TITLES`): model har safar boshqacha
nom yozardi, ilova va eksport esa bir xil ko'rinishi kerak. Testi lug'at
to'liqligini tekshiradi.

Har shablonda O'Z `version` i: shablon matni o'zgarsa eski xulosalar
"bir xil" hisoblanmasin (`POST /summaries` takrorlanishini tekshirish).
"""

from __future__ import annotations

from dataclasses import dataclass, field

LANGS = ("uz", "ru", "en")

#: Hamma shablon identifikatorlari - API `TemplateId` turi bilan bir xil tartibda.
TEMPLATE_IDS = ("auto", "general", "minutes", "standup", "one_on_one", "project_review",
                "brainstorm", "sales_call", "interview", "lecture", "short_call", "follow_up")

#: Umumiy yadro bo'limlari - `layout` ning default tartibi. `followUps` - KOD yig'adigan
#: "hal qilinmagan masalalar" (Plaud'ning "AI Suggestion" bloki o'rnida, lekin maslahat
#: to'qimasdan): ochiq savollar, taxminiy/shartli qarorlar, egasiz yoki muddatsiz
#: vazifalar, yechimsiz xavflar - har biri o'z elementiga havola bilan.
CORE_LAYOUT = ("overview", "actionItems", "decisions", "followUps", "topics", "keyPoints", "openQuestions",
               "risks", "numbers", "dates", "nextSteps", "nextMeeting", "highlights",
               "participants", "keywords", "sentiment")

#: `short_call` da qoladigan bo'limlar; qolganlari bo'shatiladi. Qisqa mijoz
#: qo'ng'irog'ining narxi, ochiq savoli va keyingi uchrashuvi ham YO'QOLMASIN.
#: `keyPoints` (2026-10-10): "Qisqa xulosa"ning "Asosiy fikrlar"i qisqa qo'ng'iroqda ham
#: bo'lishi shart - foydalanuvchi aynan shu ko'rinishni ulashadi; umumiy xulosadan keyin.
SHORT_CALL_KEEP = ("overview", "keyPoints", "actionItems", "decisions", "followUps", "openQuestions", "numbers",
                   "dates", "nextMeeting", "highlights")


@dataclass(frozen=True)
class Template:
    id: str
    version: str
    title: dict[str, str]
    description: dict[str, str]
    #: Klassifikator shu shablonni tanlay oladimi (`auto`).
    auto: bool
    #: Faqat qo'shimcha tab sifatida (asosiy xulosa bo'lmaydi).
    extra_tab: bool
    #: Promptdagi urg'u paragrafi (inglizcha - gemma shuni yaxshi bajaradi).
    emphasis: str
    #: `templateSections` kalitlari va ularning bir qatorli ma'nosi.
    sections: tuple[tuple[str, str], ...] = ()
    #: Bo'limlar tartibi (bo'sh - `CORE_LAYOUT`, shablon bo'limlari qarorlardan keyin).
    layout: tuple[str, ...] = field(default_factory=tuple)


def _t(uz: str, ru: str, en: str) -> dict[str, str]:
    return {"uz": uz, "ru": ru, "en": en}


TEMPLATES: dict[str, Template] = {t.id: t for t in (
    Template(
        "auto", "auto-1",
        _t("Avtomatik", "Автоматически", "Automatic"),
        _t("Turini Barno o'zi aniqlaydi", "Тип определит Барно", "Barno picks the type"),
        auto=False, extra_tab=False, emphasis="",
    ),
    Template(
        "general", "general-1",
        _t("Umumiy yig'ilish", "Общая встреча", "General meeting"),
        _t("Muvozanatli xulosa: qarorlar, vazifalar, ochiq savollar",
           "Сбалансированное резюме: решения, задачи, открытые вопросы",
           "Balanced summary: decisions, action items, open questions"),
        auto=True, extra_tab=False,
        emphasis="General meeting. Balanced coverage of every core section.",
    ),
    Template(
        "minutes", "minutes-1",
        # 2026-11-04: "Bayonnoma" -> "Protokol": rasmiy hujjat (`minutes/`, Word/PDF) endi
        # "Bayonnoma" deb ataladi; bu shablon - xulosa KARTASI, ikkalasi bir menyuda chalkashmasin.
        _t("Protokol", "Протокол", "Minutes"),
        _t("Rasmiy protokol ko'rinishidagi xulosa: kun tartibi, muhokama, qaror, ovoz berish",
           "Официальный протокол: повестка, обсуждение, решение, голосование",
           "Formal minutes: agenda, discussion, decision, votes"),
        auto=True, extra_tab=False,
        emphasis=("Formal minutes. Treat each topic as an agenda item: its summary is the discussion "
                  "and its outcome the decision. Record attendees as named, votes with counts if stated, "
                  "and whether previous minutes were approved."),
        sections=(("attendees", "people named as present, as spoken"),
                  ("votes", "each vote: question and result/counts as stated"),
                  ("approvedPrevious", "approval of previous minutes, if mentioned")),
    ),
    Template(
        "standup", "standup-1",
        _t("Stend-ap / holat", "Стендап / статус", "Stand-up / status"),
        _t("Har kim: nima qildi, nima qiladi, nima to'sqinlik qilyapti",
           "Каждый: что сделал, что сделает, что мешает",
           "Per person: done, next, blockers"),
        auto=True, extra_tab=False,
        emphasis=("Stand-up / status round. For every speaker capture what they did, what they will do "
                  "next and their blockers; every item MUST carry `speaker`. Next steps of each person "
                  "are also action items with that person as owner."),
        sections=(("done", "work a person reports as finished (speaker set)"),
                  ("next", "work a person says they will do next (speaker set)"),
                  ("blockers", "what blocks a person (speaker set)")),
    ),
    Template(
        "one_on_one", "one_on_one-1",
        _t("1:1 suhbat", "Встреча 1:1", "One-on-one"),
        _t("Yutuqlar, muammolar, fikr-mulohaza, kelishuvlar, o'sish",
           "Успехи, проблемы, обратная связь, договорённости, рост",
           "Wins, issues, feedback, agreements, growth"),
        auto=True, extra_tab=False,
        emphasis=("One-on-one meeting between two people. Personal topics are allowed: the meeting is "
                  "private. Capture wins, issues, feedback in both directions, agreements and growth "
                  "goals. Do not judge either person."),
        sections=(("wins", "achievements mentioned"), ("issues", "problems raised"),
                  ("feedbackGiven", "feedback the lead gave"),
                  ("feedbackReceived", "feedback the lead received"),
                  ("agreements", "what both agreed on"),
                  ("growth", "growth / development goals")),
    ),
    Template(
        "project_review", "project_review-1",
        _t("Loyiha ko'rigi", "Обзор проекта", "Project review"),
        _t("Holat, bosqichlar, muddatlar, o'zgarishlar, bog'liqliklar",
           "Статус, этапы, сроки, изменения, зависимости",
           "Status, milestones, deadlines, scope changes, dependencies"),
        auto=True, extra_tab=False,
        emphasis=("Project review. Capture the project status, milestones with dates, scope changes and "
                  "dependencies; deadlines go to `dates` and to action items."),
        sections=(("status", "overall status statements (on track / delayed / blocked)"),
                  ("milestones", "milestones with their date or state"),
                  ("scopeChanges", "added, removed or changed scope"),
                  ("dependencies", "what the project waits on, and who")),
    ),
    Template(
        "brainstorm", "brainstorm-1",
        _t("Aqliy hujum", "Мозговой штурм", "Brainstorm"),
        _t("G'oyalar, ijobiy va salbiy tomonlar, tanlanganlar",
           "Идеи, плюсы и минусы, шорт-лист",
           "Ideas, pros, cons, shortlist"),
        auto=True, extra_tab=False,
        emphasis=("Brainstorm: many ideas, few decisions. Prefer recall over ideas: list every distinct "
                  "idea as \"theme: idea\". Every next exploration needs an owner as an action item."),
        sections=(("ideas", "\"theme: idea\" for every distinct idea"),
                  ("pros", "arguments for an idea"), ("cons", "arguments against an idea"),
                  ("shortlist", "ideas the group chose to pursue")),
    ),
    Template(
        "sales_call", "sales_call-1",
        _t("Mijoz / savdo qo'ng'irog'i", "Звонок клиенту / продажи", "Client / sales call"),
        _t("Mijoz ehtiyoji, byudjet, e'tirozlar, majburiyatlar",
           "Потребности клиента, бюджет, возражения, обязательства",
           "Client needs, budget, objections, commitments"),
        auto=True, extra_tab=False,
        emphasis=("Client / sales call. Capture the client's needs and pain points, BANT (budget, "
                  "authority, need, timeline), objections, commitments of each side and competitors. "
                  "`sentiment` describes the client's intent."),
        sections=(("clientNeeds", "what the client needs"), ("painPoints", "client problems"),
                  ("budget", "budget statements"), ("authority", "who decides / signs"),
                  ("need", "how strong the need is"), ("timeline", "client's timeline"),
                  ("objections", "client objections"),
                  ("ourCommitments", "what our side promised"),
                  ("clientCommitments", "what the client promised"),
                  ("competitors", "competitors mentioned")),
    ),
    Template(
        "interview", "interview-2",
        _t("Suhbat (ishga qabul)", "Собеседование", "Job interview"),
        _t("Tajriba, kompetensiyalar, nomzod savollari, xavotirlar",
           "Опыт, компетенции, вопросы кандидата, опасения",
           "Background, competencies, candidate questions, concerns"),
        auto=True, extra_tab=False,
        emphasis=("Job interview. Capture the candidate's background, competencies with evidence, the "
                  "candidate's questions and stated concerns. Salary expectations may be recorded. NEVER give "
                  "a hire/no-hire verdict and NEVER mention health, family or other protected attributes (age, "
                  "gender, religion, ethnicity)."),
        sections=(("background", "candidate's experience as stated"),
                  ("competencies", "\"competency: evidence\""),
                  ("candidateQuestions", "questions the candidate asked"),
                  ("concerns", "concerns raised by either side")),
    ),
    Template(
        "lecture", "lecture-1",
        _t("Ma'ruza / trening", "Лекция / тренинг", "Lecture / training"),
        _t("Tushunchalar, misollar, savol-javob, uy vazifasi",
           "Понятия, примеры, вопросы-ответы, домашнее задание",
           "Concepts, examples, Q&A, homework"),
        auto=True, extra_tab=False,
        emphasis=("Lecture or training with one dominant speaker. Capture concepts as \"term: "
                  "definition\", examples, questions with their answers, and homework."),
        sections=(("concepts", "\"term: definition\""), ("examples", "examples given"),
                  ("qa", "question and its answer"), ("homework", "assigned homework")),
    ),
    Template(
        "short_call", "short_call-3",
        _t("Qisqa qo'ng'iroq", "Короткий звонок", "Short call"),
        _t("Qisqa: xulosa, asosiy fikrlar, vazifalar, qarorlar, raqamlar",
           "Кратко: резюме, ключевые моменты, задачи, решения, цифры",
           "Short: overview, key points, action items, decisions, numbers"),
        auto=True, extra_tab=False,
        emphasis=("Short call. Write the purpose, a 1-2 sentence overview and 3-6 short keyPoints. The action "
                  "items, decisions, open questions, key numbers, dates, highlights and a next meeting (if one "
                  "was set) matter; keep topics, risks, nextSteps and templateSections empty."),
        layout=SHORT_CALL_KEEP,
    ),
    Template(
        "follow_up", "follow_up-1",
        _t("Kuzatuv xabari", "Письмо по итогам", "Follow-up message"),
        _t("Ishtirokchilarga yuboriladigan xabar matni",
           "Текст письма участникам по итогам встречи",
           "A message to send to the participants"),
        auto=False, extra_tab=True,
        emphasis=("Follow-up message. Besides the core sections, write `followUpMessage`: a plain-text "
                  "message (no markdown) for Telegram or email in the output language: a short thanks, "
                  "a recap, the decisions, every action item with its owner and due date, and the next "
                  "meeting if one was set. Use [S#] tokens for speakers."),
        layout=("followUpMessage", "overview", "actionItems", "decisions", "nextMeeting"),
    ),
)}


#: Bo'lim sarlavhalari: kalit -> til -> sarlavha. Yadro + shablon bo'limlari.
SECTION_TITLES: dict[str, dict[str, str]] = {
    "overview": _t("Qisqacha", "Кратко", "Overview"),
    "purpose": _t("Maqsad", "Цель", "Purpose"),
    "actionItems": _t("Vazifalar", "Задачи", "Action items"),
    "decisions": _t("Qarorlar", "Решения", "Decisions"),
    "followUps": _t("Hal qilinmagan masalalar", "Нерешённые вопросы", "Needs follow-up"),
    "topics": _t("Mavzular", "Темы", "Topics"),
    "keyPoints": _t("Asosiy fikrlar", "Ключевые моменты", "Key points"),
    "openQuestions": _t("Ochiq savollar", "Открытые вопросы", "Open questions"),
    "risks": _t("Xavflar", "Риски", "Risks"),
    "numbers": _t("Raqamlar", "Цифры", "Key numbers"),
    "dates": _t("Sanalar va muddatlar", "Даты и сроки", "Dates and deadlines"),
    "nextSteps": _t("Keyingi qadamlar", "Следующие шаги", "Next steps"),
    "nextMeeting": _t("Keyingi yig'ilish", "Следующая встреча", "Next meeting"),
    "highlights": _t("Muhim lahzalar", "Важные моменты", "Highlights"),
    "participants": _t("Ishtirokchilar", "Участники", "Participants"),
    "keywords": _t("Kalit so'zlar", "Ключевые слова", "Keywords"),
    "sentiment": _t("Kayfiyat", "Настроение", "Sentiment"),
    "followUpMessage": _t("Kuzatuv xabari", "Письмо по итогам", "Follow-up message"),
    # minutes
    "attendees": _t("Qatnashganlar", "Присутствовали", "Attendees"),
    "votes": _t("Ovoz berish", "Голосование", "Votes"),
    "approvedPrevious": _t("Oldingi bayonnoma", "Предыдущий протокол", "Previous minutes"),
    # standup
    "done": _t("Bajarildi", "Сделано", "Done"),
    "next": _t("Keyingi ishlar", "Далее", "Next"),
    "blockers": _t("To'siqlar", "Блокеры", "Blockers"),
    # one_on_one
    "wins": _t("Yutuqlar", "Успехи", "Wins"),
    "issues": _t("Muammolar", "Проблемы", "Issues"),
    "feedbackGiven": _t("Berilgan fikr-mulohaza", "Данная обратная связь", "Feedback given"),
    "feedbackReceived": _t("Olingan fikr-mulohaza", "Полученная обратная связь", "Feedback received"),
    "agreements": _t("Kelishuvlar", "Договорённости", "Agreements"),
    "growth": _t("O'sish", "Развитие", "Growth"),
    # project_review
    "status": _t("Holat", "Статус", "Status"),
    "milestones": _t("Bosqichlar", "Этапы", "Milestones"),
    "scopeChanges": _t("Hajmdagi o'zgarishlar", "Изменения объёма", "Scope changes"),
    "dependencies": _t("Bog'liqliklar", "Зависимости", "Dependencies"),
    # brainstorm
    "ideas": _t("G'oyalar", "Идеи", "Ideas"),
    "pros": _t("Afzalliklar", "Плюсы", "Pros"),
    "cons": _t("Kamchiliklar", "Минусы", "Cons"),
    "shortlist": _t("Tanlanganlar", "Шорт-лист", "Shortlist"),
    # sales_call
    "clientNeeds": _t("Mijoz ehtiyojlari", "Потребности клиента", "Client needs"),
    "painPoints": _t("Mijoz muammolari", "Боли клиента", "Pain points"),
    "budget": _t("Byudjet", "Бюджет", "Budget"),
    "authority": _t("Qaror qiluvchi", "ЛПР", "Authority"),
    "need": _t("Ehtiyoj", "Потребность", "Need"),
    "timeline": _t("Muddat", "Сроки", "Timeline"),
    "objections": _t("E'tirozlar", "Возражения", "Objections"),
    "ourCommitments": _t("Bizning majburiyatlar", "Наши обязательства", "Our commitments"),
    "clientCommitments": _t("Mijoz majburiyatlari", "Обязательства клиента", "Client commitments"),
    "competitors": _t("Raqobatchilar", "Конкуренты", "Competitors"),
    # interview
    "background": _t("Tajriba", "Опыт", "Background"),
    "competencies": _t("Kompetensiyalar", "Компетенции", "Competencies"),
    "candidateQuestions": _t("Nomzod savollari", "Вопросы кандидата", "Candidate questions"),
    "concerns": _t("Xavotirlar", "Опасения", "Concerns"),
    # lecture
    "concepts": _t("Tushunchalar", "Понятия", "Concepts"),
    "examples": _t("Misollar", "Примеры", "Examples"),
    "qa": _t("Savol-javob", "Вопросы и ответы", "Q&A"),
    "homework": _t("Uy vazifasi", "Домашнее задание", "Homework"),
}


def get(template_id: str) -> Template:
    return TEMPLATES.get(template_id) or TEMPLATES["general"]


def section_keys(template_id: str) -> list[str]:
    return [key for key, _ in get(template_id).sections]


def layout(template_id: str, lang: str) -> list[dict[str, str]]:
    """Bo'limlar tartibi va sarlavhalari (xulosa tilida)."""
    tpl = get(template_id)
    lang = lang if lang in LANGS else "uz"
    if tpl.layout:
        keys = list(tpl.layout)
    else:
        keys = list(CORE_LAYOUT)
        # Shablon bo'limlari qarorlardan keyin: ular shablonning "yuragi"
        # (`followUps` ulardan keyin keladi).
        at = keys.index("decisions") + 1
        keys[at:at] = section_keys(template_id)
    return [{"key": k, "title": SECTION_TITLES.get(k, {}).get(lang, k)} for k in keys]


def catalog(lang: str) -> list[dict[str, object]]:
    """`GET /meetings/config` dagi `templates` - `Accept-Language` tilida."""
    lang = lang if lang in LANGS else "uz"
    return [{"id": t.id, "title": t.title[lang], "description": t.description[lang],
             "auto": t.auto, "extraTab": t.extra_tab} for t in TEMPLATES.values()]
