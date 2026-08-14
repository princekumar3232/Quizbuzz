import os
import json
from pathlib import Path
from functools import wraps

import psycopg
from psycopg.rows import dict_row
from flask import Flask, render_template, request, redirect, url_for, session, abort
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "change-this-secret-key"
)

DATABASE_URL = os.environ.get("DATABASE_URL")

BASE_DIR = Path(__file__).resolve().parent
QUESTIONS_FILE = BASE_DIR / "static" / "questions.json"

TIME_PER_QUESTION = 30

CATEGORY_LABELS = {
    "teaching": "🎓 Teaching",
    "sports": "🏆 Sports",
    "music": "🎵 Music",
    "physical": "🏃 Physical Education",
}


def load_questions():
    if not QUESTIONS_FILE.exists():
        return {}

    try:
        with open(QUESTIONS_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception as error:
        print("Question file error:", error)
        return {}


QUESTIONS_DATA = load_questions()


def get_db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured.")

    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row
    )


def init_db():
    conn = get_db()

    try:
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                best_score INTEGER NOT NULL DEFAULT 0
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                username TEXT NOT NULL,
                text TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()

    finally:
        conn.close()


@app.before_request
def database_setup():
    if DATABASE_URL and not app.config.get("DATABASE_READY"):
        try:
            init_db()
            app.config["DATABASE_READY"] = True
        except Exception as error:
            print("Database initialization error:", error)


def login_required(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return function(*args, **kwargs)

    return wrapper


@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            return render_template(
                "register.html",
                error="Sabhi fields bharna zaroori hai."
            )

        conn = get_db()

        try:
            cur = conn.cursor()

            cur.execute(
                "SELECT id FROM users WHERE LOWER(username)=LOWER(%s)",
                (username,)
            )

            if cur.fetchone():
                return render_template(
                    "register.html",
                    error="Ye username pehle se registered hai."
                )

            cur.execute(
                """
                INSERT INTO users(username, password_hash)
                VALUES(%s, %s)
                """,
                (
                    username,
                    generate_password_hash(password)
                )
            )

            conn.commit()

        finally:
            conn.close()

        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        conn = get_db()

        try:
            cur = conn.cursor()

            cur.execute(
                """
                SELECT *
                FROM users
                WHERE LOWER(username)=LOWER(%s)
                """,
                (username,)
            )

            user = cur.fetchone()

        finally:
            conn.close()

        if not user or not check_password_hash(
            user["password_hash"],
            password
        ):
            return render_template(
                "login.html",
                error="Galat username ya password."
            )

        session.clear()
        session["user_id"] = user["id"]
        session["username"] = user["username"]

        return redirect(url_for("index"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    return render_template(
        "index.html",
        username=session.get("username"),
        categories=CATEGORY_LABELS
    )


@app.route("/category/<category>")
@login_required
def exams(category):

    if category not in QUESTIONS_DATA:
        abort(404)

    exams_data = QUESTIONS_DATA[category]

    return render_template(
        "exams.html",
        category=category,
        category_label=CATEGORY_LABELS.get(category, category.title()),
        exams=exams_data
    )


@app.route("/category/<category>/exam/<path:exam>")
@login_required
def subjects(category, exam):

    if category not in QUESTIONS_DATA:
        abort(404)

    if exam not in QUESTIONS_DATA[category]:
        abort(404)

    subjects_data = QUESTIONS_DATA[category][exam]

    return render_template(
        "subjects.html",
        category=category,
        category_label=CATEGORY_LABELS.get(category, category.title()),
        exam=exam,
        subjects=subjects_data
    )


@app.route("/category/<category>/exam/<path:exam>/subject/<path:subject>")
@login_required
def start_test(category, exam, subject):

    try:
        questions = QUESTIONS_DATA[category][exam][subject]
    except KeyError:
        abort(404)

    if not questions:
        return render_template(
            "subjects.html",
            category=category,
            category_label=CATEGORY_LABELS.get(category, category.title()),
            exam=exam,
            subjects=QUESTIONS_DATA[category][exam],
            error="Is subject mein abhi questions available nahi hain."
        )

    session["category"] = category
    session["exam"] = exam
    session["subject"] = subject
    session["quiz"] = questions
    session["score"] = 0
    session["q_index"] = 0

    return redirect(url_for("question"))


@app.route("/question", methods=["GET", "POST"])
@login_required
def question():

    quiz = session.get("quiz")

    if not quiz:
        return redirect(url_for("index"))

    q_index = session.get("q_index", 0)

    if q_index >= len(quiz):
        final_score = session.get("score", 0)
        save_best_score(final_score)

        return render_template(
            "result.html",
            score=final_score,
            total=len(quiz)
        )

    current_question = quiz[q_index]

    if request.method == "POST":

        selected = request.form.get("option")
        correct_answer = current_question.get("answer")

        is_correct = selected == correct_answer

        if is_correct:
            session["score"] = session.get("score", 0) + 1

        session["last_feedback"] = {
            "is_correct": is_correct,
            "selected": selected,
            "correct_answer": correct_answer
        }

        session["q_index"] = q_index + 1

        return render_template(
            "answer_feedback.html",
            feedback=session["last_feedback"],
            q_index=q_index + 1,
            total=len(quiz)
        )

    return render_template(
        "question.html",
        question=current_question.get("q", ""),
        options=current_question.get("options", []),
        q_number=q_index + 1,
        total=len(quiz),
        time_limit=TIME_PER_QUESTION,
        category_label=CATEGORY_LABELS.get(
            session.get("category"),
            ""
        ),
        exam=session.get("exam", ""),
        subject=session.get("subject", "")
    )


def save_best_score(score):

    if "user_id" not in session:
        return

    conn = get_db()

    try:
        cur = conn.cursor()

        cur.execute(
            "SELECT best_score FROM users WHERE id=%s",
            (session["user_id"],)
        )

        user = cur.fetchone()

        if user and score > user["best_score"]:

            cur.execute(
                """
                UPDATE users
                SET best_score=%s
                WHERE id=%s
                """,
                (
                    score,
                    session["user_id"]
                )
            )

            conn.commit()

    finally:
        conn.close()


@app.route("/notes", methods=["GET", "POST"])
@login_required
def notes():

    error = None

    if request.method == "POST":

        text = request.form.get("text", "").strip()

        if not text:
            error = "Note likhna zaroori hai."

        else:

            conn = get_db()

            try:
                cur = conn.cursor()

                cur.execute(
                    """
                    INSERT INTO notes(user_id, username, text)
                    VALUES(%s, %s, %s)
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

            return redirect(url_for("notes"))

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


@app.route("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=False
    )
  
