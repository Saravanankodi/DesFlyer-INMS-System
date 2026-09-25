# Internship Management & Task Tracking System

A web-based **Internship Management and Task Tracking System** developed using **Python Flask**. The system helps organizations manage interns, mentors, tasks, projects, progress, notifications, and reports through role-based dashboards.

## 🚀 Features

### 👨‍💼 Admin

* Admin dashboard with task and internship statistics
* Add, edit, and manage interns
* Add, edit, and manage mentors
* Assign mentors to interns
* Manage user accounts
* Create and assign internship tasks
* Set task priority, start date, and deadline
* Monitor overall task progress
* View and generate progress reports
* Manage uploaded project files

### 👨‍🏫 Mentor

* Mentor dashboard
* View assigned interns
* View Admin-assigned projects
* Assign subtasks to interns
* Monitor intern task progress
* Review intern project submissions
* Manage mentor-assigned tasks
* View progress reports

### 👨‍💻 Intern

* Intern dashboard
* View assigned Admin projects
* View assigned tasks
* Update task status
* Upload project files
* Track deadlines and task progress
* Receive notifications
* View personal progress information

## 🔄 Project Workflow

```text
                    ADMIN
                      │
          ┌───────────┴───────────┐
          │                       │
       Mentors                 Interns
          │                       │
          └───────────┬───────────┘
                      │
               Assign Project
                      │
                      ▼
                   MENTOR
                      │
              Assign Subtasks
                      │
                      ▼
                   INTERN
                      │
          ┌───────────┴───────────┐
          │                       │
       Update Status          Upload Work
          │                       │
          └───────────┬───────────┘
                      │
                      ▼
                  MENTOR
                      │
                  Review
                      │
                      ▼
               Progress Report
```

## 📌 Task Structure

Admin-created projects can act as parent tasks.

Example:

```text
DFPY01
│
├── DFPY01-01
├── DFPY01-02
└── DFPY01-03
```

Where:

* `DFPY01` → Parent/Admin project
* `DFPY01-01` → Mentor-assigned subtask
* `DFPY01-02` → Mentor-assigned subtask
* `DFPY01-03` → Mentor-assigned subtask

This structure keeps mentor subtasks connected to the original Admin project.

## 🎯 Task Priority

Tasks support three priority levels:

* 🔴 High
* 🟡 Medium
* 🟢 Low

## 📊 Task Status

The system tracks task progress using statuses such as:

* Not Started
* In Progress
* Completed
* Not Completed
* Overdue

## 🔔 Notifications

The system provides role-based notifications for relevant task activities, including:

* Task assignments
* Task updates
* Project submissions
* Status changes

## 📄 Progress Reports

The application provides progress-report functionality for monitoring internship work.

Reports can include:

* Intern information
* Department
* Assigned tasks
* Task status
* Progress
* Deadlines
* Internship information

PDF reports are generated using **ReportLab**.

## 📁 Project Structure

```text
Internship_Tracker/
│
├── app.py
├── internship_tracker.py
├── init_db.py
├── requirements.txt
│
├── users.json
├── interns.json
├── mentors.json
├── tasks.json
├── notifications.json
│
├── templates/
│   ├── login.html
│   ├── dashboard.html
│   ├── mentor_dashboard.html
│   ├── intern_dashboard.html
│   ├── interns.html
│   ├── mentors.html
│   ├── tasks.html
│   ├── assign_task.html
│   ├── task_detail.html
│   ├── report.html
│   └── ...
│
├── static/
│   ├── style.css
│   └── images/
│
├── uploads/
│   ├── documents/
│   ├── projects/
│   └── intern_files/
│
└── README.md
```

## 🛠️ Technologies Used

### Backend

* Python
* Flask
* ReportLab

### Frontend

* HTML5
* CSS3
* JavaScript
* Jinja2

### Storage

* JSON
* SQLite

### Development Tools

* Git
* GitHub
* VS Code

## ⚙️ Installation

### 1. Clone the Repository

```bash
git clone <repository-url>
cd Internship_Tracker
```

### 2. Create Virtual Environment

```bash
python -m venv .venv
```

### 3. Activate Virtual Environment

**Windows:**

```powershell
.venv\Scripts\activate
```

### 4. Install Dependencies

```bash
pip install -r requirements.txt
```

### 5. Run the Application

```bash
python app.py
```

Open your browser and visit:

```text
http://127.0.0.1:5000
```

## 🔐 User Roles

| Feature          | Admin | Mentor | Intern |
| ---------------- | :---: | :----: | :----: |
| Dashboard        |   ✅   |    ✅   |    ✅   |
| Manage Interns   |   ✅   |   👁️  |   👁️  |
| Manage Mentors   |   ✅   |    ❌   |    ❌   |
| Manage Users     |   ✅   |    ❌   |    ❌   |
| Create Projects  |   ✅   |    ❌   |    ❌   |
| Assign Tasks     |   ✅   |    ✅   |    ❌   |
| Update Tasks     |   ✅   |    ✅   |    ✅   |
| Upload Projects  |   ✅   | Review |    ✅   |
| Notifications    |   ✅   |    ✅   |    ✅   |
| Progress Reports |   ✅   |    ✅   |   Own  |

## 📎 File Uploads

The system supports uploading internship-related documents and project files.

Project files can be uploaded through the Intern dashboard and reviewed through the appropriate Admin/Mentor workflow.

## 🔒 Security

For production deployment, it is recommended to:

* Use environment variables for secret keys
* Use a production database
* Add stronger file validation
* Configure HTTPS
* Disable Flask debug mode
* Implement production-ready authentication
* Secure uploaded files

## 🔮 Future Enhancements

* Email notifications
* Real-time notifications
* Attendance management
* Mentor feedback system
* Internship evaluation system
* Advanced analytics
* MySQL/PostgreSQL support
* Cloud file storage
* REST API
* Docker deployment
* Mobile application

## 👨‍💻 Project Purpose

This project was developed to provide a centralized platform for managing the internship lifecycle, from **intern and mentor management to task assignment, project submission, progress tracking, and reporting**.

---

### Developed Using

**Python • Flask • HTML • CSS • JavaScript • JSON • SQLite • ReportLab**
