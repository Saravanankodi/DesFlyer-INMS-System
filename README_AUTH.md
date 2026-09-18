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

## Forgot password
`/forgot-password` lets a user reset their password using their username/email and a new password. This is suitable for the local JSON-based internship project. A production system should send a verified password-reset link by email instead.

## Password storage
Passwords are stored as PBKDF2-SHA256 hashes in `users.json`, not as plain text.
