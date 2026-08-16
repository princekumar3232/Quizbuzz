import os
import json
import sqlite3
import re
import unicodedata

from pathlib import Path
from functools import wraps

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    abort
)

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)


# =========================================================
# APP
# =========================================================

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "quizbuzz-change-this-secret-key"
)


# =========================================================
# PATHS
# =========================================================

BASE_DIR = Path(__file__).resolve().parent

QUESTIONS_FILE = (
    BASE_DIR / "static" / "questions.json"
)

DATABASE_FILE = (
    BASE_DIR / "quizbuzz.db"
)


TIME_PER_QUESTION = 30


# =========================================================
# CATEGORY LABELS
# =========================================================

CATEGORY_LABELS = {
    "teaching": "🎓 Teaching",
    "sports": "🏆 Sports",
    "music": "🎵 Music",
    "physical": "🏃 Physical Education"
}


# =========================================================
# DATABASE
# =========================================================

def get_db():

    conn = sqlite3.connect(
        DATABASE_FILE,
        timeout=30
    )

    conn.row_factory = sqlite3.Row

    return conn


def init_db():

    conn = get_db()

    try:

        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                best_score INTEGER NOT NULL DEFAULT 0
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                text TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id)
                REFERENCES users(id)
                ON DELETE CASCADE
            )
        """)

        conn.commit()

    finally:

        conn.close()


# Initialize database
try:

    init_db()

    print(
        "Database initialized successfully."
    )

except Exception as error:

    print(
        "Database initialization error:",
        error
    )


# =========================================================
# QUESTIONS
# =========================================================

def load_questions():

    if not QUESTIONS_FILE.exists():

        print(
            "Question file not found:",
            QUESTIONS_FILE
        )

        return {}

    try:

        with open(
            QUESTIONS_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        print(
            "Questions loaded successfully."
        )

        return data

    except Exception as error:

        print(
            "Question file error:",
            error
        )

        return {}


QUESTIONS_DATA = load_questions()


# =========================================================
# LOGIN REQUIRED
# =========================================================

def login_required(function):

    @wraps(function)
    def wrapper(*args, **kwargs):

        if "user_id" not in session:

            return redirect(
                url_for("login")
            )

        return function(
            *args,
            **kwargs
        )

    return wrapper


# =========================================================
# ANSWER NORMALIZATION
# =========================================================

def normalize_answer(value):

    if value is None:

        return ""

    value = str(value)

    value = unicodedata.normalize(
        "NFKC",
        value
    )

    value = value.strip().lower()

    # Remove common punctuation
    value = re.sub(
        r"[.!?,;:]+",
        "",
        value
    )

    # Normalize brackets
    value = value.replace(
        "（",
        "("
    )

    value = value.replace(
        "）",
        ")"
    )

    # Remove extra spaces
    value = re.sub(
        r"\s+",
        " ",
        value
    )

    return value.strip()


def answers_match(selected, correct):

    selected_normalized = normalize_answer(
        selected
    )

    correct_normalized = normalize_answer(
        correct
    )

    if not selected_normalized:
        return False

    if not correct_normalized:
        return False

    # Exact match
    if selected_normalized == correct_normalized:
        return True

    # Handle answers such as:
    #
    # Selected:
    # Sunil Gavaskar
    #
    # JSON answer:
    # Sunil Gavaskar (Achieved against Pakistan...)
    #
    if correct_normalized.startswith(
        selected_normalized
    ):

        remaining = correct_normalized[
            len(selected_normalized):
        ].strip()

        if remaining.startswith("("):
            return True

    return False


# =========================================================
# QUESTION VALIDATION
# =========================================================

def clean_questions(question_list):

    if not isinstance(
        question_list,
        list
    ):

        return []

    valid_questions = []

    for item in question_list:

        if not isinstance(
            item,
            dict
        ):

            continue

        question_text = item.get(
            "q",
            ""
        )

        options = item.get(
            "options",
            []
        )

        answer = item.get(
            "answer",
            ""
        )

        if not isinstance(
            question_text,
            str
        ):

            continue

        if not question_text.strip():

            continue

        if not isinstance(
            options,
            list
        ):

            continue

        # Broken questions with no options
        # are not shown in the quiz.
        if len(options) < 2:

            continue

        options = [
            str(option).strip()
            for option in options
            if str(option).strip()
        ]

        if len(options) < 2:

            continue

        if not str(answer).strip():

            continue

        # Copy question so original JSON
        # is never modified.
        cleaned = dict(item)

        cleaned["q"] = question_text.strip()

        cleaned["options"] = options

        cleaned["answer"] = str(
            answer
        ).strip()

        valid_questions.append(
            cleaned
        )

    return valid_questions


# =========================================================
# GET EXAM QUESTIONS
# =========================================================

def get_exam_questions(
    category,
    exam
):

    try:

        category_data = QUESTIONS_DATA[
            category
        ]

        exams_data = category_data.get(
            "exams",
            {}
        )

        exam_data = exams_data[
            exam
        ]

    except (
        KeyError,
        TypeError
    ):

        return []

    # Normal structure:
    #
    # "General Knowledge": [
    #     {...},
    #     {...}
    # ]

    if isinstance(
        exam_data,
        list
    ):

        return clean_questions(
            exam_data
        )

    # Extra support in case a future exam
    # contains subjects:
    #
    # "Exam": {
    #     "Subject 1": [...],
    #     "Subject 2": [...]
    # }

    if isinstance(
        exam_data,
        dict
    ):

        all_questions = []

        for value in exam_data.values():

            if isinstance(
                value,
                list
            ):

                all_questions.extend(
                    value
                )

        return clean_questions(
            all_questions
        )

    return []


# =========================================================
# REGISTER
# =========================================================

@app.route(
    "/register",
    methods=["GET", "POST"]
)
def register():

    if request.method == "POST":

        username = request.form.get(
            "username",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        if not username or not password:

            return render_template(
                "register.html",
                error=(
                    "Sabhi fields bharna "
                    "zaroori hai."
                )
            )

        conn = get_db()

        try:

            cur = conn.cursor()

            cur.execute(
                """
                SELECT id
                FROM users
                WHERE LOWER(username)=LOWER(?)
                """,
                (username,)
            )

            if cur.fetchone():

                return render_template(
                    "register.html",
                    error=(
                        "Ye username pehle se "
                        "registered hai."
                    )
                )

            password_hash = (
                generate_password_hash(
                    password
                )
            )

            cur.execute(
                """
                INSERT INTO users(
                    username,
                    password_hash
                )
                VALUES(?, ?)
                """,
                (
                    username,
                    password_hash
                )
            )

            conn.commit()

        finally:

            conn.close()

        return redirect(
            url_for("login")
        )

    return render_template(
        "register.html"
    )


# =========================================================
# LOGIN
# =========================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if request.method == "POST":

        username = request.form.get(
            "username",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        conn = get_db()

        try:

            cur = conn.cursor()

            cur.execute(
                """
                SELECT *
                FROM users
                WHERE LOWER(username)=LOWER(?)
                """,
                (username,)
            )

            user = cur.fetchone()

        finally:

            conn.close()

        if not user:

            return render_template(
                "login.html",
                error=(
                    "Galat username "
                    "ya password."
                )
            )

        if not check_password_hash(
            user["password_hash"],
            password
        ):

            return render_template(
                "login.html",
                error=(
                    "Galat username "
                    "ya password."
                )
            )

        session.clear()

        session["user_id"] = user["id"]

        session["username"] = (
            user["username"]
        )

        return redirect(
            url_for("index")
        )

    return render_template(
        "login.html"
    )


# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("login")
    )


# =========================================================
# HOME
# =========================================================

@app.route("/")
@login_required
def index():

    return render_template(
        "index.html",
        username=session.get(
            "username"
        ),
        categories=CATEGORY_LABELS
    )


# =========================================================
# CATEGORY → EXAMS
# =========================================================

@app.route(
    "/category/<category>"
)
@login_required
def exams(category):

    if category not in QUESTIONS_DATA:

        abort(404)

    category_data = QUESTIONS_DATA[
        category
    ]

    exams_data = category_data.get(
        "exams",
        {}
    )

    category_label = category_data.get(
        "label",
        CATEGORY_LABELS.get(
            category,
            category.title()
        )
    )

    return render_template(
        "exams.html",
        category=category,
        category_label=category_label,
        exams=exams_data
    )


# =========================================================
# EXAM → QUESTION BANK
# =========================================================

@app.route(
    "/category/<category>/exam/<path:exam>"
)
@login_required
def subjects(
    category,
    exam
):

    if category not in QUESTIONS_DATA:

        abort(404)

    category_data = QUESTIONS_DATA[
        category
    ]

    exams_data = category_data.get(
        "exams",
        {}
    )

    if exam not in exams_data:

        abort(404)

    questions = get_exam_questions(
        category,
        exam
    )

    category_label = category_data.get(
        "label",
        CATEGORY_LABELS.get(
            category,
            category.title()
        )
    )

    return render_template(
        "subjects.html",
        category=category,
        category_label=category_label,
        exam=exam,
        question_count=len(
            questions
        )
    )


# =========================================================
# START QUIZ
# =========================================================

@app.route(
    "/category/<category>/exam/<path:exam>/start"
)
@login_required
def start_test(
    category,
    exam
):

    if category not in QUESTIONS_DATA:

        abort(404)

    category_data = QUESTIONS_DATA[
        category
    ]

    exams_data = category_data.get(
        "exams",
        {}
    )

    if exam not in exams_data:

        abort(404)

    questions = get_exam_questions(
        category,
        exam
    )

    if not questions:

        return render_template(
            "subjects.html",
            category=category,
            category_label=category_data.get(
                "label",
                CATEGORY_LABELS.get(
                    category,
                    category.title()
                )
            ),
            exam=exam,
            question_count=0,
            error=(
                "Is exam mein abhi "
                "valid questions available "
                "nahi hain."
            )
        )

    # IMPORTANT:
    #
    # Complete question list session/cookie
    # mein save nahi kar rahe.
    #
    # Sirf small values save hongi.
    #
    # This prevents large-cookie/session
    # problems on Render.

    session["quiz_category"] = category

    session["quiz_exam"] = exam

    session["q_index"] = 0

    session["score"] = 0

    session["quiz_total"] = len(
        questions
    )

    return redirect(
        url_for("question")
    )


# =========================================================
# QUESTION
# =========================================================

@app.route(
    "/question",
    methods=["GET", "POST"]
)
@login_required
def question():

    category = session.get(
        "quiz_category"
    )

    exam = session.get(
        "quiz_exam"
    )

    if not category or not exam:

        return redirect(
            url_for("index")
        )

    questions = get_exam_questions(
        category,
        exam
    )

    if not questions:

        session.pop(
            "quiz_category",
            None
        )

        session.pop(
            "quiz_exam",
            None
        )

        return redirect(
            url_for("index")
        )

    q_index = int(
        session.get(
            "q_index",
            0
        )
    )

    # Quiz complete
    if q_index >= len(
        questions
    ):

        final_score = int(
            session.get(
                "score",
                0
            )
        )

        total = len(
            questions
        )

        save_best_score(
            final_score
        )

        return render_template(
            "result.html",
            score=final_score,
            total=total,
            category=category,
            exam=exam
        )

    current_question = questions[
        q_index
    ]

    # =====================================================
    # ANSWER SUBMISSION
    # =====================================================

    if request.method == "POST":

        selected = request.form.get(
            "option",
            ""
        )

        correct_answer = (
            current_question.get(
                "answer",
                ""
            )
        )

        is_correct = answers_match(
            selected,
            correct_answer
        )

        current_score = int(
            session.get(
                "score",
                0
            )
        )

        if is_correct:

            current_score += 1

            session["score"] = (
                current_score
            )

        # Move to next question
        session["q_index"] = (
            q_index + 1
        )

        return render_template(
            "answer_feedback.html",
            feedback={
                "is_correct": is_correct,
                "selected": selected,
                "correct_answer": correct_answer
            },
            q_index=q_index + 1,
            total=len(questions)
        )

    # =====================================================
    # SHOW QUESTION
    # =====================================================

    category_data = QUESTIONS_DATA.get(
        category,
        {}
    )

    category_label = category_data.get(
        "label",
        CATEGORY_LABELS.get(
            category,
            category.title()
        )
    )

    return render_template(
        "question.html",
        question=current_question.get(
            "q",
            ""
        ),
        options=current_question.get(
            "options",
            []
        ),
        q_number=q_index + 1,
        total=len(questions),
        time_limit=TIME_PER_QUESTION,
        category_label=category_label,
        exam=exam
    )


# =========================================================
# BEST SCORE
# =========================================================

def save_best_score(score):

    if "user_id" not in session:

        return

    conn = get_db()

    try:

        cur = conn.cursor()

        cur.execute(
            """
            SELECT best_score
            FROM users
            WHERE id=?
            """,
            (
                session["user_id"],
            )
        )

        user = cur.fetchone()

        if (
            user
            and score > user["best_score"]
        ):

            cur.execute(
                """
                UPDATE users
                SET best_score=?
                WHERE id=?
                """,
                (
                    score,
                    session["user_id"]
                )
            )

            conn.commit()

    finally:

        conn.close()


# =========================================================
# NOTES
# =========================================================

@app.route(
    "/notes",
    methods=["GET", "POST"]
)
@login_required
def notes():

    error = None

    if request.method == "POST":

        text = request.form.get(
            "text",
            ""
        ).strip()

        if not text:

            error = (
                "Note likhna zaroori hai."
            )

        else:

            conn = get_db()

            try:

                cur = conn.cursor()

                cur.execute(
                    """
                    INSERT INTO notes(
                        user_id,
                        username,
                        text
                    )
                    VALUES(?, ?, ?)
                    """,
                    (
                        session["user_id"],
                        session["username"],
                        text
                    )
                )

                conn.commit()

            finally:

                conn.close()

            return redirect(
                url_for("notes")
            )

    conn = get_db()

    try:

        cur = conn.cursor()

        cur.execute(
            """
            SELECT *
            FROM notes
            ORDER BY created_at DESC
            LIMIT 50
            """
        )

        all_notes = cur.fetchall()

    finally:

        conn.close()

    return render_template(
        "notes.html",
        notes=all_notes,
        error=error
    )


# =========================================================
# LEADERBOARD
# =========================================================

@app.route("/leaderboard")
@login_required
def leaderboard():

    conn = get_db()

    try:

        cur = conn.cursor()

        cur.execute(
            """
            SELECT username, best_score
            FROM users
            ORDER BY best_score DESC
            LIMIT 20
            """
        )

        top_users = cur.fetchall()

    finally:

        conn.close()

    return render_template(
        "leaderboard.html",
        top_users=top_users
    )


# =========================================================
# HEALTH CHECK
# =========================================================

@app.route("/health")
def health():

    return {
        "status": "ok"
    }


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                5000
            )
        ),
        debug=False
    )
