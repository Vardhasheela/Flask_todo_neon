from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "todo.db"

app = Flask(__name__)
app.secret_key = "replace_with_a_random_secret_in_prod"

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        notes TEXT,
        done INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    conn.commit()
    conn.close()

@app.route("/")
def index():
    conn = get_db_connection()
    tasks = conn.execute("SELECT * FROM tasks ORDER BY done ASC, created_at DESC").fetchall()
    conn.close()
    return render_template("index.html", tasks=tasks)

@app.route("/add", methods=["POST"])
def add():
    title = request.form.get("title", "").strip()
    notes = request.form.get("notes", "").strip()
    if not title:
        flash("Task title cannot be empty.", "error")
        return redirect(url_for("index"))
    conn = get_db_connection()
    conn.execute("INSERT INTO tasks (title, notes) VALUES (?, ?)", (title, notes))
    conn.commit()
    conn.close()
    flash("Task added.", "success")
    return redirect(url_for("index"))

@app.route("/toggle/<int:task_id>")
def toggle(task_id):
    conn = get_db_connection()
    row = conn.execute("SELECT done FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row:
        new_state = 0 if row["done"] else 1
        conn.execute("UPDATE tasks SET done = ? WHERE id = ?", (new_state, task_id))
        conn.commit()
    conn.close()
    return redirect(url_for("index"))

@app.route("/edit/<int:task_id>", methods=["GET", "POST"])
def edit(task_id):
    conn = get_db_connection()
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        notes = request.form.get("notes", "").strip()
        if not title:
            flash("Title cannot be empty.", "error")
            return redirect(url_for("edit", task_id=task_id))
        conn.execute("UPDATE tasks SET title = ?, notes = ? WHERE id = ?", (title, notes, task_id))
        conn.commit()
        conn.close()
        flash("Task updated.", "success")
        return redirect(url_for("index"))
    else:
        task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        conn.close()
        if task is None:
            flash("Task not found.", "error")
            return redirect(url_for("index"))
        return render_template("edit.html", task=task)

@app.route("/delete/<int:task_id>", methods=["POST"])
def delete(task_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()
    flash("Task deleted.", "success")
    return redirect(url_for("index"))

if __name__ == "__main__":
    init_db()
    import os
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "True").lower() in ("1","true","yes")
    app.run(host=host, port=port, debug=debug)
