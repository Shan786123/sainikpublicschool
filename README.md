# Sainik Public School — Full Stack Web Application

Python Flask + SQLite school management system.

## QUICK START (Local)

```bash
pip install flask
python run.py
# Open: http://localhost:5000
```

### Login Credentials

| Portal | URL | Username | Password |
|--------|-----|----------|----------|
| Admin Panel | /admin/login | admin | admin123 |
| Student | /student/login | STU001 | password123 |

---

## FEATURES

### Admin Panel
- Dashboard with live stats
- Students — Add / Edit / Delete (full profile fields)
- Staff — Add / Edit / Delete
- Marks (SGPA) — Semester marks, auto SGPA/CGPA in student portal
- Backlogs — Add, Clear, Reset
- Notices, Gallery, Admissions, Messages

### Student Portal
- Dashboard with quick links
- My Profile — full personal details
- My Results — SGPA/CGPA marksheet, printable
- Backlogs — view and apply for re-examination

---

## FREE HOSTING GUIDE

---

### OPTION 1: PythonAnywhere (Recommended — Always Free)

Site URL will be: yourusername.pythonanywhere.com

Step 1 — Create Account
- Go to https://www.pythonanywhere.com
- Click Pricing and Signup, then Create a Beginner account (FREE)
- Choose a username carefully — it becomes your URL

Step 2 — Upload Files
- Click Files tab at the top
- Click New directory and create a folder called sainik
- Upload app.py, run.py, requirements.txt into it
- Inside sainik, create a templates folder
- Upload all .html files from the templates folder into it
- FASTER: In Bash console, run: unzip sainik_school_fullstack.zip

Step 3 — Install Flask
- Click Consoles tab, then Bash
- Run: pip install flask --user

Step 4 — Create Web App
- Click Web tab, then Add a new web app
- Click Next, choose Flask, choose Python 3.10
- Set source code path to: /home/yourusername/sainik/app.py

Step 5 — Edit WSGI File
- In the Web tab, click on the WSGI configuration file link
- Delete everything and paste:

import sys
sys.path.insert(0, '/home/yourusername/sainik')
from app import app, init_db
init_db()
application = app

- Replace yourusername with your actual username
- Click Save

Step 6 — Reload
- Go back to Web tab
- Click the green Reload button
- Visit https://yourusername.pythonanywhere.com — done!

---

### OPTION 2: Render.com (Free — sleeps after 15 min)

Step 1 — Add Procfile
Create a file called Procfile (no extension) with content:
  web: python run.py

Step 2 — Update run.py for Render
Replace contents with:
  import os
  from app import app, init_db
  if __name__ == '__main__':
      init_db()
      port = int(os.environ.get('PORT', 5000))
      app.run(host='0.0.0.0', port=port)

Step 3 — Push to GitHub
- Create account at https://github.com
- New repository, upload all project files

Step 4 — Deploy on Render
- Create account at https://render.com
- Click New+ then Web Service
- Connect GitHub, select your repository
- Name: sainik-school
- Runtime: Python 3
- Build Command: pip install flask
- Start Command: python run.py
- Click Create Web Service
- Live at https://sainik-school.onrender.com in 2 minutes

---

### OPTION 3: Railway.app (Free $5 credit/month)

- Sign up at https://railway.app with GitHub
- New Project, Deploy from GitHub repo
- Select repository
- Add environment variable PORT = 5000
- Done, live in 2 minutes

---

## BEFORE GOING LIVE

Change the secret key in app.py line 16:
  app.secret_key = 'your-random-secret-string-here'

Change default passwords using the Edit feature in Admin panel.

---

## COMMON ISSUES

| Problem | Fix |
|---------|-----|
| ModuleNotFoundError: flask | Run: pip install flask |
| school.db not created | Run: python app.py once |
| Login not working | Roll no must be STU001 exactly, password: password123 |
| PythonAnywhere 500 error | Check WSGI file, username must match exactly |
| Render site slow first load | Free tier sleeps — takes 30 sec to wake up |

---

## PROJECT STRUCTURE

sainik/
- app.py                    Main Flask app
- run.py                    Server startup
- requirements.txt
- school.db                 Auto-created SQLite database
- templates/
  - base.html               Public layout
  - index.html              Homepage
  - result.html             Public result checker
  - student_login.html
  - student_portal.html     Dashboard
  - student_profile.html    Personal details
  - student_results.html    SGPA marksheet
  - student_backlogs.html   Backlog tracker
  - apply_backlog.html      Re-exam form
  - admin_base.html         Admin layout
  - admin_login.html
  - admin_dashboard.html
  - admin_students.html     With EDIT modal
  - admin_staff.html        With EDIT modal
  - admin_marks.html        SGPA marks entry
  - admin_backlogs.html
  - admin_results.html
  - admin_notices.html
  - admin_messages.html
  - admin_admissions.html
  - admin_gallery.html
