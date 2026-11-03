# College ERP

A functional Flask College ERP prototype with three roles: Admin, Staff, and Student.

## Quick start

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python app.py
```

Open http://127.0.0.1:5000. The first launch creates `instance/college_erp.db` and loads demo data.

Demo password for all accounts: `Demo@12345` (change this outside demo use).

| Role | Login |
|---|---|
| Admin | admin@example.com |
| Staff | staff@example.com |
| Student | student@example.com |

## MySQL

Create an empty database, set `DATABASE_URL` in `.env` to a SQLAlchemy MySQL URL shown in `.env.example`, then start the app. Tables and demo data are created automatically. See `database/schema.sql` for a portable starter schema.

## Included

The admin portal has dedicated, admin-only management pages for students, staff, courses, subjects, attendance, 20+20+10 assessment records, fees and payment history, and notices. The staff workspace includes assignment-scoped student records, attendance registers, assessment entry and CSV reports, bulk prediction, read-only admin notices, and profile/password management. Student and staff accounts are managed with hashed passwords; a password must be explicitly provided when an admin creates an account. Existing student course names, legacy subjects, marks, attendance, fees, and notice records are preserved when the catalog and management tables are initialized.

Role-protected dashboards, assigned-subject workflows, individual and bulk performance prediction, responsive searchable tables, and CSV reports remain available. Flask-WTF CSRF protection is enabled on forms.
