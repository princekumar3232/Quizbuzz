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
    "quizapp-secret-key-change-this"
)


# =========================================================
# PATHS
# =========================================================

BASE_DIR = Path(__file__).resolve().parent

QUESTIONS_FILE = (
    BASE_DIR / "static" / "questions.json"
)

DATABASE_FILE = (
    BASE_DIR / "quizapp.db"
)


# =========================================================
# SETTINGS
# =========================================================

TIME_PER_QUESTION = 30


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


# =========================================================
# LOAD QUESTIONS
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
# QUESTION HELPERS
# =========================================================

def get_category_data(category):

    category_data = QUESTIONS_DATA.get(
        category
    )

    if not isinstance(
        category_data,
        dict
    ):
        abort(404)

    return category_data


def get_exams_data(category):

    category_data = get_category_data(
        category
    )

    exams = category_data.get(
        "exams",
        {}
    )

    if not isinstance(
        exams,
        dict
    ):
        return {}

    return exams


def get_exam_questions(
    category,
    exam
):

    exams = get_exams_data(
        category
    )

    if exam not in exams:
        abort(404)

    questions = exams[exam]

    if not isinstance(
        questions,
        list
    ):
        return []

    valid_questions = []

    for question in questions:

        if not isinstance(
            question,
            dict
        ):
            continue

        text = question.get(
            "q"
        )

        options = question.get(
            "options"
        )

        answer = question.get(
            "answer"
        )

        if not text:
            continue

        if not isinstance(
            options,
            list
        ):
            continue

        if len(options) < 2:
            continue

        if answer is None:
            continue

        if str(answer).strip() == "":
            continue

        valid_questions.append(
            question
        )

    return valid_questions


def normalize_answer(value):

    if value is None:
        return ""

    text = str(value)

    text = unicodedata.normalize(
        "NFKC",
        text
    )

    text = text.strip().lower()

    # Convert multiple spaces into one.
    text = re.sub(
        r"\s+",
        " ",
        text
    )

    # Remove punctuation only from
    # the beginning/end.
    text = text.strip(
        " \t\r\n.,!?;:،۔"
    )

    return text


def answers_match(
    selected,
    correct
):

    selected_normalized = (
        normalize_answer(selected)
    )

    correct_normalized = (
        normalize_answer(correct)
    )

    if not selected_normalized:
        return False

    if not correct_normalized:
        return False

    return (
        selected_normalized
        == correct_normalized
    )


# =========================================================
# INITIALIZE DATABASE
# =========================================================

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
# LOGIN REQUIRED
# =========================================================

def login_required(function):

    @wraps(function)
    def wrapper(
        *args,
        **kwargs
    ):

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

            existing = cur.fetchone()

            if existing:

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
                    "Galat username ya password."
                )
            )

        if not check_password_hash(
            user["password_hash"],
            password
        ):

            return render_template(
                "login.html",
                error=(
                    "Galat username ya password."
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

    category_data = (
        get_category_data(
            category
        )
    )

    exams_data = (
        category_data.get(
            "exams",
            {}
        )
    )

    category_label = (
        category_data.get(
            "label",
            CATEGORY_LABELS.get(
                category,
                category.title()
            )
        )
    )

    exam_list = []

    for exam_name in exams_data:

        questions = (
            get_exam_questions(
                category,
                exam_name
            )
        )

        exam_list.append({
            "name": exam_name,
            "total": len(questions)
        })

    return render_template(
        "exams.html",
        category=category,
        category_label=category_label,
        exams=exam_list
    )


# =========================================================
# EXAM → SUBJECT/PREVIEW
# =========================================================

@app.route(
    "/category/<category>/exam/<path:exam>"
)
@login_required
def subjects(
    category,
    exam
):

    category_data = (
        get_category_data(
            category
        )
    )

    questions = (
        get_exam_questions(
            category,
            exam
        )
    )

    category_label = (
        category_data.get(
            "label",
            CATEGORY_LABELS.get(
                category,
                category.title()
            )
        )
    )

    # Current JSON has:
    #
    # category
    #     ↓
    # exams
    #     ↓
    # exam name
    #     ↓
    # questions
    #
    # There is no separate "subject"
    # field in the current JSON.
    #
    # Therefore the exam itself is
    # treated as the quiz/subject.

    subject = {
        "name": exam,
        "total": len(questions)
    }

    return render_template(
        "subjects.html",
        category=category,
        category_label=category_label,
        exam=exam,
        subjects=[subject]
    )


# =========================================================
# START TEST
# =========================================================

@app.route(
    "/category/<category>/exam/<path:exam>/subject/<path:subject>"
)
@login_required
def start_test(
    category,
    exam,
    subject
):

    questions = (
        get_exam_questions(
            category,
            exam
        )
    )

    if not questions:

        return render_template(
            "subjects.html",
            category=category,
            category_label=CATEGORY_LABELS.get(
                category,
                category.title()
            ),
            exam=exam,
            subjects=[
                {
                    "name": exam,
                    "total": 0
                }
            ],
            error=(
                "Is quiz mein abhi "
                "valid questions available nahi hain."
            )
        )

    # IMPORTANT:
    #
    # Pura question list session mein
    # store nahi kar rahe.
    #
    # Isse large question bank ke
    # cookie/session size ka problem
    # nahi hoga.

    session["quiz_category"] = (
        category
    )

    session["quiz_exam"] = (
        exam
    )

    session["quiz_subject"] = (
        subject
    )

    session["score"] = 0

    session["q_index"] = 0

    session["quiz_total"] = (
        len(questions)
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

    subject = session.get(
        "quiz_subject"
    )

    if not category or not exam:

        return redirect(
            url_for("index")
        )

    questions = (
        get_exam_questions(
            category,
            exam
        )
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

        session.pop(
            "quiz_subject",
            None
        )

        return redirect(
            url_for("index")
        )

    total = len(questions)

    session["quiz_total"] = total

    q_index = int(
        session.get(
            "q_index",
            0
        )
    )

    # =====================================================
    # QUIZ FINISHED
    # =====================================================

    if q_index >= total:

        final_score = int(
            session.get(
                "score",
                0
            )
        )

        save_best_score(
            final_score
        )

        return render_template(
            "result.html",
            score=final_score,
            total=total
        )


    # =====================================================
    # CURRENT QUESTION
    # =====================================================

    current_question = (
        questions[q_index]
    )

    if request.method == "POST":

        selected = request.form.get(
            "option"
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

        if is_correct:

            session["score"] = (
                int(
                    session.get(
                        "score",
                        0
                    )
                ) + 1
            )

        session["last_feedback"] = {

            "is_correct": is_correct,

            "selected": selected,

            "correct_answer": (
                correct_answer
            )
        }

        session["q_index"] = (
            q_index + 1
        )

        return render_template(
            "answer_feedback.html",
            feedback=(
                session[
                    "last_feedback"
                ]
            ),
            q_index=q_index + 1,
            total=total
        )


    # =====================================================
    # SHOW QUESTION
    # =====================================================

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

        total=total,

        time_limit=TIME_PER_QUESTION,

        category_label=(
            CATEGORY_LABELS.get(
                category,
                category.title()
            )
        ),

        exam=exam,

        subject=subject
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

@app.route(
    "/leaderboard"
)
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
