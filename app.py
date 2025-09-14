import os
import sqlite3
from datetime import datetime
from functools import wraps
from flask import (
    Flask, g, render_template, request, redirect, url_for,
    jsonify, send_from_directory, flash, abort, session
)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(__file__)
DATABASE = os.path.join(BASE_DIR, "todo.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "pdf", "mp3", "wav", "webm", "ogg"}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.secret_key = os.environ.get("FLASK_SECRET", "dev-secret")


# ----------------------------
# DB helpers
# ----------------------------
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


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()


# ----------------------------
# init DB
# ----------------------------
def init_db():
    create_tasks = """
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT,
        due_date TEXT,
        attachment TEXT,
        is_completed INTEGER DEFAULT 0,
        created_at TEXT NOT NULL
    );
    """
    create_users = """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT
    );
    """
    # ensure we run inside app context
    with app.app_context():
        execute_db(create_tasks)
        execute_db(create_users)


# ----------------------------
# Utilities
# ----------------------------
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapped


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    u = query_db("SELECT id, username FROM users WHERE id = ?", (uid,), one=True)
    return dict(u) if u else None


# ----------------------------
# Routes - auth
# ----------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        if not username or not password:
            flash("Username and password required.", "error")
            return redirect(url_for("register"))
        # check existing
        existing = query_db("SELECT id FROM users WHERE username = ?", (username,), one=True)
        if existing:
            flash("Username already taken.", "error")
            return redirect(url_for("register"))
        hashed = generate_password_hash(password)
        execute_db("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed))
        flash("Account created. Please sign in.", "success")
        return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    next_url = request.args.get("next") or url_for("index")
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        user = query_db("SELECT * FROM users WHERE username = ?", (username,), one=True)
        if not user or not check_password_hash(user["password"], password):
            flash("Invalid credentials.", "error")
            return redirect(url_for("login"))
        session["user_id"] = user["id"]
        flash("Signed in.", "success")
        return redirect(request.form.get("next") or url_for("index"))
    return render_template("login.html", next=next_url)


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    flash("Signed out.", "success")
    return redirect(url_for("login"))


# ----------------------------
# App Routes
# ----------------------------
@app.route("/", methods=["GET", "POST"])
@login_required
def index():
    user = current_user()

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        description = (request.form.get("description") or "").strip()
        due_date = (request.form.get("due_date") or "").strip() or None
        attachment = None

        # recorder hidden field
        rec_path = (request.form.get("attachment_path") or "").strip()
        if rec_path:
            attachment = secure_filename(rec_path)

        # file upload input
        uploaded = request.files.get("file")
        if uploaded and uploaded.filename:
            if allowed_file(uploaded.filename):
                filename = secure_filename(uploaded.filename)
                base, ext = os.path.splitext(filename)
                filename = f"{base}_{int(datetime.utcnow().timestamp())}{ext}"
                uploaded.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
                attachment = filename
            else:
                flash("File type not allowed.", "error")
                return redirect(url_for("index"))

        if not title:
            flash("Task title cannot be empty.", "error")
            return redirect(url_for("index"))

        created_at = datetime.utcnow().isoformat()
        execute_db(
            "INSERT INTO tasks (title, description, due_date, attachment, created_at) VALUES (?, ?, ?, ?, ?)",
            (title, description, due_date, attachment, created_at)
        )
        flash("Task added.", "success")
        return redirect(url_for("index"))

    # GET: load tasks and progress
    rows = query_db("SELECT * FROM tasks ORDER BY created_at DESC")
    tasks = [dict(r) for r in rows]

    total = len(tasks)
    completed = sum(1 for t in tasks if t.get("is_completed"))
    progress = int((completed / total * 100) if total else 0)

    return render_template("index.html", tasks=tasks, user=user, progress=progress)


@app.route("/task/<int:task_id>")
@login_required
def view_task(task_id):
    user = current_user()
    t = query_db("SELECT * FROM tasks WHERE id = ?", (task_id,), one=True)
    if not t:
        abort(404)
    return render_template("view.html", task=dict(t), user=user)


@app.route("/toggle/<int:task_id>", methods=["POST"])
@login_required
def toggle_complete(task_id):
    t = query_db("SELECT is_completed FROM tasks WHERE id = ?", (task_id,), one=True)
    if not t:
        flash("Task not found.", "error")
        return redirect(url_for("index"))
    newv = 0 if t["is_completed"] else 1
    execute_db("UPDATE tasks SET is_completed = ? WHERE id = ?", (newv, task_id))
    return redirect(url_for("index"))


@app.route("/record", methods=["POST"])
@login_required
def record_upload():
    if "recorded_blob" not in request.files:
        return jsonify(ok=False, error="No file part 'recorded_blob'"), 400
    f = request.files["recorded_blob"]
    if f.filename == "":
        return jsonify(ok=False, error="Empty filename"), 400

    if not allowed_file(f.filename):
        ext = f.filename.rsplit(".", 1)[-1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            return jsonify(ok=False, error="File type not allowed"), 400

    filename = secure_filename(f.filename)
    base, ext = os.path.splitext(filename)
    filename = f"{base}_{int(datetime.utcnow().timestamp())}{ext}"
    save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    try:
        f.save(save_path)
    except Exception as e:
        app.logger.exception("Failed to save recorded blob")
        return jsonify(ok=False, error=str(e)), 500

    return jsonify(ok=True, filename=filename)


@app.route("/uploads/<path:filename>")
@login_required
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename, as_attachment=False)


# ----------------------------
if __name__ == "__main__":
    init_db()
    app.run(debug=True)
