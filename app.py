import json
from datetime import date
from pathlib import Path
from uuid import uuid4

from flask import Flask, flash, redirect, render_template, request, url_for

app = Flask(__name__)
app.secret_key = "internship-tracker-development-key"

BASE_DIR = Path(__file__).resolve().parent
INTERNS_FILE = BASE_DIR / "interns.json"
TASKS_FILE = BASE_DIR / "tasks.json"
MENTORS_FILE = BASE_DIR / "mentors.json"
STATUSES = ("Pending", "In Progress", "Completed")
PRIORITIES = ("High", "Medium", "Low")


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


def get_data():
    return load_json(INTERNS_FILE), load_json(TASKS_FILE), load_json(MENTORS_FILE)


def is_overdue(task):
    try:
        return task["status"] != "Completed" and date.fromisoformat(task["deadline"]) < date.today()
    except (KeyError, TypeError, ValueError):
        return False


def intern_summary(intern, tasks):
    assigned = [{**task, "overdue": is_overdue(task)} for task in tasks
                if task.get("intern_id") == intern["id"]]
    completed = sum(task.get("status") == "Completed" for task in assigned)
    return {**intern, "tasks": assigned, "total_tasks": len(assigned),
            "completed_tasks": completed,
            "pending_tasks": sum(task.get("status") == "Pending" for task in assigned),
            "in_progress_tasks": sum(task.get("status") == "In Progress" for task in assigned),
            "progress": round(completed / len(assigned) * 100, 1) if assigned else 0}


def decorate_tasks(tasks, interns):
    names = {intern["id"]: intern["name"] for intern in interns}
    return [{**task, "intern_name": names.get(task.get("intern_id"), "Unknown intern"),
             "overdue": is_overdue(task)} for task in tasks]


@app.context_processor
def navigation_data():
    return {"current_year": date.today().year}


@app.route("/")
def dashboard():
    interns, tasks, mentors = get_data()
    completed = sum(task.get("status") == "Completed" for task in tasks)
    pending = sum(task.get("status") == "Pending" for task in tasks)
    in_progress = sum(task.get("status") == "In Progress" for task in tasks)
    overdue = sum(is_overdue(task) for task in tasks)
    return render_template("dashboard.html", interns=[intern_summary(i, tasks) for i in interns],
                           tasks=decorate_tasks(tasks, interns), total_interns=len(interns),
                           mentors=mentors, total_mentors=len(mentors),
                           total_tasks=len(tasks), completed=completed, pending=pending,
                           in_progress=in_progress, overdue=overdue,
                           progress=round(completed / len(tasks) * 100, 1) if tasks else 0)


@app.route("/interns")
def view_interns():
    interns, tasks, mentors = get_data()
    mentor_names = {mentor["id"]: mentor["name"] for mentor in mentors}
    enriched = [{**intern, "mentor_name": mentor_names.get(intern.get("assigned_mentor"), "Unassigned")}
                for intern in interns]
    return render_template("interns.html", interns=[intern_summary(i, tasks) for i in enriched])


@app.route("/interns/add", methods=["GET", "POST"])
def add_intern():
    interns, _, mentors = get_data()
    if request.method == "POST":
        intern = {field: request.form.get(field, "").strip() for field in
                  ("id", "name", "email", "phone", "department", "joining_date")}
        intern["assigned_mentor"] = request.form.get("assigned_mentor", "").strip()
        if not all(intern.values()):
            flash("Please complete every intern field.", "danger")
        elif any(item.get("id") == intern["id"] for item in interns):
            flash("That Intern ID is already in use.", "danger")
        else:
            interns.append(intern)
            save_json(INTERNS_FILE, interns)
            flash("Intern added successfully.", "success")
            return redirect(url_for("view_interns"))
    return render_template("add_intern.html", intern=None, mentors=mentors)


@app.post("/mentors/add")
def add_mentor():
    mentor_name = request.form.get("name", "").strip()
    mentors = load_json(MENTORS_FILE)
    if not mentor_name:
        flash("Enter a mentor name.", "danger")
    elif any(mentor.get("name", "").casefold() == mentor_name.casefold() for mentor in mentors):
        flash("That mentor already exists.", "danger")
    else:
        mentors.append({"id": uuid4().hex[:10], "name": mentor_name})
        save_json(MENTORS_FILE, mentors)
        flash("Mentor added successfully.", "success")
    return redirect(url_for("dashboard"))


@app.route("/interns/<intern_id>/edit", methods=["GET", "POST"])
def edit_intern(intern_id):
    interns, _, mentors = get_data()
    intern = next((item for item in interns if item.get("id") == intern_id), None)
    if intern is None:
        flash("Intern not found.", "danger")
        return redirect(url_for("view_interns"))
    if request.method == "POST":
        for field in ("name", "email", "phone", "department", "joining_date"):
            intern[field] = request.form.get(field, "").strip()
        intern["assigned_mentor"] = request.form.get("assigned_mentor", "").strip()
        save_json(INTERNS_FILE, interns)
        flash("Intern details updated.", "success")
        return redirect(url_for("view_interns"))
    return render_template("add_intern.html", intern=intern, mentors=mentors)


@app.post("/interns/<intern_id>/delete")
def delete_intern(intern_id):
    interns, tasks, _ = get_data()
    save_json(INTERNS_FILE, [item for item in interns if item.get("id") != intern_id])
    save_json(TASKS_FILE, [task for task in tasks if task.get("intern_id") != intern_id])
    flash("Intern and assigned tasks deleted.", "success")
    return redirect(url_for("view_interns"))


@app.route("/tasks")
def view_tasks():
    interns, tasks, _ = get_data()
    return render_template("tasks.html", tasks=decorate_tasks(tasks, interns))


@app.route("/tasks/add", methods=["GET", "POST"])
def assign_task():
    interns, tasks, _ = get_data()
    if request.method == "POST":
        task = {"id": uuid4().hex[:10], "intern_id": request.form.get("intern_id", ""),
                "title": request.form.get("title", "").strip(),
                "description": request.form.get("description", "").strip(),
                "deadline": request.form.get("deadline", ""),
                "priority": request.form.get("priority", "Medium"),
                "status": request.form.get("status", "Pending")}
        if not task["intern_id"] or not task["title"] or not task["deadline"]:
            flash("Intern, title, and deadline are required.", "danger")
        elif task["intern_id"] not in {item.get("id") for item in interns}:
            flash("Select a valid intern.", "danger")
        else:
            tasks.append(task)
            save_json(TASKS_FILE, tasks)
            flash("Task assigned successfully.", "success")
            return redirect(url_for("view_tasks"))
    return render_template("assign_task.html", interns=interns, task=None,
                           priorities=PRIORITIES, statuses=STATUSES)


@app.route("/tasks/<task_id>/edit", methods=["GET", "POST"])
def edit_task(task_id):
    interns, tasks, _ = get_data()
    task = next((item for item in tasks if item.get("id") == task_id), None)
    if task is None:
        flash("Task not found.", "danger")
        return redirect(url_for("view_tasks"))
    if request.method == "POST":
        for field in ("intern_id", "title", "description", "deadline", "priority", "status"):
            task[field] = request.form.get(field, "").strip()
        save_json(TASKS_FILE, tasks)
        flash("Task details updated.", "success")
        return redirect(url_for("view_tasks"))
    return render_template("assign_task.html", interns=interns, task=task,
                           priorities=PRIORITIES, statuses=STATUSES)


@app.post("/tasks/<task_id>/delete")
def delete_task(task_id):
    _, tasks, _ = get_data()
    save_json(TASKS_FILE, [task for task in tasks if task.get("id") != task_id])
    flash("Task deleted.", "success")
    return redirect(url_for("view_tasks"))


@app.route("/reports")
def reports():
    interns, tasks, mentors = get_data()
    mentor_names = {mentor["id"]: mentor["name"] for mentor in mentors}
    enriched = [{**intern, "mentor_name": mentor_names.get(intern.get("assigned_mentor"), "Unassigned")}
                for intern in interns]
    return render_template("report.html", interns=[intern_summary(i, tasks) for i in enriched])


if __name__ == "__main__":
    app.run(debug=True)