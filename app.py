# app.py
import os
import sqlite3
from datetime import datetime, timezone
from flask import (
    Flask, g, render_template, request, redirect, url_for,
    jsonify, send_from_directory, flash, abort
)
from werkzeug.utils import secure_filename

# ---------- Config ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "todo.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "pdf", "mp3", "wav", "webm", "ogg"}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")

# ---------- DB helpers ----------
def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv

def execute_db(query, args=()):
    db = get_db()
    cur = db.execute(query, args)
    db.commit()
    cur.close()

def init_db():
    """Create schema if missing. Called inside app.app_context()."""
    # tasks table
    create_tasks = """
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT,
        due_date TEXT,
        attachment TEXT,
        user_id INTEGER,
        is_completed INTEGER DEFAULT 0,
        created_at TEXT NOT NULL
    );
    """
    # users table (simple - useful if you add auth later)
    create_users = """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT
    );
    """
    execute_db(create_tasks)
    execute_db(create_users)

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()

# ---------- Utilities ----------
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

# ---------- Routes ----------
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        description = (request.form.get("description") or "").strip()
        due_date = (request.form.get("due_date") or "").strip() or None

        # attachment from recorder (hidden) or file input named 'file'
        attachment = None
        rec_path = (request.form.get("attachment_path") or "").strip()
        if rec_path:
            attachment = secure_filename(rec_path)

        file = request.files.get("file")
        if file and file.filename:
            if allowed_file(file.filename):
                filename = secure_filename(file.filename)
                base, ext = os.path.splitext(filename)
                filename = f"{base}_{int(datetime.now(timezone.utc).timestamp())}{ext}"
                save_to = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                file.save(save_to)
                attachment = filename
            else:
                flash("File type not allowed.", "error")

        if not title:
            flash("Task title cannot be empty.", "error")
            return redirect(url_for("index"))

        created_at = datetime.now(timezone.utc).isoformat()
        execute_db(
            "INSERT INTO tasks (title, description, due_date, attachment, created_at) VALUES (?, ?, ?, ?, ?)",
            (title, description, due_date, attachment, created_at),
        )
        flash("Task added.", "success")
        return redirect(url_for("index"))

    # SELECT with LEFT JOIN to show username if user exists; users table now exists (created in init_db)
    rows = query_db(
        "SELECT t.*, u.username FROM tasks t LEFT JOIN users u ON t.user_id = u.id ORDER BY t.created_at DESC"
    )
    tasks = [dict(r) for r in rows]
    return render_template("index.html", tasks=tasks)

@app.route("/task/<int:task_id>")
def view_task(task_id):
    t = query_db("SELECT * FROM tasks WHERE id = ?", (task_id,), one=True)
    if not t:
        abort(404)
    task = dict(t)
    return render_template("view_task.html", task=task)

@app.route("/record", methods=["POST"])
def record_upload():
    # receives a file field named 'recorded_blob' (from client-side recorder)
    if "recorded_blob" not in request.files:
        return jsonify(ok=False, error="No file uploaded"), 400
    f = request.files["recorded_blob"]
    if f.filename == "":
        return jsonify(ok=False, error="Empty filename"), 400
    # allow audio container types allowed in ALLOWED_EXTENSIONS
    ext = f.filename.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify(ok=False, error="File type not allowed"), 400

    filename = secure_filename(f.filename)
    base, ext = os.path.splitext(filename)
    filename = f"{base}_{int(datetime.now(timezone.utc).timestamp())}{ext}"
    save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    try:
        f.save(save_path)
    except Exception as e:
        app.logger.exception("Failed to save recorded blob")
        return jsonify(ok=False, error=str(e)), 500

    # client expects {"ok":true,"filename":"..."}
    return jsonify(ok=True, filename=filename)

@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename, as_attachment=False)

@app.route("/toggle/<int:task_id>", methods=["POST"])
def toggle_complete(task_id):
    t = query_db("SELECT is_completed FROM tasks WHERE id = ?", (task_id,), one=True)
    if not t:
        flash("Task not found.", "error")
        return redirect(url_for("index"))
    newv = 0 if t["is_completed"] else 1
    execute_db("UPDATE tasks SET is_completed = ? WHERE id = ?", (newv, task_id))
    return redirect(url_for("index"))

# ---------- Ensure DB initialized at import time (so gunicorn will create tables) ----------
with app.app_context():
    init_db()

# ---------- run (development) ----------
if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)
