# Internship Tracker - Login and User Management

## Login
The login page accepts either the username or email address, plus the password. Select the correct role: Admin, Mentor, or Intern.

## Admin user management
After logging in as an admin, open **Users** in the navigation bar or visit `/admin/users`.

The admin can:
- Create login accounts
- Edit username and email
- Change role
- Link a Mentor account to a mentor profile
- Link an Intern account to an intern profile
- Change a user's password
- Delete other user accounts

The currently logged-in admin account cannot delete itself.

## Password storage
Passwords are stored as PBKDF2-SHA256 hashes in `users.json`, not as plain text.


## Recent UI and workflow updates

- Login alerts automatically disappear after 3 seconds.
- Fixed/sticky navigation is used across authenticated pages.
- Admin has a dedicated **Mentors** navigation page; mentor creation includes ID, name, email, phone, department, and document upload.
- Intern creation/editing includes a department dropdown, ending date, mentor assignment, and document upload.
- Intern and task tables use their own scroll areas so long tables do not force the whole page to scroll.
- Admin intern listing sorts active interns before past interns.
- Progress reports support name search, department filtering, Intern/Mentor filtering, and individual PDF downloads.
- Tasks have automatic Task IDs, departments, and department-based intern filtering.
- Mentors choose an admin-created project when assigning work; the selected project supplies the task title.
- Interns can upload a project `.zip` file for each assigned task and download the submitted file.
