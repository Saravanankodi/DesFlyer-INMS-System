# Internship Tracker - Login and User Management

## Login
The login page accepts either the username or email address, plus the password. Select the correct role: Admin, Mentor, or Intern. The email/password must exist in Firebase Authentication, and the same account must also have an INMS user record in Firestore.

## Linking an existing Firebase account
Creating an account in Firebase Authentication alone does not grant INMS access. An operator with production Firebase Admin credentials must link it to an INMS role and Firestore user record:

1. Configure the project-root `.env` with the production Firebase project, Web API key, service-account credential path, and `FIREBASE_USE_EMULATORS=0`.
2. Ensure the account's role profile exists in Firestore first for mentor/intern accounts.
3. Run, for example:

   ```text
   python provision_firebase_user.py --email user@example.com --username user --role admin
   ```

   For a mentor or intern, also pass `--profile-id` with the existing Firestore profile ID. The command links an existing Auth account; it does not ask for or change its password. Do not assign the admin role unless authorized.
4. Restart the Flask app and sign in using the same email/password and selected role.

The provision command refuses to run when emulator mode is enabled, to avoid accidentally linking an account in the wrong Firebase project.

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
Passwords are stored only in Firebase Authentication. Firestore user documents must not contain passwords.


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
