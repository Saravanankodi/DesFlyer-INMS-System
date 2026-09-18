import calendar
from io import BytesIO
from datetime import date
from uuid import uuid4
from xml.sax.saxutils import escape

from flask import Flask, flash, redirect, render_template, request, send_file, url_for
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from init_db import get_connection, initialize_database, migrate_legacy_json

app = Flask(__name__)
app.secret_key = "internship-tracker-development-key"

STATUSES = ("Pending", "In Progress", "Completed")
PRIORITIES = ("High", "Medium", "Low")


def calculate_end_date(joining_date, duration_months):
    joining = date.fromisoformat(joining_date)
    month_index = joining.month - 1 + int(duration_months)
    year = joining.year + month_index // 12
    month = month_index % 12 + 1
    day = min(joining.day, calendar.monthrange(year, month)[1])
    return date(year, month, day).isoformat()


def calculate_intern_dates(joining_date, duration_months):
    end_date = calculate_end_date(joining_date, duration_months)
    status = "Active Intern" if date.today().isoformat() <= end_date else "Past Employee"
    return end_date, status

def get_data():
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT id, joining_date, duration_months FROM interns WHERE duration_months > 0"
        ).fetchall()
        for row in rows:
            end_date, status = calculate_intern_dates(row["joining_date"], row["duration_months"])
            connection.execute(
                "UPDATE interns SET end_date = ?, employment_status = ? WHERE id = ?",
                (end_date, status, row["id"]),
            )
        interns = [dict(row) for row in connection.execute("SELECT * FROM interns ORDER BY id")]
        tasks = [dict(row) for row in connection.execute("SELECT * FROM tasks ORDER BY id")]
        member_rows = connection.execute(
            """SELECT task_members.task_id, task_members.intern_id, interns.name
               FROM task_members JOIN interns ON interns.id = task_members.intern_id
               ORDER BY interns.name"""
        ).fetchall()
        members_by_task = {}
        for row in member_rows:
            members_by_task.setdefault(row["task_id"], []).append(
                {"id": row["intern_id"], "name": row["name"]}
            )
        for task in tasks:
            members = members_by_task.get(task["id"], [])
            task["assigned_interns"] = members
            task["assigned_intern_ids"] = [member["id"] for member in members]
            task["assigned_names"] = [member["name"] for member in members]
        mentors = [dict(row) for row in connection.execute("SELECT * FROM mentors ORDER BY name")]
    return interns, tasks, mentors


initialize_database()
migrate_legacy_json()


def is_overdue(task):
    try:
        return task["status"] != "Completed" and date.fromisoformat(task["deadline"]) < date.today()
    except (KeyError, TypeError, ValueError):
        return False


def intern_summary(intern, tasks):
    assigned = [{**task, "overdue": is_overdue(task)} for task in tasks
                if intern["id"] in task.get("assigned_intern_ids", [task.get("intern_id")])]
    completed = sum(task.get("status") == "Completed" for task in assigned)
    return {**intern, "tasks": assigned, "total_tasks": len(assigned),
            "completed_tasks": completed,
            "pending_tasks": sum(task.get("status") == "Pending" for task in assigned),
            "in_progress_tasks": sum(task.get("status") == "In Progress" for task in assigned),
            "progress": round(completed / len(assigned) * 100, 1) if assigned else 0}


def decorate_tasks(tasks, interns):
    names = {intern["id"]: intern["name"] for intern in interns}
    decorated = []
    for task in tasks:
        assigned_ids = task.get("assigned_intern_ids") or [task.get("intern_id")]
        assigned_names = task.get("assigned_names") or [names.get(task.get("intern_id"), "Unknown intern")]
        decorated.append({**task, "intern_name": ", ".join(assigned_names),
                          "assigned_names": assigned_names,
                          "assigned_intern_ids": assigned_ids,
                          "overdue": is_overdue(task)})
    return decorated


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
    departments = {intern.get("department") for intern in interns if intern.get("department")}
    active_interns = sum(intern.get("employment_status") == "Active Intern" for intern in interns)
    return render_template("dashboard.html", interns=[intern_summary(i, tasks) for i in interns],
                           tasks=decorate_tasks(tasks, interns), total_interns=len(interns),
                           mentors=mentors, total_mentors=len(mentors),
                           total_tasks=len(tasks), completed=completed, pending=pending,
                           in_progress=in_progress, overdue=overdue,
                           active_interns=active_interns, past_employees=len(interns) - active_interns,
                           total_departments=len(departments),
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
                  ("id", "name", "email", "phone", "department", "joining_date", "duration_months")}
        intern["assigned_mentor"] = request.form.get("assigned_mentor", "").strip()
        try:
            duration_months = int(intern["duration_months"])
        except ValueError:
            duration_months = 0
        if not all(intern[field] for field in
               ("id", "name", "email", "phone", "department", "joining_date")) or duration_months <= 0:
            flash("Please complete every intern field.", "danger")
        elif any(item.get("id") == intern["id"] for item in interns):
            flash("That Intern ID is already in use.", "danger")
        else:
            end_date, employment_status = calculate_intern_dates(intern["joining_date"], duration_months)
            with get_connection() as connection:
                connection.execute(
                    """INSERT INTO interns
                       (id, name, email, phone, department, joining_date, duration_months,
                        end_date, employment_status, assigned_mentor)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    tuple(intern[field] for field in
                          ("id", "name", "email", "phone", "department", "joining_date"))
                    + (duration_months, end_date, employment_status, intern["assigned_mentor"]),
                )
            flash("Intern added successfully.", "success")
            return redirect(url_for("view_interns"))
    return render_template("add_intern.html", intern=None, mentors=mentors)


@app.post("/mentors/add")
def add_mentor():
    mentor_name = request.form.get("name", "").strip()
    _, _, mentors = get_data()
    if not mentor_name:
        flash("Enter a mentor name.", "danger")
    elif any(mentor.get("name", "").casefold() == mentor_name.casefold() for mentor in mentors):
        flash("That mentor already exists.", "danger")
    else:
        with get_connection() as connection:
            connection.execute("INSERT INTO mentors (id, name) VALUES (?, ?)",
                               (uuid4().hex[:10], mentor_name))
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
        values = [request.form.get(field, "").strip()
                  for field in ("name", "email", "phone", "department", "joining_date")]
        try:
            duration_months = int(request.form.get("duration_months", "0"))
        except ValueError:
            flash("Internship duration must be a positive number of months.", "danger")
            return render_template("add_intern.html", intern=intern, mentors=mentors)
        if duration_months <= 0:
            flash("Internship duration must be a positive number of months.", "danger")
            return render_template("add_intern.html", intern=intern, mentors=mentors)
        end_date, employment_status = calculate_intern_dates(values[-1], duration_months)
        values.extend((duration_months, end_date, employment_status))
        values.append(request.form.get("assigned_mentor", "").strip() or None)
        with get_connection() as connection:
            connection.execute(
                """UPDATE interns SET name = ?, email = ?, phone = ?, department = ?,
                   joining_date = ?, duration_months = ?, end_date = ?, employment_status = ?,
                   assigned_mentor = ? WHERE id = ?""",
                (*values, intern_id),
            )
        flash("Intern details updated.", "success")
        return redirect(url_for("view_interns"))
    return render_template("add_intern.html", intern=intern, mentors=mentors)


@app.post("/interns/<intern_id>/delete")
def delete_intern(intern_id):
    with get_connection() as connection:
        connection.execute("DELETE FROM interns WHERE id = ?", (intern_id,))
    flash("Intern and assigned tasks deleted.", "success")
    return redirect(url_for("view_interns"))


@app.route("/tasks")
def view_tasks():
    interns, tasks, _ = get_data()
    return render_template("tasks.html", tasks=decorate_tasks(tasks, interns))


@app.get("/tasks/<task_id>")
def view_task(task_id):
    interns, tasks, mentors = get_data()
    task = next((item for item in tasks if item.get("id") == task_id), None)
    if task is None:
        flash("Task not found.", "danger")
        return redirect(url_for("view_tasks"))

    intern_by_id = {intern["id"]: intern for intern in interns}
    mentor_names = {mentor["id"]: mentor["name"] for mentor in mentors}
    assigned_ids = task.get("assigned_intern_ids") or [task.get("intern_id")]
    assigned_interns = []
    for intern_id in assigned_ids:
        intern = intern_by_id.get(intern_id)
        if intern is not None:
            assigned_interns.append({
                **intern,
                "mentor_name": mentor_names.get(intern.get("assigned_mentor"), "Unassigned"),
            })

    return render_template(
        "task_detail.html",
        task=decorate_tasks([task], interns)[0],
        assigned_interns=assigned_interns,
    )


@app.route("/tasks/add", methods=["GET", "POST"])
def assign_task():
    interns, tasks, _ = get_data()
    departments = sorted({intern["department"] for intern in interns if intern.get("department")})
    active_interns = [intern for intern in interns if intern.get("employment_status") == "Active Intern"]
    if request.method == "POST":
        task_type = request.form.get("task_type", "Individual Work").strip()
        selected_ids = [item.strip() for item in request.form.getlist("selected_intern_ids") if item.strip()]
        intern_id = request.form.get("intern_id", "").strip()
        if task_type == "Individual Work":
            selected_ids = [intern_id]
        task = {"title": request.form.get("title", "").strip(),
                "description": request.form.get("description", "").strip(),
                "deadline": request.form.get("deadline", ""),
                "priority": request.form.get("priority", "Medium"),
                "status": request.form.get("status", "Pending")}
        valid_ids = {intern["id"] for intern in active_interns}
        if task_type not in ("Individual Work", "Team Work"):
            flash("Select a valid task type.", "danger")
        elif not task["title"] or not task["deadline"]:
            flash("Task title and deadline are required.", "danger")
        elif any(item not in valid_ids for item in selected_ids):
            flash("Only active interns can be assigned to tasks.", "danger")
        elif task_type == "Individual Work" and len(selected_ids) != 1:
            flash("Individual Work must have exactly one intern selected.", "danger")
        else:
            with get_connection() as connection:
                task_id = uuid4().hex[:10]
                connection.execute(
                    """INSERT INTO tasks
                       (id, intern_id, task_type, title, description, deadline, priority, status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (task_id, selected_ids[0], task_type, task["title"], task["description"],
                     task["deadline"], task["priority"], task["status"]),
                )
                connection.executemany(
                    "INSERT INTO task_members (task_id, intern_id) VALUES (?, ?)",
                    [(task_id, selected_id) for selected_id in selected_ids],
                )
            flash("Task assigned successfully.", "success")
            return redirect(url_for("view_tasks"))
    return render_template("assign_task.html", interns=active_interns, departments=departments, task=None,
                           priorities=PRIORITIES, statuses=STATUSES)


@app.route("/tasks/<task_id>/edit", methods=["GET", "POST"])
def edit_task(task_id):
    interns, tasks, _ = get_data()
    active_interns = [intern for intern in interns if intern.get("employment_status") == "Active Intern"]
    task = next((item for item in tasks if item.get("id") == task_id), None)
    if task is None:
        flash("Task not found.", "danger")
        return redirect(url_for("view_tasks"))
    if request.method == "POST":
        task_type = request.form.get("task_type", "Individual Work").strip()
        selected_ids = [item.strip() for item in request.form.getlist("selected_intern_ids") if item.strip()]
        if task_type == "Individual Work":
            selected_ids = [request.form.get("intern_id", "").strip()]
        values = [request.form.get(field, "").strip()
                  for field in ("title", "description", "deadline", "priority", "status")]
        valid_ids = {intern["id"] for intern in active_interns}
        if task_type not in ("Individual Work", "Team Work"):
            flash("Select a valid task type.", "danger")
        elif any(item not in valid_ids for item in selected_ids):
            flash("Only active interns can be assigned to tasks.", "danger")
        elif task_type == "Individual Work" and len(selected_ids) != 1:
            flash("Individual Work must have exactly one intern selected.", "danger")
        else:
            with get_connection() as connection:
                connection.execute(
                    """UPDATE tasks SET intern_id = ?, task_type = ?, title = ?, description = ?,
                       deadline = ?, priority = ?, status = ? WHERE id = ?""",
                    (selected_ids[0], task_type, *values, task_id),
                )
                connection.execute("DELETE FROM task_members WHERE task_id = ?", (task_id,))
                connection.executemany(
                    "INSERT INTO task_members (task_id, intern_id) VALUES (?, ?)",
                    [(task_id, selected_id) for selected_id in selected_ids],
                )
            flash("Task details updated.", "success")
            return redirect(url_for("view_tasks"))
    return render_template("assign_task.html", interns=active_interns, departments=sorted({intern["department"] for intern in interns}), task=task,
                           priorities=PRIORITIES, statuses=STATUSES)


@app.post("/tasks/<task_id>/delete")
def delete_task(task_id):
    with get_connection() as connection:
        connection.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    flash("Task deleted.", "success")
    return redirect(url_for("view_tasks"))


@app.route("/reports")
def reports():
    return render_template("report.html", interns=build_report_data())


def build_report_data():
    interns, tasks, mentors = get_data()
    mentor_names = {mentor["id"]: mentor["name"] for mentor in mentors}
    enriched = [{**intern, "mentor_name": mentor_names.get(intern.get("assigned_mentor"), "Unassigned")}
                for intern in interns]
    return [intern_summary(i, decorate_tasks(tasks, interns)) for i in enriched]


@app.get("/download-report")
def download_report():
    report_interns = build_report_data()
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=14 * mm,
        leftMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title="Progress Reports",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle", parent=styles["Title"], alignment=TA_CENTER, spaceAfter=10
    )
    heading_style = ParagraphStyle(
        "InternHeading", parent=styles["Heading2"], spaceBefore=12, spaceAfter=4
    )
    body_style = ParagraphStyle("ReportBody", parent=styles["BodyText"], fontSize=9, leading=11)
    small_style = ParagraphStyle("ReportSmall", parent=body_style, fontSize=8, leading=10)
    story = [Paragraph("Progress reports", title_style)]

    for intern in report_interns:
        story.extend([
            Paragraph(escape(intern["name"]), heading_style),
            Paragraph(
                escape(f'{intern["department"]} · {intern["email"]} · ID {intern["id"]}'),
                body_style,
            ),
            Paragraph(
                escape(f'Mentor: {intern["mentor_name"]}'), body_style
            ),
            Paragraph(
                escape(
                    f'{intern["employment_status"]} · {intern["duration_months"]} months · '
                    f'Ends {intern["end_date"] or "Not set"}'
                ),
                body_style,
            ),
            Paragraph(escape(f'Progress: {intern["progress"]}%'), body_style),
            Paragraph(
                escape(
                    f'Total tasks: {intern["total_tasks"]} · '
                    f'Completed: {intern["completed_tasks"]} · '
                    f'In progress: {intern["in_progress_tasks"]}'
                ),
                body_style,
            ),
            Spacer(1, 4),
        ])

        task_rows = [[
            Paragraph("Assigned task", small_style),
            Paragraph("Type / team", small_style),
            Paragraph("Deadline", small_style),
            Paragraph("Status", small_style),
        ]]
        for task in intern["tasks"]:
            task_rows.append([
                Paragraph(
                    escape(f'{task["title"]}\n{task["description"]}'), small_style
                ),
                Paragraph(
                    escape(f'{task["task_type"]}\n{task["intern_name"]}'), small_style
                ),
                Paragraph(escape(task["deadline"]), small_style),
                Paragraph(escape(task["status"]), small_style),
            ])
        if len(task_rows) == 1:
            task_rows.append([Paragraph("No tasks assigned.", small_style), "", "", ""])
        task_table = Table(task_rows, colWidths=[78 * mm, 58 * mm, 28 * mm, 28 * mm], repeatRows=1)
        task_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f5")),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d9e0e5")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(task_table)

    if not report_interns:
        story.append(Paragraph("Add an intern to generate a progress report.", body_style))
    document.build(story)
    buffer.seek(0)
    return send_file(
        buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="progress-reports.pdf",
    )


if __name__ == "__main__":
    app.run(debug=True)