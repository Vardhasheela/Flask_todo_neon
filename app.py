import os
import sqlite3
from datetime import datetime
from functools import wraps
from flask import (
    Flask, g, render_template, request, redirect, url_for,
    jsonify, send_from_directory, flash, session
)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

# --- config ---
BASE_DIR = os.path.dirname(__file__)
DATABASE = os.path.join(BASE_DIR, "todo.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "pdf", "mp3", "wav", "webm", "ogg"}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.secret_key = "dev-secret-change-this"  # change for production

# ----------------------------
# Database helpers
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
# DB init
# ----------------------------
def init_db():
    # create tasks and users tables if missing
    create_tasks = """
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT,
        due_date TEXT,
        attachment TEXT,
        is_completed INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        user_id INTEGER
    );
    """
    create_users = """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL
    );
    """
    execute_db(create_tasks)
    execute_db(create_users)

# ----------------------------
# Auth helpers
# ----------------------------
def login_user(user_id, username):
    session["user_id"] = user_id
    session["username"] = username

def logout_user():
    session.pop("user_id", None)
    session.pop("username", None)

def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    row = query_db("SELECT id, username FROM users WHERE id = ?", (uid,), one=True)
    return row

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please sign in to perform that action.", "error")
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return decorated

# ----------------------------
# Utilities
# ----------------------------
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

# ----------------------------
# Routes: auth
# ----------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""
        if not username or not password:
            flash("Missing username or password.", "error")
            return redirect(url_for("register"))
        if password != confirm:
            flash("Passwords do not match.", "error")
            return redirect(url_for("register"))
        existing = query_db("SELECT id FROM users WHERE username = ?", (username,), one=True)
        if existing:
            flash("Username already taken.", "error")
            return redirect(url_for("register"))
        hashed = generate_password_hash(password)
        execute_db("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed))
        flash("Account created — please sign in.", "success")
        return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        user = query_db("SELECT * FROM users WHERE username = ?", (username,), one=True)
        if not user or not check_password_hash(user["password"], password):
            flash("Invalid username or password.", "error")
            return redirect(url_for("login"))
        login_user(user["id"], user["username"])
        flash("Signed in successfully.", "success")
        nxt = request.args.get("next") or url_for("index")
        return redirect(nxt)
    return render_template("login.html")

@app.route("/logout")
def logout():
    logout_user()
    flash("Signed out.", "success")
    return redirect(url_for("index"))

# ----------------------------
# Routes: tasks & uploads
# ----------------------------
@app.route("/", methods=["GET"])
def index():
    # Show tasks (no login required to view)
    rows = query_db("SELECT t.*, u.username FROM tasks t LEFT JOIN users u ON t.user_id = u.id ORDER BY t.created_at DESC")
    tasks = []
    for r in rows:
        d = dict(r)
        d["is_completed"] = bool(d.get("is_completed"))
        tasks.append(d)
    return render_template("index.html", tasks=tasks, current_user=current_user())

@app.route("/add", methods=["POST"])
@login_required
def add_task():
    title = (request.form.get("title") or "").strip()
    description = (request.form.get("description") or "").strip()
    due_date = request.form.get("due_date") or None
    attachment = None

    # recorder produced filename (hidden)
    rec_path = (request.form.get("attachment_path") or "").strip()
    if rec_path:
        attachment = secure_filename(rec_path)

    # file input
    file = request.files.get("file")
    if file and file.filename:
        if allowed_file(file.filename):
            filename = secure_filename(file.filename)
            base, ext = os.path.splitext(filename)
            filename = f"{base}_{int(datetime.now().timestamp())}{ext}"
            save_to = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(save_to)
            attachment = filename
        else:
            flash("File type not allowed.", "error")
            return redirect(url_for("index"))

    if not title:
        flash("Task title cannot be empty.", "error")
        return redirect(url_for("index"))

    created_at = datetime.now().isoformat()
    execute_db(
        "INSERT INTO tasks (title, description, due_date, attachment, created_at, user_id) VALUES (?, ?, ?, ?, ?, ?)",
        (title, description or None, due_date or None, attachment, created_at, session["user_id"])
    )
    flash("Task added.", "success")
    return redirect(url_for("index"))

@app.route("/record", methods=["POST"])
@login_required
def record_upload():
    # Receives FormData with 'recorded_blob'
    if "recorded_blob" not in request.files:
        return jsonify(ok=False, error="No recorded_blob in request"), 400
    f = request.files["recorded_blob"]
    if f.filename == "":
        return jsonify(ok=False, error="Empty filename"), 400

    ext = f.filename.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify(ok=False, error="file type not allowed"), 400

    filename = secure_filename(f.filename)
    base, ext = os.path.splitext(filename)
    filename = f"{base}_{int(datetime.now().timestamp())}{ext}"
    save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    try:
        f.save(save_path)
    except Exception as e:
        app.logger.exception("Failed to save recorded blob")
        return jsonify(ok=False, error=str(e)), 500

    return jsonify(ok=True, filename=filename)

@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename, as_attachment=False)

@app.route("/view/<int:task_id>")
def view_task(task_id):
    row = query_db("SELECT t.*, u.username FROM tasks t LEFT JOIN users u ON t.user_id = u.id WHERE t.id = ?", (task_id,), one=True)
    if not row:
        flash("Task not found.", "error")
        return redirect(url_for("index"))
    task = dict(row)
    attachment = task.get("attachment")
    attachment_url = url_for("uploaded_file", filename=attachment) if attachment else None
    # determine attachment type from filename ext
    ext = (attachment.rsplit(".",1)[-1].lower()) if attachment else ""
    is_audio = ext in ("mp3","wav","webm","ogg")
    is_image = ext in ("png","jpg","jpeg","gif")
    is_pdf = ext == "pdf"
    return render_template("edit.html", task=task, attachment_url=attachment_url,
                           is_audio=is_audio, is_image=is_image, is_pdf=is_pdf, current_user=current_user())

@app.route("/toggle/<int:task_id>", methods=["POST"])
@login_required
def toggle_complete(task_id):
    t = query_db("SELECT is_completed FROM tasks WHERE id = ? AND (user_id = ? OR user_id IS NULL)", (task_id, session["user_id"]), one=True)
    if not t:
        flash("Task not found or you don't have permission.", "error")
        return redirect(url_for("index"))
    newv = 0 if t["is_completed"] else 1
    execute_db("UPDATE tasks SET is_completed = ? WHERE id = ?", (newv, task_id))
    return redirect(url_for("index"))

# ----------------------------
# Start
# ----------------------------
if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(debug=True)
