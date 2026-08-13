import os
import json
from functools import wraps
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, session, abort
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg
from psycopg.rows import dict_row

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-fallback-key-change-me")

DATABASE_URL = os.environ.get("DATABASE_URL")

TIME_PER_QUESTION = 3
CHECKPOINT_EVERY = 10

QUESTIONS_BY_CATEGORY = json.loads(
    (Path(__file__).parent / "static" / "questions.json").read_text(encoding="utf-8")
)

CATEGORY_LABELS = {
    "teaching": "Teaching",
    "sports": "Sports",
    "music": "Music",
    "physical": "Physical",
}


def get_db():
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    return conn


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
            user_id INTEGER NOT NULL REFERENCES users(id),
            username TEXT NOT NULL,
            text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    cur.close()
    conn.close()


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]

        if not username or not password:
            return render_template("register.html", error="Sabhi field zaroori hain.")

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE username = %s", (username,))
        existing = cur.fetchone()
        if existing:
            cur.close()
            conn.close()
            return render_template("register.html", error="Ye username pehle se hai.")

        cur.execute(
            "INSERT INTO users (username, password_hash) VALUES (%s, %s)",
            (username, generate_password_hash(password)),
        )
        conn.commit()
        cur.close()
        conn.close()
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"].strip()

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE LOWER(username) = LOWER(%s)", (username,))
        user = cur.fetchone()
        cur.close()
        conn.close()

        if user is None or not check_password_hash(user["password_hash"], password):
            app.logger.warning(f"LOGIN FAIL: username={username!r} user_found={user is not None}")
            return render_template("login.html", error="Galat username ya password.")

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
    return render_template("index.html", username=session["username"], categories=CATEGORY_LABELS)


@app.route("/quiz/<category>")
@login_required
def quiz(category):
    if category not in QUESTIONS_BY_CATEGORY:
        abort(404)
    session["category"] = category
    session["quiz"] = QUESTIONS_BY_CATEGORY[category]
    session["score"] = 0
    session["q_index"] = 0
    return redirect(url_for("question"))


@app.route("/question", methods=["GET", "POST"])
@login_required
def question():
    quiz_list = session.get("quiz")
    if not quiz_list:
        return redirect(url_for("index"))

    q_index = session.get("q_index", 0)

    if request.method == "POST":
        action = request.form.get("action")

        if action in ("continue", "next"):
            pass
        else:
            selected = request.form.get("option")
            correct_answer = quiz_list[q_index]["answer"]
            is_correct = (selected == correct_answer)
            if is_correct:
                session["score"] = session.get("score", 0) + 1

            session["last_feedback"] = {
                "is_correct": is_correct,
                "correct_answer": correct_answer,
                "selected": selected,
            }
            q_index += 1
            session["q_index"] = q_index

            if q_index % CHECKPOINT_EVERY == 0 and q_index < len(quiz_list):
                return render_template(
                    "checkpoint.html",
                    score=session.get("score", 0),
                    q_index=q_index,
                    total=len(quiz_list),
                    feedback=session["last_feedback"],
                )

            return render_template(
                "answer_feedback.html",
                feedback=session["last_feedback"],
                q_index=q_index,
                total=len(quiz_list),
            )

    if q_index >= len(quiz_list):
        final_score = session.get("score", 0)
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE id = %s", (session["user_id"],))
        user = cur.fetchone()
        if final_score > user["best_score"]:
            cur.execute(
                "UPDATE users SET best_score = %s WHERE id = %s",
                (final_score, session["user_id"]),
            )
            conn.commit()
        cur.close()
        conn.close()
        return render_template("result.html", score=final_score, total=len(quiz_list))

    current_q = quiz_list[q_index]
    category_label = CATEGORY_LABELS.get(session.get("category"), "")
    return render_template(
        "question.html",
        question=current_q["q"],
        options=current_q["options"],
        q_number=q_index + 1,
        total=len(quiz_list),
        time_limit=TIME_PER_QUESTION,
        category_label=category_label,
    )


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
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO notes (user_id, username, text) VALUES (%s, %s, %s)",
                (session["user_id"], session["username"], text),
            )
            conn.commit()
            cur.close()
            conn.close()
            return redirect(url_for("notes"))

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM notes ORDER BY created_at DESC LIMIT 50")
    all_notes = cur.fetchall()
    cur.close()
    conn.close()

    return render_template("notes.html", notes=all_notes, error=error)


@app.route("/leaderboard")
@login_required
def leaderboard():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT username, best_score FROM users ORDER BY best_score DESC LIMIT 20")
    top_users = cur.fetchall()
    cur.close()
    conn.close()
    return render_template("leaderboard.html", top_users=top_users)


init_db()

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5000)
