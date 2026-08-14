import os
import json
from functools import wraps
from pathlib import Path

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    abort,
)

from werkzeug.security import generate_password_hash, check_password_hash
import psycopg
from psycopg.rows import dict_row


app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "dev-fallback-key-change-me"
)

DATABASE_URL = os.environ.get("DATABASE_URL")

TIME_PER_QUESTION = 10
CHECKPOINT_EVERY = 10


# --------------------------------------------------
# QUESTION DATA
# --------------------------------------------------

QUESTIONS_FILE = (
    Path(__file__).parent
    / "static"
    / "questions.json"
)


def load_questions():
    if not QUESTIONS_FILE.exists():
        return {}

    try:
        return json.loads(
            QUESTIONS_FILE.read_text(
                encoding="utf-8"
            )
        )
    except json.JSONDecodeError:
        return {}


QUESTIONS_DATA = load_questions()


CATEGORY_LABELS = {
    "teaching": "🎓 Teaching",
    "sports": "🏆 Sports",
    "music": "🎵 Music",
    "physical": "🏃 Physical",
}


# --------------------------------------------------
# DATABASE
# --------------------------------------------------

def get_db():
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL environment variable missing."
        )

    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row
    )


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            best_score INTEGER NOT NULL DEFAULT 0
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL
                REFERENCES users(id),
            username TEXT NOT NULL,
            text TEXT NOT NULL,
            created_at TIMESTAMP
                DEFAULT CURRENT_TIMESTAMP
        );
    """)

    conn.commit()

    cur.close()
    conn.close()


# --------------------------------------------------
# LOGIN REQUIRED
# --------------------------------------------------

def login_required(f):

    @wraps(f)
    def wrapper(*args, **kwargs):

        if "user_id" not in session:
            return redirect(
                url_for("login")
            )

        return f(*args, **kwargs)

    return wrapper


# --------------------------------------------------
# REGISTER
# --------------------------------------------------

@app.route(
    "/register",
    methods=["GET", "POST"]
)
def register():

    if request.method == "POST":

        username = request.form[
            "username"
        ].strip()

        password = request.form[
            "password"
        ]

        if not username or not password:

            return render_template(
                "register.html",
                error="Sabhi field zaroori hain."
            )

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT id
            FROM users
            WHERE LOWER(username)
                = LOWER(%s)
            """,
            (username,)
        )

        existing = cur.fetchone()

        if existing:

            cur.close()
            conn.close()

            return render_template(
                "register.html",
                error="Ye username pehle se hai."
            )

        cur.execute(
            """
            INSERT INTO users
            (
                username,
                password_hash
            )
            VALUES (%s, %s)
            """,
            (
                username,
                generate_password_hash(password)
            )
        )

        conn.commit()

        cur.close()
        conn.close()

        return redirect(
            url_for("login")
        )

    return render_template(
        "register.html"
    )


# --------------------------------------------------
# LOGIN
# --------------------------------------------------

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if request.method == "POST":

        username = request.form[
            "username"
        ].strip()

        password = request.form[
            "password"
        ].strip()

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT *
            FROM users
            WHERE LOWER(username)
                = LOWER(%s)
            """,
            (username,)
        )

        user = cur.fetchone()

        cur.close()
        conn.close()

        if (
            user is None
            or not check_password_hash(
                user["password_hash"],
                password
            )
        ):

            return render_template(
                "login.html",
                error="Galat username ya password."
            )

        session["user_id"] = user["id"]
        session["username"] = user["username"]

        return redirect(
            url_for("index")
        )

    return render_template(
        "login.html"
    )


# --------------------------------------------------
# LOGOUT
# --------------------------------------------------

@app.route("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("login")
    )


# --------------------------------------------------
# HOME
# --------------------------------------------------

@app.route("/")
@login_required
def index():

    return render_template(
        "index.html",
        username=session["username"],
        categories=CATEGORY_LABELS
    )


# --------------------------------------------------
# CATEGORY → EXAMS
# --------------------------------------------------

@app.route("/category/<category>")
@login_required
def exams(category):

    if category not in QUESTIONS_DATA:
        abort(404)

    exams_data = QUESTIONS_DATA[
        category
    ]

    return render_template(
        "exams.html",
        category=category,
        category_label=CATEGORY_LABELS.get(
            category,
            category.title()
        ),
        exams=exams_data
    )


# --------------------------------------------------
# EXAM → SUBJECTS
# --------------------------------------------------

@app.route(
    "/category/<category>/exam/<exam>"
)
@login_required
def subjects(category, exam):

    if category not in QUESTIONS_DATA:
        abort(404)

    if exam not in QUESTIONS_DATA[
        category
    ]:
        abort(404)

    subjects_data = QUESTIONS_DATA[
        category
    ][
        exam
    ]

    return render_template(
        "subjects.html",
        category=category,
        category_label=CATEGORY_LABELS.get(
            category,
            category.title()
        ),
        exam=exam,
        subjects=subjects_data
    )


# --------------------------------------------------
# SUBJECT → START TEST
# --------------------------------------------------

@app.route(
    "/category/<category>/exam/<exam>/subject/<subject>"
)
@login_required
def start_test(
    category,
    exam,
    subject
):

    try:

        questions = QUESTIONS_DATA[
            category
        ][
            exam
        ][
            subject
        ]

    except KeyError:

        abort(404)

    if not questions:

        return render_template(
            "subjects.html",
            category=category,
            category_label=CATEGORY_LABELS.get(
                category,
                category.title()
            ),
            exam=exam,
            subjects=QUESTIONS_DATA[
                category
            ],
            error=(
                "Is subject mein "
                "questions abhi available nahi hain."
            )
        )

    session["category"] = category
    session["exam"] = exam
    session["subject"] = subject

    session["quiz"] = questions
    session["score"] = 0
    session["q_index"] = 0

    return redirect(
        url_for("question")
    )


# --------------------------------------------------
# QUESTION
# --------------------------------------------------

@app.route(
    "/question",
    methods=["GET", "POST"]
)
@login_required
def question():

    quiz_list = session.get("quiz")

    if not quiz_list:
        return redirect(
            url_for("index")
        )

    q_index = session.get(
        "q_index",
        0
    )

    # ----------------------------------------------
    # ANSWER SUBMIT
    # ----------------------------------------------

    if request.method == "POST":

        selected = request.form.get(
            "option"
        )

        current_question = quiz_list[
            q_index
        ]

        correct_answer = current_question.get(
            "answer"
        )

        is_correct = (
            selected == correct_answer
        )

        if is_correct:

            session["score"] = (
                session.get(
                    "score",
                    0
                ) + 1
            )

        session["last_feedback"] = {

            "is_correct": is_correct,

            "correct_answer":
                correct_answer,

            "selected":
                selected
        }

        q_index += 1

        session["q_index"] = q_index

        # ------------------------------------------
        # CHECKPOINT
        # ------------------------------------------

        if (
            q_index % CHECKPOINT_EVERY == 0
            and q_index < len(quiz_list)
        ):

            return render_template(
                "checkpoint.html",

                score=session.get(
                    "score",
                    0
                ),

                q_index=q_index,

                total=len(
                    quiz_list
                ),

                feedback=session[
                    "last_feedback"
                ]
            )

        # ------------------------------------------
        # FEEDBACK
        # ------------------------------------------

        return render_template(
            "answer_feedback.html",

            feedback=session[
                "last_feedback"
            ],

            q_index=q_index,

            total=len(
                quiz_list
            )
        )

    # ----------------------------------------------
    # RESULT
    # ----------------------------------------------

    if q_index >= len(quiz_list):

        final_score = session.get(
            "score",
            0
        )

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT *
            FROM users
            WHERE id = %s
            """,
            (session["user_id"],)
        )

        user = cur.fetchone()

        if (
            user
            and final_score
            > user["best_score"]
        ):

            cur.execute(
                """
                UPDATE users
                SET best_score = %s
                WHERE id = %s
                """,
                (
                    final_score,
                    session["user_id"]
                )
            )

            conn.commit()

        cur.close()
        conn.close()

        return render_template(
            "result.html",
            score=final_score,
            total=len(quiz_list)
        )

    # ----------------------------------------------
    # CURRENT QUESTION
    # ----------------------------------------------

    current_q = quiz_list[
        q_index
    ]

    return render_template(
        "question.html",

        question=current_q["q"],

        options=current_q.get(
            "options",
            []
        ),

        q_number=q_index + 1,

        total=len(
            quiz_list
        ),

        time_limit=TIME_PER_QUESTION,

        category_label=CATEGORY_LABELS.get(
            session.get("category"),
            ""
        ),

        exam=session.get(
            "exam",
            ""
        ),

        subject=session.get(
            "subject",
            ""
        )
    )


# --------------------------------------------------
# NOTES
# --------------------------------------------------

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
            cur = conn.cursor()

            cur.execute(
                """
                INSERT INTO notes
                (
                    user_id,
                    username,
                    text
                )
                VALUES (%s, %s, %s)
                """,
                (
                    session["user_id"],
                    session["username"],
                    text
                )
            )

            conn.commit()

            cur.close()
            conn.close()

            return redirect(
                url_for("notes")
            )

    conn = get_db()
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

    cur.close()
    conn.close()

    return render_template(
        "notes.html",
        notes=all_notes,
        error=error
    )


# --------------------------------------------------
# LEADERBOARD
# --------------------------------------------------

@app.route("/leaderboard")
@login_required
def leaderboard():

    conn = get_db()
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

    cur.close()
    conn.close()

    return render_template(
        "leaderboard.html",
        top_users=top_users
    )


# --------------------------------------------------
# DATABASE INITIALIZATION
# --------------------------------------------------

try:
    init_db()
except Exception as e:
    app.logger.warning(
        f"Database initialization skipped: {e}"
    )


# --------------------------------------------------
# RUN
# --------------------------------------------------

if __name__ == "__main__":

    app.run(
        debug=False,
        host="0.0.0.0",
        port=5000
    )
