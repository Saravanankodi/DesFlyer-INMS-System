import calendar
import json
import re
from io import BytesIO
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4
from xml.sax.saxutils import escape

from flask import Flask, flash, redirect, render_template, request, send_file, session, url_for
from werkzeug.utils import secure_filename
import hashlib
import secrets
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

app = Flask(__name__)
app.secret_key = "internship-tracker-development-key-change-me"

BASE_DIR = Path(__file__).resolve().parent
UPLOADS_DIR = BASE_DIR / "uploads"
DOC_UPLOAD_DIR = UPLOADS_DIR / "documents"
PROJECT_UPLOAD_DIR = UPLOADS_DIR / "projects"
UPLOADS_DIR.mkdir(exist_ok=True)
DOC_UPLOAD_DIR.mkdir(exist_ok=True)
PROJECT_UPLOAD_DIR.mkdir(exist_ok=True)
INTERNS_FILE = BASE_DIR / "interns.json"
TASKS_FILE = BASE_DIR / "tasks.json"
MENTORS_FILE = BASE_DIR / "mentors.json"
USERS_FILE = BASE_DIR / "users.json"
NOTIFICATIONS_FILE = BASE_DIR / "notifications.json"
STATUSES = ("Start", "In Progress", "Completed", "Not Completed")
PRIORITIES = ("High", "Medium", "Low")
DEFAULT_DEPARTMENTS = (
    "Digital Marketing",
    "Human Resources",
    "Python Development",
    "Web Development",
    "Data Science",
    "UI/UX Design",
    "Testing / QA",
    "Fullstack Development",
    "Frontend Development",
    "Backend Development",
    "Research and Development",
    "Video Editing",
    "Graphical Designing",
    "Android Development",
    "HR Department",
    "Sales Department",
    "Finance Department",
)

# Older records used a few misspelled/duplicate department names. Keep them
# compatible while exposing one canonical name in every department selector.
DEPARTMENT_ALIASES = {
    "Python Developement": "Python Development",
    "UI and UX Design": "UI/UX Design",
    "Fullstack Developement": "Fullstack Development",
    "Frontend Developement": "Frontend Development",
    "Backend Developement": "Backend Development",
    "Android Developement": "Android Development",
}
DEPARTMENT_CODES = {
    "Digital Marketing": "DM",
    "Human Resources": "HR",
    "Python Development": "PY",
    "Web Development": "WD",
    "Data Science": "DS",
    "UI/UX Design": "UI",
    "Testing / QA": "QA",
    "Fullstack Development": "FSD",
    "Frontend Development": "FD",
    "Backend Development": "BD",
    "Research and Development": "R&D",
    "Video Editing": "VE",
    "Graphical Designing": "GE",
    "Android Development": "AD",
    "HR Department": "HR",
    "Sales Department": "SD",
    "Finance Department": "FND",
}
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # Allow large internship project ZIP uploads (up to 500 MB)


@app.errorhandler(413)
def request_entity_too_large(error):
    flash("The uploaded ZIP is too large. The maximum allowed size is 500 MB.", "danger")
    return redirect(url_for("intern_dashboard"))


def calculate_end_date(joining_date, duration_months):
    joining = date.fromisoformat(joining_date)
    month_index = joining.month - 1 + int(duration_months)
    year = joining.year + month_index // 12
    month = month_index % 12 + 1
    day = min(joining.day, calendar.monthrange(year, month)[1])
    return date(year, month, day).isoformat()


def calculate_intern_status(end_date):
    return "Active Intern" if date.today().isoformat() <= end_date else "Past Employee"


def load_json(path):
    if not path.exists():
        path.write_text("[]", encoding="utf-8")
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def next_profile_id(prefix, records):
    sequence_numbers = []
    for record in records:
        value = str(record.get("id", ""))
        suffix = value[len(prefix):] if value.startswith(prefix) else ""
        if suffix.isdigit():
            sequence_numbers.append(int(suffix))
    return f"{prefix}{max(sequence_numbers, default=0) + 1:03d}"


def task_id_for_department(department, tasks):
    code = DEPARTMENT_CODES.get(department, "")
    if not code:
        return ""
    base_id = f"DF{code}"
    pattern = re.compile(rf"^{re.escape(base_id)}(\d+)$", re.IGNORECASE)
    sequence_numbers = [int(match.group(1)) for task in tasks
                        if (match := pattern.match(str(task.get("id", ""))))]
    return f"{base_id}{max(sequence_numbers, default=0) + 1:02d}"


def next_subtask_id(parent_task_id, tasks):
    """Return the next per-parent mentor subtask ID, e.g. DFPY01-01."""
    if not parent_task_id:
        return ""
    prefix = f"{parent_task_id}-"
    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$", re.IGNORECASE)
    sequence_numbers = [int(match.group(1)) for task in tasks
                        if (match := pattern.match(str(task.get("id", ""))))]
    return f"{parent_task_id}-{max(sequence_numbers, default=0) + 1:02d}"


def next_subtask_ids(parent_task_id, selected_ids, tasks):
    """Allocate consecutive subtask IDs in the same order as selected interns."""
    next_number = 1
    prefix = f"{parent_task_id}-"
    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$", re.IGNORECASE)
    existing = [int(match.group(1)) for task in tasks
                if (match := pattern.match(str(task.get("id", ""))))]
    next_number = max(existing, default=0) + 1
    return [f"{parent_task_id}-{next_number + offset:02d}" for offset, _ in enumerate(selected_ids)]


def parent_admin_task(task, tasks):
    parent_id = task.get("parent_task_id")
    if not parent_id:
        return task if task.get("created_by_role", "admin") == "admin" else None
    return next((item for item in tasks if item.get("id") == parent_id and
                 item.get("created_by_role", "admin") == "admin"), None)


def visible_project_file(task, user_role, tasks):
    """Return the ZIP a role is allowed to see for a task."""
    if user_role == "admin":
        return task.get("final_project_file")
    if user_role == "mentor":
        return task.get("intern_project_file") or task.get("project_file")
    if user_role == "intern":
        parent = parent_admin_task(task, tasks)
        return parent.get("final_project_file") if parent else None
    return None


def format_task_date(value):
    try:
        return date.fromisoformat(str(value)).strftime("%d-%m-%y")
    except (TypeError, ValueError):
        return value or "—"


def notification_timestamp():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def add_notification(recipient_id, task, user_name, action):
    if not recipient_id:
        return
    notifications = load_json(NOTIFICATIONS_FILE)
    notifications.append({
        "id": uuid4().hex,
        "recipient_id": recipient_id,
        "task_id": task.get("id", ""),
        "task_title": task.get("title", "Untitled task"),
        "user_name": user_name,
        "action": action,
        "created_at": notification_timestamp(),
        "read": False,
    })
    save_json(NOTIFICATIONS_FILE, notifications)


def notify_users(user_ids, task, user_name, action):
    for user_id in dict.fromkeys(user_ids):
        add_notification(user_id, task, user_name, action)


def admin_user_ids():
    return [user.get("id") for user in load_json(USERS_FILE) if user.get("role") == "admin"]


def mentor_user_ids_for_task(task, interns):
    users = load_json(USERS_FILE)
    assigned_ids = task.get("assigned_intern_ids") or [task.get("intern_id")]
    mentor_ids = {intern.get("assigned_mentor") for intern in interns
                  if intern.get("id") in assigned_ids and intern.get("assigned_mentor")}
    return [user.get("id") for user in users
            if user.get("role") == "mentor" and user.get("mentor_id") in mentor_ids]


def notify_task_assignees(task, interns, actor_name):
    users = load_json(USERS_FILE)
    selected_ids = task.get("assigned_intern_ids") or [task.get("intern_id")]
    recipient_ids = []
    for intern_id in selected_ids:
        intern = next((item for item in interns if item.get("id") == intern_id), None)
        if not intern:
            continue
        recipient_ids.extend(user.get("id") for user in users
                             if user.get("role") == "intern" and user.get("intern_id") == intern_id)
        recipient_ids.extend(user.get("id") for user in users
                             if user.get("role") == "mentor" and
                             user.get("mentor_id") == intern.get("assigned_mentor"))
    assigned_mentor = task.get("assigned_mentor")
    if assigned_mentor:
        recipient_ids.extend(user.get("id") for user in users
                             if user.get("role") == "mentor" and user.get("mentor_id") == assigned_mentor)
    notify_users(recipient_ids, task, actor_name, "Task assigned")


def canonical_department(value):
    value = str(value or "").strip()
    return DEPARTMENT_ALIASES.get(value, value)


def mentor_departments(mentor):
    """Return a mentor's departments as unique canonical department names."""
    if not mentor:
        return []
    departments = mentor.get("departments")
    if isinstance(departments, list):
        values = departments
    elif isinstance(departments, str) and departments.strip():
        values = departments.split(",")
    else:
        values = [mentor.get("department", "")]
    return list(dict.fromkeys(canonical_department(d) for d in values if str(d).strip()))

def current_mentor_departments(user=None, mentors=None):
    user = user or current_user()
    mentors = mentors if mentors is not None else load_json(MENTORS_FILE)
    mentor_id = (user or {}).get("mentor_id")
    mentor = next((m for m in mentors if m.get("id") == mentor_id), None)
    return mentor_departments(mentor)

def available_departments(interns=None, mentors=None):
    return list(dict.fromkeys(DEFAULT_DEPARTMENTS))


def save_upload(file_storage, folder, prefix):
    if not file_storage or not file_storage.filename:
        return None
    filename = secure_filename(file_storage.filename)
    if not filename:
        return None
    stored_name = f"{prefix}_{uuid4().hex[:12]}_{filename}"
    destination = folder / stored_name
    file_storage.save(destination)
    return {"filename": filename, "stored_name": stored_name}


def document_path(record):
    if not record or not record.get("stored_name"):
        return None
    path = DOC_UPLOAD_DIR / record["stored_name"]
    return path if path.exists() else None


def project_path(record):
    if not record or not record.get("stored_name"):
        return None
    path = PROJECT_UPLOAD_DIR / record["stored_name"]
    return path if path.exists() else None


def set_completed_timestamp(task, status):
    normalized = normalize_task_status(status)
    task["status"] = normalized
    if normalized == "Completed":
        task.setdefault("completed_at", date.today().isoformat())
    else:
        task.pop("completed_at", None)


def task_department(task, interns):
    if task.get("department"):
        return task.get("department")
    assigned_ids = task.get("assigned_intern_ids") or [task.get("intern_id")]
    for intern in interns:
        if intern.get("id") in assigned_ids:
            return intern.get("department", "")
    return ""


def get_data():
    interns = load_json(INTERNS_FILE)
    changed = False
    for intern in interns:
        duration = intern.get("duration_months")
        if duration:
            try:
                intern["end_date"] = calculate_end_date(intern["joining_date"], int(duration))
                intern["employment_status"] = calculate_intern_status(intern["end_date"])
                changed = True
            except (KeyError, TypeError, ValueError):
                pass
    if changed:
        save_json(INTERNS_FILE, interns)
    tasks = load_json(TASKS_FILE)
    tasks_changed = False
    for task in tasks:
        legacy_status = normalize_task_status(task.get("status", "Start"))
        if "intern_status" not in task:
            task["intern_status"] = legacy_status
            tasks_changed = True
        if "mentor_status" not in task:
            task["mentor_status"] = legacy_status
            tasks_changed = True
        if "mentor_pending_status" not in task:
            task["mentor_pending_status"] = None
            tasks_changed = True
        if "mentor_pending" not in task:
            task["mentor_pending"] = False
            tasks_changed = True
        # Keep intern submissions private to mentors. Legacy project_file values
        # are left intact for compatibility, but new uploads use intern_project_file.
        if task.get("created_by_role") == "mentor" and "intern_project_file" not in task:
            if task.get("project_file"):
                task["intern_project_file"] = task.get("project_file")
                task.pop("project_file", None)
                tasks_changed = True
    if tasks_changed:
        save_json(TASKS_FILE, tasks)
    mentors = load_json(MENTORS_FILE)
    mentors_changed = False
    for mentor in mentors:
        departments = mentor_departments(mentor)
        if mentor.get("departments") != departments or mentor.get("department", "") != (departments[0] if departments else ""):
            mentor["departments"] = departments
            mentor["department"] = departments[0] if departments else ""
            mentors_changed = True
    if mentors_changed:
        save_json(MENTORS_FILE, mentors)
    return interns, tasks, mentors


def normalize_task_status(value):
    if value is None:
        return "Start"
    status = str(value).strip()
    normalized = status.casefold()
    if normalized in {"pending", "start"}:
        return "Start"
    if normalized in {"in progress", "in_progress"}:
        return "In Progress"
    if normalized in {"completed", "done"}:
        return "Completed"
    if normalized in {"not completed", "not-completed", "notcomplete", "uncompleted"}:
        return "Not Completed"
    return status if status in STATUSES else "Start"


def task_status_for_role(task, role):
    if role == "intern":
        return normalize_task_status(task.get("intern_status", task.get("status", "Start")))
    if role == "mentor" and task.get("mentor_pending"):
        return normalize_task_status(task.get("mentor_pending_status", task.get("status", "Start")))
    return normalize_task_status(task.get("status", "Start"))


def is_overdue(task):
    try:
        return normalize_task_status(task.get("status")) != "Completed" and date.fromisoformat(task["deadline"]) < date.today()
    except (KeyError, TypeError, ValueError):
        return False


def intern_summary(intern, tasks, role="admin"):
    assigned = [{**task, "overdue": is_overdue(task),
                 "deadline_display": format_task_date(task.get("deadline")),
                 "view_status": task_status_for_role(task, role)} for task in tasks
                if intern["id"] in task.get("assigned_intern_ids", [task.get("intern_id")])]
    completed = sum(task["view_status"] == "Completed" for task in assigned)
    start_tasks = sum(task["view_status"] == "Start" for task in assigned)
    not_completed_tasks = sum(task["view_status"] == "Not Completed" for task in assigned)
    completed_items = [task for task in assigned if task["view_status"] == "Completed"]
    latest_completed = max(
        completed_items,
        key=lambda task: task.get("completed_at") or task.get("deadline") or "",
        default=None,
    )
    return {**intern, "tasks": assigned, "total_tasks": len(assigned),
            "completed_tasks": completed,
            "start_tasks": start_tasks,
            "pending_tasks": start_tasks,
            "not_completed_tasks": not_completed_tasks,
            "in_progress_tasks": sum(task["view_status"] == "In Progress" for task in assigned),
            "latest_completed_task": latest_completed.get("title") if latest_completed else "No completed task yet",
            "latest_completed_at": (latest_completed.get("completed_at") or latest_completed.get("deadline") or "") if latest_completed else "",
            "progress": round(completed / len(assigned) * 100, 1) if assigned else 0}


def decorate_tasks(tasks, interns):
    names = {intern["id"]: intern["name"] for intern in interns}
    all_tasks = load_json(TASKS_FILE)
    role = current_user().get("role") if current_user() else "admin"
    decorated = []
    for task in tasks:
        assigned_ids = task.get("assigned_intern_ids") or [task.get("intern_id")]
        assigned_names = task.get("assigned_names") or [names.get(task.get("intern_id"), "Unknown intern")]
        decorated.append({**task, "task_type": task.get("task_type", "Individual Work"),
                          "project_file": visible_project_file(task, role, all_tasks),
                          "intern_project_file": task.get("intern_project_file"),
                          "final_project_file": task.get("final_project_file"),
                          "assigned_intern_ids": assigned_ids,
                          "assigned_names": assigned_names,
                          "assigned_count": len(assigned_ids),
                          "intern_name": ", ".join(assigned_names),
                          "deadline_display": format_task_date(task.get("deadline")),
                          "department": task_department(task, interns),
                          "overdue": is_overdue(task),
                          "view_status": task_status_for_role(task, current_user().get("role") if current_user() else "admin"),
                          "mentor_pending": bool(task.get("mentor_pending")),
                          "pending_status": task.get("mentor_pending_status")})
    return decorated


def check_password(stored, password):
    try:
        algorithm, salt, expected = stored.split("$", 2)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120000).hex()
        return actual == expected
    except ValueError:
        return False


def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120000).hex()
    return f"pbkdf2_sha256${salt}${digest}"


def find_user(identifier, users):
    identifier = identifier.strip().casefold()
    return next((u for u in users
                 if u.get("username", "").casefold() == identifier
                 or u.get("email", "").casefold() == identifier), None)


def profile_name(user, interns, mentors):
    if user.get("role") == "intern":
        item = next((i for i in interns if i.get("id") == user.get("intern_id")), None)
        return item.get("name") if item else ""
    if user.get("role") == "mentor":
        item = next((m for m in mentors if m.get("id") == user.get("mentor_id")), None)
        return item.get("name") if item else ""
    return ""


def current_user():
    return session.get("user")


def login_required():
    return "user" in session


def role_required(*roles):
    user = current_user()
    return bool(user and user.get("role") in roles)


def find_intern_for_user(user, interns):
    return next((i for i in interns if i.get("id") == user.get("intern_id")), None)


def mentor_intern_ids(user, interns):
    return {i.get("id") for i in interns if i.get("assigned_mentor") == user.get("mentor_id")}


@app.context_processor
def navigation_data():
    user = current_user()
    notifications = []
    if user:
        notifications = [item for item in load_json(NOTIFICATIONS_FILE)
                         if item.get("recipient_id") == user.get("id")]
        notifications.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return {"current_year": date.today().year, "current_user": user,
            "notifications": notifications[:12],
            "unread_notifications": sum(not item.get("read", False) for item in notifications)}


@app.route("/login", methods=["GET", "POST"])
def login():
    if login_required():
        return redirect(url_for("home"))

    if request.method == "POST":
        identifier = request.form.get("username_or_email", "").strip()
        password = request.form.get("password", "")
        selected_role = request.form.get("role", "").strip().casefold()

        users = load_json(USERS_FILE)
        user = find_user(identifier, users)
       
        user = find_user(identifier, users)

        if user and user.get("role", "").casefold() == selected_role and check_password(user.get("password", ""), password):
                session.clear()
                session["user"] = {
                    k: user[k]
                    for k in ("id", "username", "email", "role", "mentor_id", "intern_id")
                    if k in user
                }
                flash(f"Welcome, {user.get('username', identifier)}!", "success")
                return redirect(url_for("home"))

        flash("Invalid login details or selected role.", "danger")

    return render_template("login.html")



@app.route("/admin/users", methods=["GET", "POST"])
def user_management():
    if not role_required("admin"):
        flash("Only an admin can manage login accounts.", "danger")
        return redirect(url_for("home"))
    users = load_json(USERS_FILE)
    interns, _, mentors = get_data()
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "").strip().casefold()
        profile_id = request.form.get("profile_id", "").strip()
        if not username or not email or not password or role not in {"admin", "mentor", "intern"}:
            flash("Username, email, password, and role are required.", "danger")
        elif len(password) < 6:
            flash("Password must be at least 6 characters.", "danger")
        elif any(u.get("username", "").casefold() == username.casefold() or u.get("email", "").casefold() == email.casefold() for u in users):
            flash("Username or email is already in use.", "danger")
        elif role == "mentor" and not any(m.get("id") == profile_id for m in mentors):
            flash("Select a valid mentor profile.", "danger")
        elif role == "intern" and not any(i.get("id") == profile_id for i in interns):
            flash("Select a valid intern profile.", "danger")
        else:
            new_user = {"id": uuid4().hex[:10], "username": username, "email": email,
                        "password": hash_password(password), "role": role}
            if role == "mentor":
                new_user["mentor_id"] = profile_id
            elif role == "intern":
                new_user["intern_id"] = profile_id
            users.append(new_user)
            save_json(USERS_FILE, users)
            flash("Login account created successfully.", "success")
            return redirect(url_for("user_management"))
    rows = []
    for user in users:
        rows.append({**user, "profile": profile_name(user, interns, mentors)})
    return render_template("user_management.html", users=rows, interns=interns, mentors=mentors)


@app.route("/admin/users/<user_id>/edit", methods=["GET", "POST"])
def edit_user(user_id):
    if not role_required("admin"):
        flash("Only an admin can edit login accounts.", "danger")
        return redirect(url_for("home"))
    users = load_json(USERS_FILE)
    interns, _, mentors = get_data()
    user = next((u for u in users if u.get("id") == user_id), None)
    if not user:
        flash("User account not found.", "danger")
        return redirect(url_for("user_management"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        role = request.form.get("role", "").strip().casefold()
        profile_id = request.form.get("profile_id", "").strip()
        password = request.form.get("password", "")
        duplicate = any(u.get("id") != user_id and
                        (u.get("username", "").casefold() == username.casefold() or
                         u.get("email", "").casefold() == email.casefold()) for u in users)
        if not username or not email or role not in {"admin", "mentor", "intern"}:
            flash("Username, email, and role are required.", "danger")
        elif duplicate:
            flash("Username or email is already in use.", "danger")
        elif password and len(password) < 6:
            flash("Password must be at least 6 characters.", "danger")
        elif role == "mentor" and not any(m.get("id") == profile_id for m in mentors):
            flash("Select a valid mentor profile.", "danger")
        elif role == "intern" and not any(i.get("id") == profile_id for i in interns):
            flash("Select a valid intern profile.", "danger")
        else:
            user["username"] = username
            user["email"] = email
            user["role"] = role
            user.pop("mentor_id", None)
            user.pop("intern_id", None)
            if role == "mentor":
                user["mentor_id"] = profile_id
            elif role == "intern":
                user["intern_id"] = profile_id
            if password:
                user["password"] = hash_password(password)
            save_json(USERS_FILE, users)
            if current_user().get("id") == user_id: # type: ignore
                session["user"] = {k: user[k] for k in ("id", "username", "email", "role", "mentor_id", "intern_id") if k in user}
            flash("User account updated.", "success")
            return redirect(url_for("user_management"))
    return render_template("edit_user.html", user=user, interns=interns, mentors=mentors)


@app.post("/admin/users/<user_id>/delete")
def delete_user(user_id):
    if not role_required("admin"):
        flash("Only an admin can delete login accounts.", "danger")
        return redirect(url_for("home"))
    users = load_json(USERS_FILE)
    if current_user().get("id") == user_id:
        flash("You cannot delete the account you are currently using.", "danger")
    elif not any(u.get("id") == user_id for u in users):
        flash("User account not found.", "danger")
    else:
        save_json(USERS_FILE, [u for u in users if u.get("id") != user_id])
        flash("User account deleted.", "success")
    return redirect(url_for("user_management"))


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


@app.route("/")
def home():
    if not login_required():
        return redirect(url_for("login"))
    role = current_user().get("role")
    if role == "admin":
        return redirect(url_for("dashboard"))
    if role == "mentor":
        return redirect(url_for("mentor_dashboard"))
    return redirect(url_for("intern_dashboard"))


@app.route("/admin/dashboard")
def dashboard():
    if not role_required("admin"):
        flash("Admin access is required.", "danger")
        return redirect(url_for("home"))
    interns, tasks, mentors = get_data()
    completed = sum(normalize_task_status(task.get("status")) == "Completed" for task in tasks)
    start = sum(normalize_task_status(task.get("status")) == "Start" for task in tasks)
    not_completed = sum(normalize_task_status(task.get("status")) == "Not Completed" for task in tasks)
    in_progress = sum(normalize_task_status(task.get("status")) == "In Progress" for task in tasks)
    overdue = sum(is_overdue(task) for task in tasks)
    active_interns = sum(intern.get("employment_status") == "Active Intern" for intern in interns)
    past_employees = sum(intern.get("employment_status") == "Past Employee" for intern in interns)
    total_departments = len({intern.get("department") for intern in interns if intern.get("department")})
    intern_summaries = [intern_summary(i, tasks) for i in interns]
    recent_completed = sorted(
        [i for i in intern_summaries if i.get("latest_completed_at")],
        key=lambda i: i.get("latest_completed_at", ""), reverse=True
    )
    return render_template("dashboard.html", interns=intern_summaries, recent_completed=recent_completed,
                           tasks=decorate_tasks(tasks, interns), total_interns=len(interns),
                           mentors=mentors, total_mentors=len(mentors), total_tasks=len(tasks),
                           completed=completed, start=start, not_completed=not_completed, in_progress=in_progress,
                           overdue=overdue, active_interns=active_interns,
                           past_employees=past_employees, total_departments=total_departments,
                           progress=round(completed / len(tasks) * 100, 1) if tasks else 0)


@app.route("/mentor/dashboard")
def mentor_dashboard():
    if not role_required("mentor"):
        flash("Mentor access is required.", "danger")
        return redirect(url_for("home"))
    interns, tasks, _ = get_data()
    ids = mentor_intern_ids(current_user(), interns)
    my_interns = [intern_summary(i, tasks, role="mentor") for i in interns if i.get("id") in ids]
    my_tasks = [t for t in tasks if ids.intersection(t.get("assigned_intern_ids", [t.get("intern_id")]))]
    admin_tasks = [t for t in my_tasks if t.get("created_by_role", "admin") != "mentor" and not t.get("parent_task_id")]
    mentor_subtasks = [t for t in my_tasks if t.get("created_by_role") == "mentor" or t.get("parent_task_id")]
    parent_titles = {t.get("id"): t.get("title", "") for t in tasks}
    def prepare(row):
        item = decorate_tasks([row], interns)[0]
        item["parent_task_title"] = row.get("parent_task_title") or parent_titles.get(row.get("parent_task_id"), "")
        item["start_date"] = row.get("start_date", "")
        item["duration_months"] = row.get("duration_months")
        return item
    admin_tasks = [prepare(t) for t in admin_tasks]
    mentor_subtasks = [prepare(t) for t in mentor_subtasks]
    completed = sum(normalize_task_status(t.get("status")) == "Completed" for t in my_tasks)
    return render_template("mentor_dashboard.html", interns=my_interns,
                           tasks=decorate_tasks(my_tasks, interns), admin_tasks=admin_tasks, mentor_subtasks=mentor_subtasks,
                           total_tasks=len(my_tasks), completed=completed, priorities=PRIORITIES, statuses=STATUSES,
                           progress=round(completed / len(my_tasks) * 100, 1) if my_tasks else 0)


@app.route("/intern/dashboard")
def intern_dashboard():
    if not role_required("intern"):
        flash("Intern access is required.", "danger")
        return redirect(url_for("home"))
    interns, tasks, mentors = get_data()
    intern = find_intern_for_user(current_user(), interns)
    if not intern:
        session.clear()
        flash("Your intern profile could not be found.", "danger")
        return redirect(url_for("login"))
    summary = intern_summary(intern, tasks, role="intern")
    mentor = next((m for m in mentors if m.get("id") == intern.get("assigned_mentor")), None)
    return render_template("intern_dashboard.html", intern=summary, mentor=mentor)


@app.route("/intern/mentor-tasks")
def intern_mentor_tasks():
    if not role_required("intern"):
        flash("Intern access is required.", "danger")
        return redirect(url_for("home"))
    interns, tasks, _ = get_data()
    user = current_user()
    intern_id = user.get("intern_id")
    parent_titles = {t.get("id"): t.get("title", "") for t in tasks}
    mentor_tasks = []
    for task in tasks:
        assigned = task.get("assigned_intern_ids") or [task.get("intern_id")]
        if intern_id in assigned and task.get("created_by_role") == "mentor":
            parent = next((p for p in tasks if p.get("id") == task.get("parent_task_id") and
                           p.get("created_by_role", "admin") == "admin"), None)
            row = {
                **task,
                "parent_task_title": task.get("parent_task_title") or parent_titles.get(task.get("parent_task_id"), ""),
                "parent_final_project_file": parent.get("final_project_file") if parent else None,
                "deadline_display": format_task_date(task.get("deadline")),
                "view_status": task_status_for_role(task, "intern"),
                "overdue": is_overdue(task),
            }
            mentor_tasks.append(row)
    return render_template("intern_mentor_tasks.html", mentor_tasks=mentor_tasks)


@app.route("/interns")
def view_interns():
    if not role_required("admin", "mentor"):
        flash("You do not have permission to view the intern directory.", "danger")
        return redirect(url_for("home"))
    interns, tasks, mentors = get_data()
    mentor_names = {mentor["id"]: mentor["name"] for mentor in mentors}
    enriched = [{**intern, "mentor_name": mentor_names.get(intern.get("assigned_mentor"), "Unassigned")}
                for intern in interns]
    if role_required("mentor"):
        ids = mentor_intern_ids(current_user(), interns)
        enriched = [i for i in enriched if i.get("id") in ids]
    enriched = [intern_summary(i, tasks) for i in enriched]
    enriched.sort(key=lambda item: (0 if item.get("employment_status") == "Active Intern" else 1,
                                    item.get("end_date") or "9999-12-31", item.get("name", "").casefold()))
    return render_template("interns.html", interns=enriched, departments=available_departments(interns, mentors))


@app.get("/interns/<intern_id>")
def view_intern_profile(intern_id):
    if not role_required("admin", "mentor"):
        flash("You do not have permission to view intern profiles.", "danger")
        return redirect(url_for("home"))
    interns, tasks, mentors = get_data()
    intern = next((item for item in interns if item.get("id") == intern_id), None)
    if not intern:
        flash("Intern not found.", "danger")
        return redirect(url_for("view_interns"))
    if role_required("mentor") and intern_id not in mentor_intern_ids(current_user(), interns):
        flash("You cannot view this intern profile.", "danger")
        return redirect(url_for("view_interns"))
    summary = intern_summary(intern, tasks, role=current_user().get("role", "admin"))
    mentor = next((item for item in mentors if item.get("id") == intern.get("assigned_mentor")), None)
    assigned_tasks = summary["tasks"]
    return render_template("intern_profile.html", intern=summary, mentor=mentor,
                           assigned_tasks=assigned_tasks,
                           pending_tasks=summary["total_tasks"] - summary["completed_tasks"])


@app.route("/interns/add", methods=["GET", "POST"])
def add_intern():
    if not role_required("admin"):
        flash("Only an admin can add interns.", "danger")
        return redirect(url_for("home"))
    interns, _, mentors = get_data()
    if request.method == "POST":
        intern = {field: request.form.get(field, "").strip() for field in
              ("name", "email", "phone", "department", "joining_date", "duration_months")}
        intern["id"] = next_profile_id("DFIN", interns)
        intern["assigned_mentor"] = request.form.get("assigned_mentor", "").strip()
        uploaded = save_upload(request.files.get("document"), DOC_UPLOAD_DIR, "intern")
        if uploaded:
            intern["document"] = uploaded
        try:
            duration_months = int(intern["duration_months"])
            end_date = calculate_end_date(intern["joining_date"], duration_months)
        except (TypeError, ValueError):
            duration_months = 0
            end_date = ""
        if not all(intern[field] for field in
                   ("id", "name", "email", "phone", "department", "joining_date")) or duration_months <= 0:
            flash("Please complete every intern field.", "danger")
        elif any(item.get("id") == intern["id"] for item in interns):
            flash("That Intern ID is already in use.", "danger")
        else:
            intern["duration_months"] = duration_months
            intern["end_date"] = end_date
            intern["employment_status"] = calculate_intern_status(end_date)
            interns.append(intern)
            save_json(INTERNS_FILE, interns)
            flash("Intern added successfully.", "success")
            return redirect(url_for("view_interns"))
    return render_template("add_intern.html", intern=None, next_intern_id=next_profile_id("DFIN", interns),
                           mentors=mentors, departments=available_departments(interns, mentors))


@app.route("/mentors")
def view_mentors():
    if not role_required("admin"):
        flash("Only an admin can manage mentors.", "danger")
        return redirect(url_for("home"))
    interns, _, mentors = get_data()
    rows = []
    for mentor in mentors:
        assigned_count = sum(i.get("assigned_mentor") == mentor.get("id") for i in interns)
        departments_for_mentor = mentor_departments(mentor)
        rows.append({**mentor, "departments": departments_for_mentor, "department_display": ", ".join(departments_for_mentor), "assigned_count": assigned_count})
    return render_template("mentors.html", mentors=rows, departments=available_departments(interns, mentors))


@app.get("/mentors/<mentor_id>")
def view_mentor_profile(mentor_id):
    if not role_required("admin"):
        flash("Only an admin can view mentor profiles.", "danger")
        return redirect(url_for("home"))
    interns, tasks, mentors = get_data()
    mentor = next((item for item in mentors if item.get("id") == mentor_id), None)
    if not mentor:
        flash("Mentor not found.", "danger")
        return redirect(url_for("view_mentors"))
    mentor_interns = [intern_summary(intern, tasks) for intern in interns
                      if intern.get("assigned_mentor") == mentor_id]
    mentor_intern_ids_set = {intern.get("id") for intern in mentor_interns}
    assigned_tasks = [task for task in tasks
                      if mentor_intern_ids_set.intersection(
                          task.get("assigned_intern_ids") or [task.get("intern_id")])]
    task_rows = decorate_tasks(assigned_tasks, interns)
    completed_tasks = sum(normalize_task_status(task.get("status")) == "Completed" for task in assigned_tasks)
    total_tasks = len(assigned_tasks)
    return render_template("mentor_profile.html", mentor=mentor,
                           departments=mentor_departments(mentor), interns=mentor_interns,
                           assigned_tasks=task_rows, total_tasks=total_tasks,
                           completed_tasks=completed_tasks,
                           pending_tasks=total_tasks - completed_tasks,
                           progress=round(completed_tasks / total_tasks * 100, 1) if total_tasks else 0)


@app.route("/mentors/add", methods=["GET", "POST"])
def add_mentor():
    if not role_required("admin"):
        flash("Only an admin can add mentors.", "danger")
        return redirect(url_for("home"))
    interns, _, mentors = get_data()
    if request.method == "POST":
        selected_departments = list(dict.fromkeys(d.strip() for d in request.form.getlist("departments") if d.strip()))
        mentor = {
            "id": next_profile_id("DFM", mentors),
            "name": request.form.get("name", "").strip(),
            "email": request.form.get("email", "").strip(),
            "phone": request.form.get("phone", "").strip(),
            "departments": selected_departments,
            "department": selected_departments[0] if selected_departments else "",
        }
        uploaded = save_upload(request.files.get("document"), DOC_UPLOAD_DIR, "mentor")
        if uploaded:
            mentor["document"] = uploaded
        if not mentor["name"] or not mentor["email"] or not mentor["phone"] or not mentor["departments"]:
            flash("Please complete every mentor field and select at least one department.", "danger")
        elif any(m.get("id") == mentor["id"] for m in mentors):
            flash("That Mentor ID is already in use.", "danger")
        else:
            mentors.append(mentor)
            save_json(MENTORS_FILE, mentors)
            flash("Mentor added successfully.", "success")
            return redirect(url_for("view_mentors"))
    return render_template("add_mentor.html", mentor=None, next_mentor_id=next_profile_id("DFM", mentors),
                           departments=available_departments(interns, mentors))


@app.route("/mentors/<mentor_id>/edit", methods=["GET", "POST"])
def edit_mentor(mentor_id):
    if not role_required("admin"):
        flash("Only an admin can edit mentors.", "danger")
        return redirect(url_for("home"))
    interns, _, mentors = get_data()
    mentor = next((m for m in mentors if m.get("id") == mentor_id), None)
    if not mentor:
        flash("Mentor not found.", "danger")
        return redirect(url_for("view_mentors"))
    if request.method == "POST":
        mentor["name"] = request.form.get("name", "").strip()
        mentor["email"] = request.form.get("email", "").strip()
        mentor["phone"] = request.form.get("phone", "").strip()
        selected_departments = list(dict.fromkeys(d.strip() for d in request.form.getlist("departments") if d.strip()))
        mentor["departments"] = selected_departments
        mentor["department"] = selected_departments[0] if selected_departments else ""
        uploaded = save_upload(request.files.get("document"), DOC_UPLOAD_DIR, "mentor")
        if uploaded:
            mentor["document"] = uploaded
        if not mentor.get("name") or not mentor.get("email") or not mentor.get("phone") or not mentor.get("departments"):
            flash("Please complete every mentor field and select at least one department.", "danger")
        else:
            save_json(MENTORS_FILE, mentors)
            flash("Mentor details updated.", "success")
            return redirect(url_for("view_mentors"))
    return render_template("add_mentor.html", mentor=mentor, departments=available_departments(interns, mentors))


@app.post("/mentors/<mentor_id>/delete")
def delete_mentor(mentor_id):
    if not role_required("admin"):
        flash("Only an admin can delete mentors.", "danger")
        return redirect(url_for("home"))
    interns, _, mentors = get_data()
    if any(i.get("assigned_mentor") == mentor_id for i in interns):
        flash("Reassign this mentor's interns before deleting the mentor.", "danger")
    elif not any(m.get("id") == mentor_id for m in mentors):
        flash("Mentor not found.", "danger")
    else:
        save_json(MENTORS_FILE, [m for m in mentors if m.get("id") != mentor_id])
        flash("Mentor deleted.", "success")
    return redirect(url_for("view_mentors"))


@app.get("/documents/<kind>/<item_id>")
def download_document(kind, item_id):
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    interns, _, mentors = get_data()
    record = None
    if kind == "intern":
        record = next((i for i in interns if i.get("id") == item_id), None)
        allowed = user.get("role") == "admin" or (
            user.get("role") == "intern" and user.get("intern_id") == item_id
        ) or (
            user.get("role") == "mentor" and item_id in mentor_intern_ids(user, interns)
        )
    elif kind == "mentor":
        record = next((m for m in mentors if m.get("id") == item_id), None)
        allowed = user.get("role") == "admin" or (
            user.get("role") == "mentor" and user.get("mentor_id") == item_id
        )
    else:
        return redirect(url_for("home"))
    if not record or not allowed:
        flash("You do not have permission to download this document.", "danger")
        return redirect(url_for("home"))
    path = document_path(record.get("document"))
    if not path:
        flash("No document is available for this person.", "warning")
        return redirect(url_for("home"))
    return send_file(path, as_attachment=True, download_name=record["document"].get("filename", path.name))




@app.route("/interns/<intern_id>/edit", methods=["GET", "POST"])
def edit_intern(intern_id):
    if not role_required("admin"):
        flash("Only an admin can edit interns.", "danger")
        return redirect(url_for("home"))
    interns, _, mentors = get_data()
    intern = next((item for item in interns if item.get("id") == intern_id), None)
    if intern is None:
        flash("Intern not found.", "danger")
        return redirect(url_for("view_interns"))
    if request.method == "POST":
        for field in ("name", "email", "phone", "department", "joining_date"):
            intern[field] = request.form.get(field, "").strip()
        try:
            duration_months = int(request.form.get("duration_months", "0"))
            end_date = calculate_end_date(intern["joining_date"], duration_months)
        except (TypeError, ValueError):
            flash("Enter a valid internship duration and joining date.", "danger")
            return render_template("add_intern.html", intern=intern, mentors=mentors, departments=available_departments(interns, mentors))
        if duration_months <= 0:
            flash("Internship duration must be greater than zero.", "danger")
            return render_template("add_intern.html", intern=intern, mentors=mentors, departments=available_departments(interns, mentors))
        intern["duration_months"] = duration_months
        intern["end_date"] = end_date
        intern["employment_status"] = calculate_intern_status(end_date)
        intern["assigned_mentor"] = request.form.get("assigned_mentor", "").strip()
        uploaded = save_upload(request.files.get("document"), DOC_UPLOAD_DIR, "intern")
        if uploaded:
            intern["document"] = uploaded
        save_json(INTERNS_FILE, interns)
        flash("Intern details updated.", "success")
        return redirect(url_for("view_interns"))
    return render_template("add_intern.html", intern=intern, mentors=mentors, departments=available_departments(interns, mentors))


@app.post("/interns/<intern_id>/delete")
def delete_intern(intern_id):
    if not role_required("admin"):
        flash("Only an admin can delete interns.", "danger")
        return redirect(url_for("home"))
    interns, tasks, _ = get_data()
    save_json(INTERNS_FILE, [item for item in interns if item.get("id") != intern_id])
    save_json(TASKS_FILE, [task for task in tasks if task.get("intern_id") != intern_id])
    flash("Intern and assigned tasks deleted.", "success")
    return redirect(url_for("view_interns"))


@app.route("/tasks")
def view_tasks():
    if not role_required("admin", "mentor"):
        flash("Only admins and mentors can view the full task list.", "danger")
        return redirect(url_for("home"))
    interns, tasks, _ = get_data()
    if role_required("mentor"):
        ids = mentor_intern_ids(current_user(), interns)
        mentor_id = current_user().get("mentor_id")
        tasks = [t for t in tasks if t.get("assigned_mentor") == mentor_id or ids.intersection(
            t.get("assigned_intern_ids", [t.get("intern_id")]))]
    return render_template("tasks.html", tasks=decorate_tasks(tasks, interns))


@app.get("/tasks/<task_id>")
def view_task(task_id):
    if not login_required():
        return redirect(url_for("home"))
    interns, tasks, mentors = get_data()
    task = next((item for item in tasks if item.get("id") == task_id), None)
    if task is None:
        flash("Task not found.", "danger")
        return redirect(url_for("view_tasks"))
    assigned_ids = task.get("assigned_intern_ids", [task.get("intern_id")])
    user = current_user()
    if user.get("role") == "mentor" and not mentor_intern_ids(user, interns).intersection(assigned_ids):
        flash("You cannot view this task.", "danger")
        return redirect(url_for("view_tasks"))
    if user.get("role") == "intern" and user.get("intern_id") not in assigned_ids:
        flash("You cannot view this task.", "danger")
        return redirect(url_for("intern_dashboard"))
    intern_by_id = {item.get("id"): item for item in interns}
    mentor_names = {mentor["id"]: mentor["name"] for mentor in mentors}
    assigned_interns = []
    for intern_id in task.get("assigned_intern_ids", [task.get("intern_id")]):
        intern = intern_by_id.get(intern_id)
        if intern:
            assigned_interns.append({**intern, "mentor_name": mentor_names.get(
                intern.get("assigned_mentor"), "Unassigned")})
    decorated = decorate_tasks([task], interns)[0]
    parent = parent_admin_task(task, tasks)
    decorated["parent_final_project_file"] = parent.get("final_project_file") if parent else None
    decorated["intern_project_file"] = task.get("intern_project_file")
    decorated["final_project_file"] = task.get("final_project_file")
    return render_template("task_detail.html", task=decorated,
                           assigned_interns=assigned_interns, parent_task=parent)


@app.route("/tasks/add", methods=["GET", "POST"])
def assign_task():
    if not role_required("admin", "mentor"):
        flash("Only admins and mentors can assign tasks.", "danger")
        return redirect(url_for("home"))
    interns, tasks, mentors = get_data()
    mentor_depts = current_mentor_departments() if role_required("mentor") else list(DEFAULT_DEPARTMENTS)
    if role_required("mentor"):
        ids = mentor_intern_ids(current_user(), interns)
        interns = [i for i in interns if i.get("id") in ids]
    if request.method == "POST":
        task_type = request.form.get("task_type", "Individual Work").strip()
        selected_ids = [item.strip() for item in request.form.getlist("selected_intern_ids") if item.strip()]
        intern_id = request.form.get("intern_id", "").strip()
        assigned_mentor = request.form.get("assigned_mentor", "").strip() if role_required("admin") else ""
        if task_type == "Individual Work":
            selected_ids = [intern_id] if intern_id else []
        department = request.form.get("department", "").strip()
        if role_required("admin") and assigned_mentor and not any(m.get("id") == assigned_mentor for m in mentors):
            assigned_mentor = ""
        project_id = request.form.get("project_id", "").strip()
        title = request.form.get("title", "").strip()
        start_date = request.form.get("start_date", "").strip()
        parent_project = None
        if role_required("mentor") and project_id:
            parent_project = next((p for p in tasks if p.get("id") == project_id and
                                   p.get("created_by_role", "admin") == "admin"), None)
            if parent_project:
                # A mentor subtask inherits the Admin task's work mode, department,
                # and assigned interns. The mentor does not have to rebuild the
                # original individual/team allocation manually.
                task_type = parent_project.get("task_type", "Individual Work")
                parent_ids = [item for item in (parent_project.get("assigned_intern_ids") or
                                                 [parent_project.get("intern_id")]) if item]
                selected_ids = parent_ids
                department = parent_project.get("department", department)
                intern_id = selected_ids[0] if selected_ids else ""

        valid_ids = {item.get("id") for item in interns}
        if role_required("mentor") and (not project_id or not parent_project):
            flash("Choose an admin-created project before assigning work.", "danger")
        elif role_required("mentor") and department not in mentor_depts:
            flash("You can only assign work in your assigned departments.", "danger")
        elif role_required("mentor") and parent_project.get("department", "") not in mentor_depts:
            flash("The selected admin task is outside your assigned departments.", "danger")
        elif task_type not in ("Individual Work", "Team Work"):
            flash("Select a valid task type.", "danger")
        elif role_required("admin") and not assigned_mentor:
            flash("Select a mentor for this task.", "danger")
        elif not department or not selected_ids or not title or not start_date or not request.form.get("deadline", ""):
            flash("Select a department and at least one intern, then provide a title, starting date, and deadline.", "danger")
        elif any(item not in valid_ids for item in selected_ids):
            flash("You cannot assign a task to that intern.", "danger")
        elif any(next((i.get("department") for i in interns if i.get("id") == item), "") != department for item in selected_ids):
            flash("All selected interns must belong to the chosen department.", "danger")
        elif task_type == "Individual Work" and len(selected_ids) != 1:
            flash("Individual Work must have exactly one intern selected.", "danger")
        else:
            # Admin tasks keep the department-based ID. Mentor subtasks get a
            # child ID under their selected admin task, one ID per intern.
            if role_required("mentor"):
                new_ids = next_subtask_ids(parent_project.get("id"), selected_ids, tasks)
            else:
                new_ids = [task_id_for_department(department, tasks)]

            if not new_ids[0] or any(any(existing.get("id", "").casefold() == new_id.casefold() for existing in tasks)
                                     for new_id in new_ids):
                flash("A generated Task ID already exists. Please try again.", "danger")
            else:
                created = []
                for item_id, generated_id in zip(selected_ids, new_ids):
                    task = {
                        "id": generated_id,
                        "intern_id": item_id,
                        "task_type": task_type,
                        "department": department,
                        "title": title,
                        "description": request.form.get("description", "").strip(),
                        "start_date": start_date,
                        "deadline": request.form.get("deadline", ""),
                        "priority": request.form.get("priority", "Medium"),
                        "status": normalize_task_status(request.form.get("status", "Start")),
                        "intern_status": normalize_task_status(request.form.get("status", "Start")),
                        "mentor_status": normalize_task_status(request.form.get("status", "Start")),
                        "mentor_pending_status": None,
                        "mentor_pending": False,
                        "created_by_role": current_user().get("role"),
                        "assigned_mentor": assigned_mentor if role_required("admin") else (parent_project.get("assigned_mentor", "") if parent_project else ""),
                        "parent_task_id": parent_project.get("id") if parent_project else None,
                        "parent_task_title": parent_project.get("title", "") if parent_project else "",
                        "assigned_intern_ids": [item_id],
                        "assigned_names": [next(item["name"] for item in interns if item["id"] == item_id)],
                    }
                    set_completed_timestamp(task, task["status"])
                    tasks.append(task)
                    created.append(task)

                save_json(TASKS_FILE, tasks)
                if current_user().get("role") == "admin":
                    for task in created:
                        notify_task_assignees(task, interns, current_user().get("username", "Admin"))
                flash("Task assigned successfully.", "success")
                return redirect(url_for("view_tasks"))
    projects = [p for p in tasks if p.get("created_by_role", "admin") == "admin" and p.get("department", "") in mentor_depts] if role_required("mentor") else []
    assignment_departments = mentor_depts if role_required("mentor") else available_departments(interns)
    return render_template("assign_task.html", interns=interns,
                           departments=assignment_departments,
                           department_codes=DEPARTMENT_CODES,
                           department_task_ids={department: task_id_for_department(department, tasks)
                                                for department in assignment_departments},
                           projects=projects,
                           mentors=mentors,
                           project_subtask_ids={project.get("id"): next_subtask_id(project.get("id"), tasks) for project in projects},
                           task=None, priorities=PRIORITIES, statuses=STATUSES)


@app.route("/tasks/<task_id>/edit", methods=["GET", "POST"])
def edit_task(task_id):
    if not role_required("admin", "mentor"):
        flash("Only admins and mentors can edit tasks.", "danger")
        return redirect(url_for("home"))
    all_interns, tasks, mentors = get_data()
    # Always initialize mentor_depts before any mentor-only filtering below.
    # This prevents NameError when editing a task as a mentor.
    mentor_depts = []
    if role_required("mentor"):
        mentor_depts = list(current_mentor_departments())
    else:
        mentor_depts = list(DEFAULT_DEPARTMENTS)
    task = next((item for item in tasks if item.get("id") == task_id), None)
    if task is None:
        flash("Task not found.", "danger")
        return redirect(url_for("view_tasks"))
    if role_required("mentor") and not mentor_intern_ids(current_user(), all_interns).intersection(
            task.get("assigned_intern_ids", [task.get("intern_id")])):
        flash("You cannot edit this task.", "danger")
        return redirect(url_for("view_tasks"))
    interns = all_interns
    if role_required("mentor"):
        interns = [i for i in all_interns if i.get("id") in mentor_intern_ids(current_user(), all_interns)]
    active_interns = interns
    task.setdefault("assigned_intern_ids", [task.get("intern_id")] if task.get("intern_id") else [])
    if not task.get("department"):
        task["department"] = task_department(task, all_interns)
    if request.method == "POST":
        task_type = request.form.get("task_type", "Individual Work").strip()
        selected_ids = [item.strip() for item in request.form.getlist("selected_intern_ids") if item.strip()]
        if task_type == "Individual Work":
            selected_ids = [request.form.get("intern_id", "").strip()]
        department = request.form.get("department", "").strip()
        project_id = request.form.get("project_id", "").strip()
        assigned_mentor = request.form.get("assigned_mentor", "").strip() if role_required("admin") else task.get("assigned_mentor", "")
        if role_required("admin") and assigned_mentor and not any(m.get("id") == assigned_mentor for m in mentors):
            assigned_mentor = ""
        if role_required("mentor"):
            project = next((p for p in tasks if p.get("id") == project_id and p.get("created_by_role", "admin") == "admin"), None)
            if project:
                task["parent_task_id"] = project_id
                task["parent_task_title"] = project.get("title", "")
                # Keep an edited mentor subtask synchronized with the Admin
                # task's original work mode and team allocation.
                task_type = project.get("task_type", "Individual Work")
                selected_ids = [item for item in (project.get("assigned_intern_ids") or
                                                   [project.get("intern_id")]) if item]
                department = project.get("department", department)
            task["title"] = request.form.get("title", "").strip()
        else:
            task["title"] = request.form.get("title", "").strip()
        task["description"] = request.form.get("description", "").strip()
        task["start_date"] = request.form.get("start_date", "").strip()
        task["deadline"] = request.form.get("deadline", "").strip()
        task["priority"] = request.form.get("priority", "Medium").strip()
        requested_status = normalize_task_status(request.form.get("status", "Start").strip())
        if role_required("admin"):
            set_completed_timestamp(task, requested_status)
            task["mentor_status"] = requested_status
        else:
            task["mentor_status"] = requested_status
            task["status"] = requested_status
        task["department"] = department
        selected_parent = next((p for p in tasks if p.get("id") == project_id and p.get("created_by_role", "admin") == "admin"), None)
        if role_required("admin") and not assigned_mentor:
            flash("Select a mentor for this task.", "danger")
        elif role_required("mentor") and (not project_id or not selected_parent):
            flash("Choose an admin-created project before editing this task.", "danger")
        elif role_required("mentor") and (department not in mentor_depts or selected_parent.get("department", "") not in mentor_depts):
            flash("You can only edit work in your assigned departments.", "danger")
        elif task_type not in ("Individual Work", "Team Work") or not selected_ids or any(item not in {i.get("id") for i in active_interns} for item in selected_ids):
            flash("You cannot assign this task to that intern.", "danger")
        elif not department:
            flash("Select a department.", "danger")
        elif any(next((i.get("department") for i in active_interns if i.get("id") == item), "") != department for item in selected_ids):
            flash("All selected interns must belong to the chosen department.", "danger")
        elif task_type == "Individual Work" and len(selected_ids) != 1:
            flash("Individual Work must have exactly one intern selected.", "danger")
        else:
            task["task_type"] = task_type
            task["intern_id"] = selected_ids[0]
            task["assigned_intern_ids"] = selected_ids
            task["assigned_names"] = [next(item["name"] for item in active_interns if item["id"] == item_id)
                                       for item_id in selected_ids]
            task["assigned_mentor"] = assigned_mentor
            save_json(TASKS_FILE, tasks)
            if role_required("mentor") and requested_status == "Completed":
                notify_users(admin_user_ids(), task, current_user().get("username", "Mentor"), "Marked task as completed")
            flash("Task details updated.", "success")
            return redirect(url_for("view_tasks"))
    projects = [p for p in tasks if p.get("created_by_role", "admin") == "admin" and p.get("department", "") in mentor_depts] if role_required("mentor") else []
    assignment_departments = mentor_depts if role_required("mentor") else available_departments(active_interns)
    return render_template("assign_task.html", interns=active_interns,
                           departments=assignment_departments,
                           department_codes=DEPARTMENT_CODES,
                           department_task_ids={department: task_id_for_department(department, tasks)
                                                for department in assignment_departments},
                           projects=projects,
                           mentors=mentors,
                           project_subtask_ids={project.get("id"): next_subtask_id(project.get("id"), tasks) for project in projects},
                           task=task, priorities=PRIORITIES, statuses=STATUSES)


@app.post("/tasks/<task_id>/delete")
def delete_task(task_id):
    if not role_required("admin", "mentor"):
        flash("Only admins and mentors can delete tasks.", "danger")
        return redirect(url_for("home"))
    interns, tasks, _ = get_data()
    task = next((t for t in tasks if t.get("id") == task_id), None)
    if task is None:
        flash("Task not found.", "danger")
    elif role_required("mentor") and not mentor_intern_ids(current_user(), interns).intersection(task.get("assigned_intern_ids", [task.get("intern_id")])):
        flash("You cannot delete this task.", "danger")
    else:
        save_json(TASKS_FILE, [t for t in tasks if t.get("id") != task_id])
        flash("Task deleted.", "success")
    return redirect(url_for("view_tasks"))


@app.post("/intern/tasks/<task_id>/status")
def update_intern_task_status(task_id):
    if not role_required("intern"):
        flash("Only interns can use this action.", "danger")
        return redirect(url_for("home"))
    interns, tasks, _ = get_data()
    user = current_user()
    task = next((t for t in tasks if t.get("id") == task_id), None)
    if task is None or user.get("intern_id") not in set(task.get("assigned_intern_ids") or [task.get("intern_id")]):
        flash("Task not found or access denied.", "danger")
        return redirect(url_for("intern_dashboard"))
    status = request.form.get("status", "").strip()
    normalized_status = normalize_task_status(status)
    if normalized_status not in STATUSES:
        flash("Invalid task status.", "danger")
    else:
        task["intern_status"] = normalized_status
        task["mentor_pending_status"] = normalized_status
        task["mentor_pending"] = True
        save_json(TASKS_FILE, tasks)
        if normalized_status == "Completed":
            notify_users(admin_user_ids() + mentor_user_ids_for_task(task, interns),
                         task, user.get("username", "Intern"), "Marked task as completed")
        flash("Status sent to your mentor for confirmation. Admin status will update after mentor confirmation.", "success")
    return redirect(url_for("intern_dashboard"))


@app.post("/mentor/tasks/<task_id>/confirm-status")
def confirm_intern_task_status(task_id):
    if not role_required("mentor"):
        flash("Only mentors can confirm intern status updates.", "danger")
        return redirect(url_for("home"))
    interns, tasks, _ = get_data()
    task = next((t for t in tasks if t.get("id") == task_id), None)
    if task is None:
        flash("Task not found.", "danger")
        return redirect(url_for("mentor_dashboard"))
    assigned = set(task.get("assigned_intern_ids") or [task.get("intern_id")])
    if not mentor_intern_ids(current_user(), interns).intersection(assigned):
        flash("You cannot confirm this task.", "danger")
        return redirect(url_for("mentor_dashboard"))
    if not task.get("mentor_pending"):
        flash("There is no pending intern status update.", "warning")
        return redirect(url_for("mentor_dashboard"))
    confirmed = normalize_task_status(task.get("mentor_pending_status", task.get("intern_status", "Start")))
    task["mentor_status"] = confirmed
    task["status"] = confirmed
    task["mentor_pending"] = False
    task["mentor_pending_status"] = None
    if confirmed == "Completed":
        task["completed_at"] = date.today().isoformat()
    else:
        task.pop("completed_at", None)
    save_json(TASKS_FILE, tasks)
    flash("Intern status confirmed. The admin view has been updated.", "success")
    return redirect(url_for("mentor_dashboard"))


@app.post("/notifications/<notification_id>/read")
def mark_notification_read(notification_id):
    if not login_required():
        return redirect(url_for("login"))
    notifications = load_json(NOTIFICATIONS_FILE)
    for notification in notifications:
        if (notification.get("id") == notification_id and
                notification.get("recipient_id") == current_user().get("id")):
            notification["read"] = True
            break
    save_json(NOTIFICATIONS_FILE, notifications)
    return redirect(request.referrer or url_for("home"))


@app.route("/reports")
def reports():
    if not role_required("admin", "mentor"):
        flash("Only admins and mentors can view reports.", "danger")
        return redirect(url_for("home"))
    interns, tasks, mentors = get_data()
    mentor_names = {mentor["id"]: mentor["name"] for mentor in mentors}
    enriched = [{**intern, "mentor_name": mentor_names.get(intern.get("assigned_mentor"), "Unassigned")}
                for intern in interns]
    if role_required("mentor"):
        ids = mentor_intern_ids(current_user(), interns)
        enriched = [i for i in enriched if i.get("id") in ids]
    intern_rows = [intern_summary(i, tasks) for i in enriched]
    for intern_row in intern_rows:
        report_statuses = set()
        for task in intern_row.get("tasks", []):
            status = normalize_task_status(task.get("view_status", task.get("status", "Start")))
            if status == "In Progress":
                report_statuses.add("in-progress")
            elif status == "Completed":
                report_statuses.add("completed")
            if task.get("overdue"):
                report_statuses.add("overdue")
        intern_row["report_statuses"] = sorted(report_statuses)
    mentor_rows = []
    for mentor in mentors:
        if role_required("mentor") and mentor.get("id") != current_user().get("mentor_id"):
            continue
        mentor_interns = [i for i in interns if i.get("assigned_mentor") == mentor.get("id")]
        mentor_intern_ids_set = {intern.get("id") for intern in mentor_interns}
        mentor_tasks = [task for task in tasks
                        if mentor_intern_ids_set.intersection(
                            task.get("assigned_intern_ids") or [task.get("intern_id")])]
        mentor_task_statuses = [normalize_task_status(task.get("status", "Start"))
                                for task in mentor_tasks]
        mentor_total_tasks = len(mentor_task_statuses)
        mentor_completed_tasks = mentor_task_statuses.count("Completed")
        mentor_in_progress_tasks = mentor_task_statuses.count("In Progress")
        mentor_pending_tasks = sum(status in {"Start", "Not Completed"}
                                   for status in mentor_task_statuses)
        mentor_report_statuses = set()
        for task, status in zip(mentor_tasks, mentor_task_statuses):
            if status == "In Progress":
                mentor_report_statuses.add("in-progress")
            elif status == "Completed":
                mentor_report_statuses.add("completed")
            if is_overdue(task):
                mentor_report_statuses.add("overdue")
        mentor_rows.append({
            **mentor,
            "assigned_count": len(mentor_interns),
            "total_tasks": mentor_total_tasks,
            "completed_tasks": mentor_completed_tasks,
            "in_progress_tasks": mentor_in_progress_tasks,
            "pending_tasks": mentor_pending_tasks,
            "report_statuses": sorted(mentor_report_statuses),
            "progress": round(mentor_completed_tasks / mentor_total_tasks * 100, 1)
            if mentor_total_tasks else 0,
        })
    return render_template("report.html", interns=intern_rows, mentors=mentor_rows,
                           departments=available_departments(interns, mentors))


@app.get("/download-report")
def download_report():
    if not role_required("admin", "mentor"):
        flash("Only admins and mentors can download reports.", "danger")
        return redirect(url_for("home"))
    interns, tasks, mentors = get_data()
    mentor_names = {mentor["id"]: mentor["name"] for mentor in mentors}
    requested_intern = request.args.get("intern_id", "").strip()
    requested_mentor = request.args.get("mentor_id", "").strip()

    if role_required("mentor"):
        allowed_ids = mentor_intern_ids(current_user(), interns)
        interns = [intern for intern in interns if intern.get("id") in allowed_ids]
        if requested_mentor and requested_mentor != current_user().get("mentor_id"):
            requested_mentor = ""

    if requested_intern:
        interns = [intern for intern in interns if intern.get("id") == requested_intern]
    enriched = [{**intern, "mentor_name": mentor_names.get(intern.get("assigned_mentor"), "Unassigned")}
                for intern in interns]
    report_rows = [intern_summary(intern, tasks) for intern in enriched]

    if requested_mentor:
        mentor = next((m for m in mentors if m.get("id") == requested_mentor), None)
        if not mentor:
            flash("Mentor not found.", "danger")
            return redirect(url_for("reports"))
        assigned = [i for i in load_json(INTERNS_FILE) if i.get("assigned_mentor") == requested_mentor]
        report_rows = [intern_summary(i, tasks) for i in assigned]
        title = f"Mentor Report - {mentor.get('name', 'Mentor')}"
        filename = f"mentor-report-{secure_filename(mentor.get('name', 'mentor'))}.pdf"
    else:
        title = "Progress Reports" if not requested_intern else f"Progress Report - {report_rows[0].get('name', 'Intern') if report_rows else 'Intern'}"
        filename = "progress-reports.pdf" if not requested_intern else f"progress-report-{secure_filename(report_rows[0].get('name', 'intern'))}.pdf"

    buffer = BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=A4, title=title)
    styles = getSampleStyleSheet()
    story = [Paragraph(escape(title), styles["Title"])]
    for intern in report_rows:
        story.extend([
            Paragraph(escape(intern.get("name", "")), styles["Heading2"]),
            Paragraph(escape(f'{intern.get("department", "")} · {intern.get("email", "")} · ID {intern.get("id", "")}'), styles["BodyText"]),
            Paragraph(escape(f'Mentor: {intern.get("mentor_name", "Unassigned")}'), styles["BodyText"]),
            Paragraph(escape(f'Progress: {intern.get("progress", 0)}% · Latest completed: {intern.get("latest_completed_task", "None")}'), styles["BodyText"]),
            Spacer(1, 6),
        ])
        rows = [["Task / Description", "Deadline", "Priority", "Status"]]
        for task in intern.get("tasks", []):
            task_title = escape(task.get("title", ""))
            description = escape(task.get("description", "") or "No description provided.")
            task_id = escape(task.get("id", ""))
            parent = escape(task.get("parent_task_id", "") or "")
            meta = f"Task ID: {task_id}" + (f" · Parent: {parent}" if parent else "")
            detail = Paragraph(f"<b>{task_title}</b><br/><font size='8'>{meta}</font><br/>{description}", styles["BodyText"])
            rows.append([detail, format_task_date(task.get("deadline")), task.get("priority", ""),
                         task.get("view_status", task.get("status", ""))])
        if len(rows) == 1:
            rows.append(["No tasks assigned.", "", "", ""])
        table = Table(rows, colWidths=[250, 75, 70, 75], repeatRows=1)
        table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, "#cccccc"),
                                   ("BACKGROUND", (0, 0), (-1, 0), "#eef2f5"),
                                   ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 6),
                                   ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                                   ("TOPPADDING", (0, 0), (-1, -1), 6),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        story.append(table)
        story.append(Spacer(1, 14))
    document.build(story)
    buffer.seek(0)
    return send_file(buffer, mimetype="application/pdf", as_attachment=True, download_name=filename)


@app.post("/intern/tasks/<task_id>/upload")
def upload_project(task_id):
    if not role_required("intern"):
        flash("Only interns can upload project files.", "danger")
        return redirect(url_for("home"))
    interns, tasks, _ = get_data()
    user = current_user()
    task = next((t for t in tasks if t.get("id") == task_id), None)
    if task is None or user.get("intern_id") not in (task.get("assigned_intern_ids") or [task.get("intern_id")]):
        flash("Task not found or access denied.", "danger")
        return redirect(url_for("intern_dashboard"))
    uploaded = save_upload(request.files.get("project_file"), PROJECT_UPLOAD_DIR, task_id)
    if not uploaded:
        flash("Choose a ZIP project file to upload.", "danger")
    elif not uploaded["filename"].lower().endswith(".zip"):
        path = PROJECT_UPLOAD_DIR / uploaded["stored_name"]
        path.unlink(missing_ok=True)
        flash("Only .zip project files are accepted.", "danger")
    else:
        task["intern_project_file"] = uploaded
        task.pop("project_file", None)
        save_json(TASKS_FILE, tasks)
        # Do not expose the intern upload to admin; only the assigned mentor can access it.
        notify_users(mentor_user_ids_for_task(task, interns), task, user.get("username", "Intern"), "Uploaded a project ZIP")
        flash("Project ZIP uploaded successfully. It is now available to your mentor.", "success")
    return redirect(url_for("intern_dashboard"))


@app.post("/mentor/tasks/<task_id>/final-upload")
def upload_final_project(task_id):
    if not role_required("mentor"):
        flash("Only mentors can submit the final project.", "danger")
        return redirect(url_for("home"))
    interns, tasks, _ = get_data()
    user = current_user()
    task = next((t for t in tasks if t.get("id") == task_id), None)
    if task is None or task.get("created_by_role") != "mentor":
        flash("Mentor subtask not found.", "danger")
        return redirect(url_for("mentor_dashboard"))
    assigned = set(task.get("assigned_intern_ids") or [task.get("intern_id")])
    if not mentor_intern_ids(user, interns).intersection(assigned):
        flash("You cannot submit a final project for this task.", "danger")
        return redirect(url_for("mentor_dashboard"))
    parent = parent_admin_task(task, tasks)
    if not parent:
        flash("The parent admin task could not be found.", "danger")
        return redirect(url_for("mentor_dashboard"))
    uploaded = save_upload(request.files.get("final_project_file"), PROJECT_UPLOAD_DIR, f"final_{parent.get('id', 'project')}")
    if not uploaded:
        flash("Choose the combined final ZIP file.", "danger")
    elif not uploaded["filename"].lower().endswith(".zip"):
        path = PROJECT_UPLOAD_DIR / uploaded["stored_name"]
        path.unlink(missing_ok=True)
        flash("Only .zip project files are accepted.", "danger")
    else:
        parent["final_project_file"] = uploaded
        parent["final_project_submitted_by"] = user.get("username", "Mentor")
        parent["final_project_submitted_at"] = notification_timestamp()
        save_json(TASKS_FILE, tasks)
        notify_users(admin_user_ids(), parent, user.get("username", "Mentor"), "Submitted the final project ZIP")
        flash("Final combined ZIP submitted to the admin successfully.", "success")
    return redirect(url_for("mentor_dashboard"))


@app.get("/tasks/<task_id>/project")
def download_project(task_id):
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    interns, tasks, _ = get_data()
    task = next((t for t in tasks if t.get("id") == task_id), None)
    if not task:
        flash("Task not found.", "danger")
        return redirect(url_for("home"))
    assigned = set(task.get("assigned_intern_ids") or [task.get("intern_id")])
    role = user.get("role")
    allowed = False
    file_record = None
    if role == "admin":
        allowed = True
        parent = parent_admin_task(task, tasks)
        file_record = (parent or task).get("final_project_file")
    elif role == "mentor" and mentor_intern_ids(user, interns).intersection(assigned):
        allowed = True
        file_record = task.get("intern_project_file") or task.get("project_file")
        if not file_record and task.get("created_by_role") == "admin":
            file_record = task.get("final_project_file")
    elif role == "intern" and user.get("intern_id") in assigned:
        allowed = True
        parent = parent_admin_task(task, tasks)
        file_record = parent.get("final_project_file") if parent else None
    if not allowed:
        flash("You do not have permission to download this project.", "danger")
        return redirect(url_for("home"))
    path = project_path(file_record)
    if not path:
        flash("No project file is available for your role yet.", "warning")
        return redirect(request.referrer or url_for("home"))
    return send_file(path, as_attachment=True, download_name=file_record.get("filename", path.name))


if __name__ == "__main__":
    app.run(debug=True)
