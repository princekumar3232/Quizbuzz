import os
import json
import sqlite3
from pathlib import Path
from functools import wraps

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    abort,
)

from werkzeug.security import (
    generate_password_hash,
    check_password_hash,
)


# ============================================================
# APP
# ============================================================

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "quizapp-secret-key-change-this"
)


# ============================================================
# PATHS / SETTINGS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

QUESTIONS_FILE = BASE_DIR / "static" / "questions.json"
DATABASE_FILE = BASE_DIR / "quizapp.db"

TIME_PER_QUESTION = 30


CATEGORY_LABELS = {
    "teaching": "🎓 Teaching",
    "sports": "🏆 Sports",
    "music": "🎵 Music",
    "physical": "🏃 Physical Education",
}


# ============================================================
# DATABASE
# ============================================================

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

        # ----------------------------------------------------
        # USERS
        # ----------------------------------------------------

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT,
                mobile TEXT,
                password_hash TEXT NOT NULL,
                best_score INTEGER NOT NULL DEFAULT 0
            )
            """
        )

        # ----------------------------------------------------
        # CHECK OLD COLUMNS
        # ----------------------------------------------------

        existing_columns = {
            row["name"]
            for row in cur.execute(
                "PRAGMA table_info(users)"
            ).fetchall()
        }

        if "email" not in existing_columns:

            cur.execute(
                "ALTER TABLE users ADD COLUMN email TEXT"
            )

        if "mobile" not in existing_columns:

            cur.execute(
                "ALTER TABLE users ADD COLUMN mobile TEXT"
            )

        # ----------------------------------------------------
        # UNIQUE EMAIL
        # ----------------------------------------------------

        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
            idx_users_email
            ON users(email)
            WHERE email IS NOT NULL
            AND email != ''
            """
        )

        # ----------------------------------------------------
        # UNIQUE MOBILE
        # ----------------------------------------------------

        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
            idx_users_mobile
            ON users(mobile)
            WHERE mobile IS NOT NULL
            AND mobile != ''
            """
        )

        # ----------------------------------------------------
        # NOTES
        # ----------------------------------------------------

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                text TEXT NOT NULL,
                created_at TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY(user_id)
                REFERENCES users(id)
                ON DELETE CASCADE
            )
            """
        )

        conn.commit()

    finally:

        conn.close()


# ============================================================
# LOAD QUESTIONS
# ============================================================

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

        if not isinstance(data, dict):

            print(
                "Question file error: "
                "top level must be an object."
            )

            return {}

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


# ============================================================
# GET EXAMS
# ============================================================

def get_exams_for_category(category):

    """
    questions.json structure:

    category
        |
        +-- label
        +-- question_bank
        +-- exams
              |
              +-- exam
                    |
                    +-- subject
                          |
                          +-- questions

    The old code incorrectly treated the entire
    category object as the exams dictionary.

    This function fixes that problem.
    """

    category_data = QUESTIONS_DATA.get(
        category
    )

    if not isinstance(
        category_data,
        dict
    ):

        return {}

    exams = category_data.get(
        "exams"
    )

    if isinstance(
        exams,
        dict
    ):

        return exams

    # --------------------------------------------------------
    # BACKWARD COMPATIBILITY
    # --------------------------------------------------------

    return {
        key: value
        for key, value in category_data.items()
        if key not in (
            "label",
            "question_bank"
        )
    }


# ============================================================
# GET SUBJECT QUESTIONS
# ============================================================

def get_subject_questions(
    category,
    exam,
    subject
):

    exams = get_exams_for_category(
        category
    )

    exam_data = exams.get(
        exam
    )

    if not isinstance(
        exam_data,
        dict
    ):

        return None

    questions = exam_data.get(
        subject
    )

    if not isinstance(
        questions,
        list
    ):

        return None

    return questions


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

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


# ============================================================
# LOGIN REQUIRED
# ============================================================

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


# ============================================================
# REGISTER
# ============================================================

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

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        mobile = request.form.get(
            "mobile",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        # ----------------------------------------------------
        # REQUIRED FIELDS
        # ----------------------------------------------------

        if (
            not username
            or not email
            or not mobile
            or not password
        ):

            return render_template(
                "register.html",
                error=(
                    "Sabhi fields bharna "
                    "zaroori hai."
                )
            )

        # ----------------------------------------------------
        # EMAIL
        # ----------------------------------------------------

        if (
            "@" not in email
            or "." not in email
        ):

            return render_template(
                "register.html",
                error=(
                    "Please valid email "
                    "address enter karein."
                )
            )

        # ----------------------------------------------------
        # MOBILE
        # ----------------------------------------------------

        if (
            not mobile.isdigit()
            or len(mobile) != 10
        ):

            return render_template(
                "register.html",
                error=(
                    "Mobile number 10 digits "
                    "ka hona chahiye."
                )
            )

        conn = get_db()

        try:

            cur = conn.cursor()

            # ------------------------------------------------
            # USERNAME
            # ------------------------------------------------

            cur.execute(
                """
                SELECT id
                FROM users
                WHERE LOWER(username)
                = LOWER(?)
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

            # ------------------------------------------------
            # EMAIL
            # ------------------------------------------------

            cur.execute(
                """
                SELECT id
                FROM users
                WHERE LOWER(email)
                = LOWER(?)
                """,
                (email,)
            )

            if cur.fetchone():

                return render_template(
                    "register.html",
                    error=(
                        "Ye email pehle se "
                        "registered hai."
                    )
                )

            # ------------------------------------------------
            # MOBILE
            # ------------------------------------------------

            cur.execute(
                """
                SELECT id
                FROM users
                WHERE mobile = ?
                """,
                (mobile,)
            )

            if cur.fetchone():

                return render_template(
                    "register.html",
                    error=(
                        "Ye mobile number pehle "
                        "se registered hai."
                    )
                )

            # ------------------------------------------------
            # CREATE USER
            # ------------------------------------------------

            cur.execute(
                """
                INSERT INTO users(
                    username,
                    email,
                    mobile,
                    password_hash
                )
                VALUES(?, ?, ?, ?)
                """,
                (
                    username,
                    email,
                    mobile,
                    generate_password_hash(
                        password
                    )
                )
            )

            conn.commit()

        except sqlite3.IntegrityError:

            return render_template(
                "register.html",
                error=(
                    "Email ya mobile number "
                    "pehle se registered hai."
                )
            )

        finally:

            conn.close()

        return redirect(
            url_for("login")
        )

    return render_template(
        "register.html"
    )


# ============================================================
# LOGIN
# ============================================================

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
                WHERE LOWER(username)
                = LOWER(?)
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


# ============================================================
# LOGOUT
# ============================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("login")
    )


# ============================================================
# HOME
# ============================================================

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


# ============================================================
# EXAMS
# ============================================================

@app.route(
    "/category/<category>"
)
@login_required
def exams(category):

    if category not in QUESTIONS_DATA:

        abort(404)

    exams_data = get_exams_for_category(
        category
    )

    if not exams_data:

        abort(404)

    return render_template(
        "exams.html",
        category=category,
        category_label=CATEGORY_LABELS.get(
            category,
            category.title()
        ),
        exams=exams_data
    )


# ============================================================
# SUBJECTS
# ============================================================

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

    exams_data = get_exams_for_category(
        category
    )

    if exam not in exams_data:

        abort(404)

    subjects_data = exams_data[
        exam
    ]

    if not isinstance(
        subjects_data,
        dict
    ):

        abort(404)

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


# ============================================================
# START TEST
# ============================================================

@app.route(
    "/category/<category>/exam/<path:exam>"
    "/subject/<path:subject>"
)
@login_required
def start_test(
    category,
    exam,
    subject
):

    if category not in QUESTIONS_DATA:

        abort(404)

    exams_data = get_exams_for_category(
        category
    )

    exam_data = exams_data.get(
        exam
    )

    if not isinstance(
        exam_data,
        dict
    ):

        abort(404)

    questions = get_subject_questions(
        category,
        exam,
        subject
    )

    if questions is None:

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
            subjects=exam_data,
            error=(
                "Is subject mein abhi "
                "questions available "
                "nahi hain."
            )
        )

    # --------------------------------------------------------
    # IMPORTANT
    #
    # Complete question bank ko Flask's
    # cookie session mein store nahi karna.
    #
    # Large questions.json ki wajah se
    # browser cookie limit exceed ho sakti hai.
    #
    # Sirf category/exam/subject session mein
    # save kiya ja raha hai.
    # --------------------------------------------------------

    session["category"] = category
    session["exam"] = exam
    session["subject"] = subject

    session["score"] = 0
    session["q_index"] = 0

    return redirect(
        url_for("question")
    )


# ============================================================
# QUESTION
# ============================================================

@app.route(
    "/question",
    methods=["GET", "POST"]
)
@login_required
def question():

    category = session.get(
        "category"
    )

    exam = session.get(
        "exam"
    )

    subject = session.get(
        "subject"
    )

    if (
        not category
        or not exam
        or not subject
    ):

        return redirect(
            url_for("index")
        )

    # --------------------------------------------------------
    # LOAD QUESTIONS AGAIN FROM JSON
    # --------------------------------------------------------

    quiz = get_subject_questions(
        category,
        exam,
        subject
    )

    if not quiz:

        session.pop(
            "category",
            None
        )

        session.pop(
            "exam",
            None
        )

        session.pop(
            "subject",
            None
        )

        session.pop(
            "q_index",
            None
        )

        session.pop(
            "score",
            None
        )

        return redirect(
            url_for("index")
        )

    try:

        q_index = int(
            session.get(
                "q_index",
                0
            )
        )

    except (
        TypeError,
        ValueError
    ):

        q_index = 0

    q_index = max(
        0,
        q_index
    )

    # --------------------------------------------------------
    # QUIZ FINISHED
    # --------------------------------------------------------

    if q_index >= len(quiz):

        try:

            final_score = int(
                session.get(
                    "score",
                    0
                )
            )

        except (
            TypeError,
            ValueError
        ):

            final_score = 0

        save_best_score(
            final_score
        )

        # Clear quiz session.

        session.pop(
            "category",
            None
        )

        session.pop(
            "exam",
            None
        )

        session.pop(
            "subject",
            None
        )

        session.pop(
            "q_index",
            None
        )

        session.pop(
            "score",
            None
        )

        session.pop(
            "last_feedback",
            None
        )

        return render_template(
            "result.html",
            score=final_score,
            total=len(quiz)
        )

    # --------------------------------------------------------
    # CURRENT QUESTION
    # --------------------------------------------------------

    current_question = quiz[
        q_index
    ]

    if not isinstance(
        current_question,
        dict
    ):

        abort(500)

    # --------------------------------------------------------
    # ANSWER SUBMITTED
    # --------------------------------------------------------

    if request.method == "POST":

        selected = request.form.get(
            "option"
        )

        correct_answer = (
            current_question.get(
                "answer"
            )
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

            "selected": selected,

            "correct_answer":
                correct_answer
        }

        session["q_index"] = (
            q_index + 1
        )

        return render_template(
            "answer_feedback.html",
            feedback=session[
                "last_feedback"
            ],
            q_index=q_index + 1,
            total=len(quiz)
        )

    # --------------------------------------------------------
    # SHOW QUESTION
    # --------------------------------------------------------

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

        total=len(quiz),

        time_limit=TIME_PER_QUESTION,

        category_label=CATEGORY_LABELS.get(
            category,
            ""
        ),

        exam=exam,

        subject=subject
    )


# ============================================================
# BEST SCORE
# ============================================================

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
            WHERE id = ?
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
                SET best_score = ?
                WHERE id = ?
                """,
                (
                    score,
                    session["user_id"]
                )
            )

            conn.commit()

    finally:

        conn.close()


# ============================================================
# NOTES
# ============================================================

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
                "Note likhna "
                "zaroori hai."
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


# ============================================================
# LEADERBOARD
# ============================================================

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
            SELECT
                username,
                best_score
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


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/health")
def health():

    return {
        "status": "ok"
    }, 200


# ============================================================
# ERROR HANDLERS
# ============================================================

@app.errorhandler(404)
def page_not_found(error):

    try:

        return (
            render_template(
                "error.html",
                error_code=404,
                error_message=(
                    "Page nahi mili."
                )
            ),
            404
        )

    except Exception:

        return (
            "Page Not Found",
            404
        )


@app.errorhandler(500)
def internal_server_error(error):

    try:

        return (
            render_template(
                "error.html",
                error_code=500,
                error_message=(
                    "Server par internal "
                    "error aa gaya. "
                    "Render logs check karein."
                )
            ),
            500
        )

    except Exception:

        return (
            "Internal Server Error",
            500
        )


# ============================================================
# RUN
# ============================================================

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
