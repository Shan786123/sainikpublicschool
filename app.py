"""
Sainik Public School - Full Stack Web Application
Backend: Flask (Python) + SQLite
New features (ported from PHP reference files):
  - personal_details.php  → /student/profile  (full profile: enrollment_no, gender, course, DOB, photo)
  - view_backlogs.php     → /student/backlogs  (Pending/Applied/Cleared + apply for re-exam)
  - view_results.php      → /student/results   (SGPA per semester, CGPA, grade points, printable marksheet)
"""

from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3, hashlib, os, uuid, urllib.request, urllib.parse, json
from werkzeug.utils import secure_filename
from datetime import datetime, date
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'xK9#mP2$qL8nR5@vT3wY7jZ1')

# Register image_url as a Jinja2 template filter
@app.template_filter('imgurl')
def imgurl_filter(value, category='students'):
    return image_url(value, category)
DB = os.path.join(os.path.dirname(__file__), 'school.db')

# ── UPLOAD CONFIG ──────────────────────────
ALLOWED_EXT = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5 MB max

# Local fallback folders (used when Cloudinary is not configured)
UPLOAD_FOLDER   = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
STUDENT_UPLOADS = os.path.join(UPLOAD_FOLDER, 'students')
STAFF_UPLOADS   = os.path.join(UPLOAD_FOLDER, 'staff')
GALLERY_UPLOADS = os.path.join(UPLOAD_FOLDER, 'gallery')
os.makedirs(STUDENT_UPLOADS, exist_ok=True)
os.makedirs(STAFF_UPLOADS,   exist_ok=True)
os.makedirs(GALLERY_UPLOADS, exist_ok=True)

# ── CLOUDINARY SETUP ───────────────────────
# _CLOUDINARY_URL = os.environ.get('CLOUDINARY_URL', '')
# USE_CLOUDINARY  = bool(_CLOUDINARY_URL)
# if USE_CLOUDINARY:
#     import cloudinary, cloudinary.uploader
#     cloudinary.config(cloudinary_url=_CLOUDINARY_URL)
_CLOUDINARY_URL = os.environ.get('CLOUDINARY_URL', '')
USE_CLOUDINARY  = bool(_CLOUDINARY_URL) and _CLOUDINARY_URL.startswith('cloudinary://')
if USE_CLOUDINARY:
    import cloudinary, cloudinary.uploader
    cloudinary.config(cloudinary_url=_CLOUDINARY_URL)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXT

def save_upload(file_obj, folder, folder_name='general'):
    if not file_obj or file_obj.filename == '':
        return None
    if not allowed_file(file_obj.filename):
        return None
    if USE_CLOUDINARY:
        try:
            result = cloudinary.uploader.upload(
                file_obj,
                folder=f'sainik_school/{folder_name}',
                resource_type='image',
                transformation=[{'quality': 'auto', 'fetch_format': 'auto'}]
            )
            return result['secure_url']
        except Exception as e:
            print(f'Cloudinary upload error: {e}')
            return None
    else:
        ext      = file_obj.filename.rsplit('.', 1)[1].lower()
        filename = uuid.uuid4().hex + '.' + ext
        file_obj.save(os.path.join(folder, filename))
        return filename

def delete_old_image(value):
    if not value or value == 'default.png':
        return
    if USE_CLOUDINARY and value.startswith('http'):
        try:
            parts = value.split('/upload/')
            if len(parts) == 2:
                public_id = parts[1].rsplit('.', 1)[0]
                cloudinary.uploader.destroy(public_id)
        except Exception:
            pass

def image_url(value, category='students'):
    if not value or value == 'default.png':
        return None
    if value.startswith('http'):
        return value
    return f'/static/uploads/{category}/{value}'

# ── CAPTCHA ────────────────────────────────
def verify_captcha(token):
    """Verify Cloudflare Turnstile token. Returns True if valid or if not configured (local dev)."""
    secret = os.environ.get('CF_TURNSTILE_SECRET_KEY', '')
    if not secret:
        return True  # Skip in local development
    if not token:
        return False
    try:
        data = urllib.parse.urlencode({
            'secret': secret,
            'response': token
        }).encode()
        req = urllib.request.Request(
            'https://challenges.cloudflare.com/turnstile/v0/siteverify',
            data=data
        )
        with urllib.request.urlopen(req, timeout=5) as res:
            result = json.loads(res.read())
            return result.get('success', False)
    except Exception:
        return False

# ── DB HELPERS ────────────────────────────
def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

# ── GRADE / SGPA HELPERS ──────────────────
def calculate_grade(obtained, total):
    if total == 0: return 'N/A'
    p = (obtained / total) * 100
    if p >= 90: return 'A+'
    if p >= 80: return 'A'
    if p >= 70: return 'B+'
    if p >= 60: return 'B'
    if p >= 50: return 'C'
    if p >= 40: return 'D'
    return 'F'

def get_grade_points(grade):
    return {'A+':10,'A':9,'B+':8,'B':7,'C':6,'D':5}.get(grade, 0)

def calculate_percentage(marks_list):
    tc = tw = 0
    for m in marks_list:
        g  = calculate_grade(m['marks_obtained'], m['total_marks'])
        gp = get_grade_points(g)
        tc += m['credits']
        tw += gp * m['credits']
    tot_obt = sum(m['marks_obtained'] for m in marks_list)
    tot_max = sum(m['total_marks']    for m in marks_list)
    return '0.00' if tot_max == 0 else '{:.1f}'.format((tot_obt / tot_max) * 100)

def calculate_overall_result(marks_list):
    for m in marks_list:
        if calculate_grade(m['marks_obtained'], m['total_marks']) == 'F':
            return 'Failed'
    return 'Passed'

def calculate_overall_pct(pct_history):
    if not pct_history: return '0.0'
    vals = [float(v) for v in pct_history.values()]
    return '{:.1f}'.format(sum(vals) / len(vals))

# ── DB INIT ───────────────────────────────
def init_db():
    db = get_db(); c = db.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS admins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
        name TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')

    c.execute('''CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        roll_no TEXT UNIQUE NOT NULL,
        enrollment_no TEXT,
        name TEXT NOT NULL,
        father_name TEXT, mother_name TEXT,
        gender TEXT DEFAULT 'Male',
        course TEXT DEFAULT 'General',
        class_name TEXT NOT NULL,
        section TEXT DEFAULT 'A',
        dob TEXT, address TEXT, phone TEXT, email TEXT,
        password TEXT NOT NULL,
        admission_date TEXT,
        profile_image TEXT DEFAULT 'default.png',
        status TEXT DEFAULT 'active',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')

    c.execute('''CREATE TABLE IF NOT EXISTS staff (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        emp_id TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
        designation TEXT, subject TEXT, qualification TEXT,
        phone TEXT, email TEXT, joining_date TEXT,
        profile_image TEXT DEFAULT 'default.png',
        status TEXT DEFAULT 'active',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')

    c.execute('''CREATE TABLE IF NOT EXISTS notices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL, content TEXT NOT NULL,
        category TEXT DEFAULT 'General',
        is_important INTEGER DEFAULT 0,
        published_date TEXT DEFAULT CURRENT_TIMESTAMP,
        created_by TEXT, status TEXT DEFAULT 'active')''')

    c.execute('''CREATE TABLE IF NOT EXISTS marks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        roll_no TEXT NOT NULL, student_name TEXT NOT NULL, class_name TEXT NOT NULL,
        subject_code TEXT, subject_name TEXT NOT NULL,
        credits INTEGER DEFAULT 4,
        marks_obtained INTEGER NOT NULL, total_marks INTEGER DEFAULT 100,
        grade TEXT, semester INTEGER NOT NULL,
        exam_type TEXT NOT NULL, session TEXT NOT NULL,
        publication_date TEXT DEFAULT CURRENT_TIMESTAMP,
        is_published INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')

    c.execute('''CREATE TABLE IF NOT EXISTS results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        roll_no TEXT NOT NULL, student_name TEXT NOT NULL, class_name TEXT NOT NULL,
        exam_type TEXT NOT NULL, session TEXT NOT NULL,
        subject TEXT NOT NULL, max_marks INTEGER DEFAULT 100,
        obtained_marks INTEGER NOT NULL, grade TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')

    c.execute('''CREATE TABLE IF NOT EXISTS backlogs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        roll_no TEXT NOT NULL, student_name TEXT NOT NULL,
        subject_code TEXT, subject_name TEXT NOT NULL,
        semester INTEGER NOT NULL,
        status TEXT DEFAULT 'Pending',
        applied_date TEXT, cleared_date TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')

    c.execute('''CREATE TABLE IF NOT EXISTS contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL, phone TEXT, email TEXT,
        subject TEXT, message TEXT NOT NULL,
        status TEXT DEFAULT 'unread',
        received_at TEXT DEFAULT CURRENT_TIMESTAMP)''')

    c.execute('''CREATE TABLE IF NOT EXISTS gallery (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL, description TEXT,
        image TEXT DEFAULT NULL, category TEXT DEFAULT 'General',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')

    c.execute('''CREATE TABLE IF NOT EXISTS admissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_name TEXT NOT NULL, father_name TEXT,
        phone TEXT NOT NULL, seeking_class TEXT,
        status TEXT DEFAULT 'pending',
        received_at TEXT DEFAULT CURRENT_TIMESTAMP)''')

    db.commit()

    for migration in [
        "ALTER TABLE staff ADD COLUMN profile_image TEXT DEFAULT 'default.png'",
        "ALTER TABLE gallery ADD COLUMN image TEXT DEFAULT NULL",
        "ALTER TABLE gallery DROP COLUMN emoji",
    ]:
        try: c.execute(migration); db.commit()
        except: pass

    # ── SEED ──
    c.execute("SELECT id FROM admins WHERE username='admin'")
    if not c.fetchone():
        c.execute("INSERT INTO admins (username,password,name) VALUES (?,?,?)",
                  ('admin', hash_password(os.environ.get('ADMIN_PASSWORD', 'admin123')), 'Super Admin'))

    c.execute("SELECT id FROM staff LIMIT 1")
    if not c.fetchone():
        for s in [
            ('EMP001','Dr. Ramesh Kumar','Principal','Administration','M.Ed., Ph.D.','9119673130','principal@sainik.in'),
            ('EMP002','Mrs. Sunita Pandey','Vice Principal','English','M.A., B.Ed.','9876543210','sunita@sainik.in'),
            ('EMP003','Mr. Anil Verma','Senior Teacher','Physics','M.Sc., B.Ed.','9876543211','anil@sainik.in'),
            ('EMP004','Mrs. Priya Singh','Senior Teacher','Chemistry','M.Sc., B.Ed.','9876543212','priya@sainik.in'),
            ('EMP005','Mr. Mohan Kumar','Teacher','History','M.A., B.Ed.','9876543213','mohan@sainik.in'),
            ('EMP006','Mrs. Neha Gupta','Teacher','Hindi','M.A., B.Ed.','9876543214','neha@sainik.in'),
            ('EMP007','Mr. Rajesh Mishra','Teacher','Commerce','M.Com., B.Ed.','9876543215','rajesh@sainik.in'),
            ('EMP008','Mrs. Anita Tiwari','Primary Teacher','EVS & Art','B.Ed.','9876543216','anita@sainik.in'),
        ]:
            c.execute('''INSERT OR IGNORE INTO staff
                (emp_id,name,designation,subject,qualification,phone,email,joining_date)
                VALUES (?,?,?,?,?,?,?,?)''', (*s,'2020-01-01'))

    c.execute("SELECT id FROM notices LIMIT 1")
    if not c.fetchone():
        for n in [
            ('Admissions Open 2025-26','Admissions open for Nursery to Class XII.','Admission',1),
            ('Annual Sports Day','Sports Day on 20 February 2025.','Event',1),
            ('Board Exam Fee','Fee submission last date: 31 January 2025.','Exam',0),
            ('Republic Day Celebration','26 January in proper uniform.','Event',0),
            ('Half-Yearly Results','Results on 10 January 2025.','Exam',0),
            ('Winter Vacation','Closed 25 Dec – 5 Jan. Reopens 6 Jan.','Holiday',0),
        ]:
            c.execute("INSERT INTO notices (title,content,category,is_important,created_by) VALUES (?,?,?,?,'Admin')", n)

    c.execute("SELECT id FROM students LIMIT 1")
    if not c.fetchone():
        for s in [
            ('STU001','ENR2024001','Rahul Sharma','Rajesh Sharma','Sunita Sharma','Male','Science','Class X','A','2008-05-15','Kanpur, U.P.','9876500001','rahul@email.com'),
            ('STU002','ENR2024002','Priya Verma','Anil Verma','Meena Verma','Female','Science','Class XII','B','2006-03-22','Kanpur, U.P.','9876500002','priya@email.com'),
            ('STU003','ENR2024003','Amit Kumar','Suresh Kumar','Rekha Kumar','Male','Commerce','Class IX','A','2009-08-10','Kanpur, U.P.','9876500003','amit@email.com'),
        ]:
            c.execute('''INSERT OR IGNORE INTO students
                (roll_no,enrollment_no,name,father_name,mother_name,gender,course,class_name,section,dob,address,phone,email,password,admission_date)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (*s, hash_password('password123'),'2020-04-01'))

    c.execute("SELECT id FROM marks LIMIT 1")
    if not c.fetchone():
        marks_seed = [
            ('STU001','Rahul Sharma','Class X','MTH101','Mathematics',4,85,100,1,'Half-Yearly','2024-25','2024-11-15'),
            ('STU001','Rahul Sharma','Class X','SCI102','Science',4,78,100,1,'Half-Yearly','2024-25','2024-11-15'),
            ('STU001','Rahul Sharma','Class X','ENG103','English',3,88,100,1,'Half-Yearly','2024-25','2024-11-15'),
            ('STU001','Rahul Sharma','Class X','HIN104','Hindi',3,82,100,1,'Half-Yearly','2024-25','2024-11-15'),
            ('STU001','Rahul Sharma','Class X','SST105','Social Science',4,75,100,1,'Half-Yearly','2024-25','2024-11-15'),
            ('STU001','Rahul Sharma','Class X','MTH201','Mathematics II',4,90,100,2,'Annual','2024-25','2025-03-20'),
            ('STU001','Rahul Sharma','Class X','SCI202','Science II',4,83,100,2,'Annual','2024-25','2025-03-20'),
            ('STU001','Rahul Sharma','Class X','ENG203','English II',3,91,100,2,'Annual','2024-25','2025-03-20'),
            ('STU001','Rahul Sharma','Class X','HIN204','Hindi II',3,79,100,2,'Annual','2024-25','2025-03-20'),
            ('STU001','Rahul Sharma','Class X','SST205','Social Science II',4,86,100,2,'Annual','2024-25','2025-03-20'),
            ('STU002','Priya Verma','Class XII','PHY101','Physics',4,91,100,1,'Half-Yearly','2024-25','2024-11-15'),
            ('STU002','Priya Verma','Class XII','CHE102','Chemistry',4,87,100,1,'Half-Yearly','2024-25','2024-11-15'),
            ('STU002','Priya Verma','Class XII','MTH103','Mathematics',4,93,100,1,'Half-Yearly','2024-25','2024-11-15'),
            ('STU002','Priya Verma','Class XII','ENG104','English',3,85,100,1,'Half-Yearly','2024-25','2024-11-15'),
        ]
        for m in marks_seed:
            g = calculate_grade(m[6], m[7])
            c.execute('''INSERT INTO marks
                (roll_no,student_name,class_name,subject_code,subject_name,credits,marks_obtained,total_marks,
                 semester,exam_type,session,publication_date,is_published,grade)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,?)''', (*m, g))

    c.execute("SELECT id FROM results LIMIT 1")
    if not c.fetchone():
        for r in [
            ('STU001','Rahul Sharma','Class X','Half-Yearly','2024-25','Mathematics',100,85,'A'),
            ('STU001','Rahul Sharma','Class X','Half-Yearly','2024-25','Science',100,78,'B+'),
            ('STU001','Rahul Sharma','Class X','Half-Yearly','2024-25','English',100,88,'A'),
            ('STU001','Rahul Sharma','Class X','Half-Yearly','2024-25','Hindi',100,82,'A'),
            ('STU001','Rahul Sharma','Class X','Half-Yearly','2024-25','Social Science',100,75,'B+'),
            ('STU002','Priya Verma','Class XII','Half-Yearly','2024-25','Physics',100,91,'A+'),
            ('STU002','Priya Verma','Class XII','Half-Yearly','2024-25','Chemistry',100,87,'A'),
            ('STU002','Priya Verma','Class XII','Half-Yearly','2024-25','Mathematics',100,93,'A+'),
        ]:
            c.execute('''INSERT INTO results
                (roll_no,student_name,class_name,exam_type,session,subject,max_marks,obtained_marks,grade)
                VALUES (?,?,?,?,?,?,?,?,?)''', r)

    c.execute("SELECT id FROM backlogs LIMIT 1")
    if not c.fetchone():
        for b in [
            ('STU001','Rahul Sharma','SST105','Social Science',1,'Pending'),
            ('STU001','Rahul Sharma','HIN104','Hindi',1,'Applied'),
            ('STU002','Priya Verma','CHE102','Chemistry',1,'Cleared'),
        ]:
            c.execute('''INSERT INTO backlogs
                (roll_no,student_name,subject_code,subject_name,semester,status) VALUES (?,?,?,?,?,?)''', b)

    c.execute("SELECT id FROM gallery LIMIT 1")
    if not c.fetchone():
        for g in [
            ('Annual Convocation 2024','Graduation ceremony for Class XII','Events'),
            ('Sports Day 2024','Annual sports day celebrations','Sports'),
            ('Science Exhibition','Students showcase science projects','Academics'),
            ('Cultural Program','Annual cultural fest performance','Events'),
            ('Art Exhibition','Student artwork display','Arts'),
            ('Library','Our well-stocked school library','Facilities'),
            ('Award Ceremony','Inter-school award winners','Achievements'),
            ('Republic Day','Republic Day celebration on campus','Events'),
        ]:
            c.execute("INSERT INTO gallery (title,description,category) VALUES (?,?,?)", g)

    db.commit(); db.close()

# ── AUTH DECORATORS ───────────────────────
def admin_required(f):
    @wraps(f)
    def d(*a,**kw):
        if 'admin_id' not in session:
            flash('Please login as admin.','error')
            return redirect(url_for('admin_login'))
        return f(*a,**kw)
    return d

def student_required(f):
    @wraps(f)
    def d(*a,**kw):
        if 'student_id' not in session:
            flash('Please login first.','error')
            return redirect(url_for('student_login'))
        return f(*a,**kw)
    return d

# ── PUBLIC ROUTES ─────────────────────────
@app.route('/')
def index():
    db = get_db()
    notices   = db.execute("SELECT * FROM notices WHERE status='active' ORDER BY published_date DESC LIMIT 7").fetchall()
    staff     = db.execute("SELECT * FROM staff WHERE status='active' ORDER BY id").fetchall()
    gallery   = db.execute("SELECT * FROM gallery ORDER BY id").fetchall()
    principal = db.execute("SELECT * FROM staff WHERE designation='Principal' AND status='active' LIMIT 1").fetchone()
    manager   = db.execute("SELECT * FROM staff WHERE designation='Manager' AND status='active' LIMIT 1").fetchone()
    stats     = {
        'students': db.execute("SELECT COUNT(*) FROM students WHERE status='active'").fetchone()[0],
        'staff':    db.execute("SELECT COUNT(*) FROM staff   WHERE status='active'").fetchone()[0],
        'notices':  db.execute("SELECT COUNT(*) FROM notices WHERE status='active'").fetchone()[0],
    }
    db.close()
    return render_template('index.html', notices=notices, staff=staff, gallery=gallery, stats=stats, principal=principal, manager=manager)

@app.route('/contact', methods=['POST'])
def contact():
    db = get_db()
    db.execute("INSERT INTO contacts (name,phone,email,subject,message) VALUES (?,?,?,?,?)",
        (request.form.get('name',''), request.form.get('phone',''),
         request.form.get('email',''), request.form.get('subject',''),
         request.form.get('message','')))
    db.commit(); db.close()
    flash('✅ Your message has been sent! We will contact you shortly.', 'success')
    return redirect(url_for('index') + '#contact')

@app.route('/admission', methods=['POST'])
def admission():
    db = get_db()
    db.execute("INSERT INTO admissions (student_name,father_name,phone,seeking_class) VALUES (?,?,?,?)",
        (request.form.get('student_name',''), request.form.get('father_name',''),
         request.form.get('phone',''), request.form.get('seeking_class','')))
    db.commit(); db.close()
    flash('✅ Admission enquiry submitted! We will call you shortly.', 'success')
    return redirect(url_for('index'))

# ── STUDENT AUTH ──────────────────────────
@app.route('/student/login', methods=['GET','POST'])
def student_login():
    if 'student_id' in session:
        return redirect(url_for('student_portal'))
    if request.method == 'POST':
        # ── CAPTCHA CHECK ──
        token = request.form.get('cf-turnstile-response', '')
        if not verify_captcha(token):
            flash('❌ Captcha verification failed. Please try again.', 'error')
            return redirect(url_for('student_login'))
        roll = request.form.get('roll_no','').strip()
        pw   = hash_password(request.form.get('password',''))
        db   = get_db()
        s    = db.execute("SELECT * FROM students WHERE roll_no=? AND password=? AND status='active'",
                          (roll, pw)).fetchone()
        db.close()
        if s:
            session['student_id']   = s['id']
            session['student_roll'] = s['roll_no']
            session['student_name'] = s['name']
            return redirect(url_for('student_portal'))
        flash('Invalid Roll Number or Password.', 'error')
    cf_site_key = os.environ.get('CF_TURNSTILE_SITE_KEY', '')
    return render_template('student_login.html', cf_site_key=cf_site_key)

@app.route('/student/logout')
def student_logout():
    session.pop('student_id',None); session.pop('student_roll',None); session.pop('student_name',None)
    return redirect(url_for('index'))

# ── STUDENT PORTAL DASHBOARD ──────────────
@app.route('/student/portal')
@student_required
def student_portal():
    db      = get_db()
    roll    = session.get('student_roll')
    student = db.execute("SELECT * FROM students WHERE roll_no=?", (roll,)).fetchone()
    if not student:
        db.close()
        session.clear()
        flash('Session expired. Please login again.', 'error')
        return redirect(url_for('student_login'))
    notices = db.execute("SELECT * FROM notices WHERE status='active' ORDER BY published_date DESC LIMIT 5").fetchall()
    backlogs_count = db.execute(
        "SELECT COUNT(*) FROM backlogs WHERE roll_no=? AND status='Pending'",
        (roll,)).fetchone()[0]
    latest_marks = db.execute("""
        SELECT semester AS class_no, marks_obtained, total_marks, credits
        FROM marks WHERE roll_no=? AND is_published=1
        ORDER BY semester DESC LIMIT 10""",
        (roll,)).fetchall()
    db.close()
    return render_template('student_portal.html',
        student=student, notices=notices,
        backlogs_count=backlogs_count, latest_marks=latest_marks)

# ── PERSONAL DETAILS ──────────────────────
@app.route('/student/profile')
@student_required
def student_profile():
    db      = get_db()
    student = db.execute("SELECT * FROM students WHERE roll_no=?", (session.get('student_roll'),)).fetchone()
    db.close()
    if not student:
        flash('Could not retrieve your details. Contact administration.', 'error')
        return redirect(url_for('student_portal'))
    return render_template('student_profile.html', student=student)

# ── BACKLOGS ──────────────────────────────
@app.route('/student/backlogs')
@student_required
def student_backlogs():
    db       = get_db()
    backlogs = db.execute(
        "SELECT * FROM backlogs WHERE roll_no=? ORDER BY status, semester",
        (session['student_roll'],)).fetchall()
    db.close()
    return render_template('student_backlogs.html', backlogs=backlogs)

@app.route('/student/backlogs/apply/<int:bid>', methods=['GET','POST'])
@student_required
def apply_backlog(bid):
    db      = get_db()
    backlog = db.execute("SELECT * FROM backlogs WHERE id=? AND roll_no=?",
                         (bid, session['student_roll'])).fetchone()
    if not backlog or backlog['status'] != 'Pending':
        flash('Invalid backlog or already applied/cleared.', 'error')
        db.close()
        return redirect(url_for('student_backlogs'))
    if request.method == 'POST':
        db.execute("UPDATE backlogs SET status='Applied', applied_date=? WHERE id=?",
                   (date.today().isoformat(), bid))
        db.commit(); db.close()
        flash('✅ Re-examination application submitted successfully.', 'success')
        return redirect(url_for('student_backlogs'))
    db.close()
    return render_template('apply_backlog.html', backlog=backlog)

# ── RESULTS ───────────────────────────────
@app.route('/student/results')
@student_required
def student_results():
    db   = get_db()
    roll = session['student_roll']

    available_classes = [row[0] for row in db.execute(
        "SELECT DISTINCT semester AS class_no FROM marks WHERE roll_no=? AND is_published=1 ORDER BY semester ASC",
        (roll,)).fetchall()]

    selected_class = request.args.get('class_no', type=int)
    if not selected_class and available_classes:
        selected_class = available_classes[0]

    student       = db.execute("SELECT * FROM students WHERE roll_no=?", (session.get('student_roll'),)).fetchone()
    marks_display = []
    pct_history   = {}
    pub_date      = None
    is_published  = False
    overall       = None

    if selected_class:
        pub_row = db.execute(
            "SELECT publication_date FROM marks WHERE roll_no=? AND semester=? AND is_published=1 LIMIT 1",
            (roll, selected_class)).fetchone()
        if pub_row:
            is_published = True
            pub_date     = pub_row['publication_date']

            all_marks = db.execute("""
                SELECT semester AS class_no, credits, marks_obtained, total_marks
                FROM marks WHERE roll_no=? AND semester<=? AND is_published=1
                ORDER BY semester ASC""", (roll, selected_class)).fetchall()

            marks_by_sem = {}
            for m in all_marks:
                marks_by_sem.setdefault(m['class_no'], []).append(dict(m))
            for sem, ml in marks_by_sem.items():
                pct_history[sem] = calculate_percentage(ml)

            raw = db.execute("""
                SELECT subject_code, subject_name, credits, marks_obtained, total_marks
                FROM marks WHERE roll_no=? AND semester=? AND is_published=1
                ORDER BY subject_name""", (roll, selected_class)).fetchall()

            for m in raw:
                g = calculate_grade(m['marks_obtained'], m['total_marks'])
                marks_display.append({
                    'subject_code':   m['subject_code'],
                    'subject_name':   m['subject_name'],
                    'credits':        m['credits'],
                    'marks_obtained': m['marks_obtained'],
                    'total_marks':    m['total_marks'],
                    'grade':          g,
                    'grade_points':   get_grade_points(g),
                })
            overall = calculate_overall_result([dict(m) for m in raw])

    overall_pct  = calculate_overall_pct(pct_history)
    pct_selected = pct_history.get(selected_class, '0.00') if selected_class else '0.00'
    db.close()

    return render_template('student_results.html',
        student=student, available_classes=available_classes,
        selected_class=selected_class, is_published=is_published,
        marks_display=marks_display, pct_history=pct_history,
        pct_selected=pct_selected, overall_pct=overall_pct,
        overall=overall, pub_date=pub_date)

# ── PUBLIC RESULT CHECKER ─────────────────
@app.route('/result', methods=['GET','POST'])
def check_result():
    results=None; student_info=None; searched=False
    if request.method == 'POST':
        roll     = request.form.get('roll_no','').strip()
        exam     = request.form.get('exam_type','')
        sess     = request.form.get('session','')
        searched = True
        db = get_db()
        student_info = db.execute("SELECT * FROM students WHERE roll_no=?", (roll,)).fetchone()
        results      = db.execute(
            "SELECT * FROM results WHERE roll_no=? AND exam_type=? AND session=? ORDER BY subject",
            (roll, exam, sess)).fetchall()
        db.close()
    return render_template('result.html', results=results, student_info=student_info, searched=searched)

# ── ADMIN AUTH ────────────────────────────
@app.route('/admin/login', methods=['GET','POST'])
def admin_login():
    if 'admin_id' in session: return redirect(url_for('admin_dashboard'))
    if request.method == 'POST':
        # ── CAPTCHA CHECK ──
        token = request.form.get('cf-turnstile-response', '')
        if not verify_captcha(token):
            flash('❌ Captcha verification failed. Please try again.', 'error')
            return redirect(url_for('admin_login'))
        uname = request.form.get('username','').strip()
        pw    = hash_password(request.form.get('password',''))
        db    = get_db()
        admin = db.execute("SELECT * FROM admins WHERE username=? AND password=?", (uname, pw)).fetchone()
        db.close()
        if admin:
            session['admin_id']   = admin['id']
            session['admin_name'] = admin['name']
            return redirect(url_for('admin_dashboard'))
        flash('Invalid username or password.', 'error')
    cf_site_key = os.environ.get('CF_TURNSTILE_SITE_KEY', '')
    return render_template('admin_login.html', cf_site_key=cf_site_key)

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_id',None); session.pop('admin_name',None)
    return redirect(url_for('admin_login'))

# ── ADMIN DASHBOARD ───────────────────────
@app.route('/admin')
@admin_required
def admin_dashboard():
    db = get_db()
    stats = {
        'students':   db.execute("SELECT COUNT(*) FROM students  WHERE status='active'").fetchone()[0],
        'staff':      db.execute("SELECT COUNT(*) FROM staff     WHERE status='active'").fetchone()[0],
        'notices':    db.execute("SELECT COUNT(*) FROM notices   WHERE status='active'").fetchone()[0],
        'messages':   db.execute("SELECT COUNT(*) FROM contacts  WHERE status='unread'").fetchone()[0],
        'admissions': db.execute("SELECT COUNT(*) FROM admissions WHERE status='pending'").fetchone()[0],
        'backlogs':   db.execute("SELECT COUNT(*) FROM backlogs  WHERE status='Pending'").fetchone()[0],
    }
    recent_contacts   = db.execute("SELECT * FROM contacts   ORDER BY received_at DESC LIMIT 5").fetchall()
    recent_admissions = db.execute("SELECT * FROM admissions ORDER BY received_at DESC LIMIT 5").fetchall()
    db.close()
    return render_template('admin_dashboard.html', stats=stats,
        recent_contacts=recent_contacts, recent_admissions=recent_admissions)

# ── NOTICES ───────────────────────────────
@app.route('/admin/notices')
@admin_required
def admin_notices():
    db=get_db(); notices=db.execute("SELECT * FROM notices ORDER BY published_date DESC").fetchall(); db.close()
    return render_template('admin_notices.html', notices=notices)

@app.route('/admin/notices/add', methods=['POST'])
@admin_required
def add_notice():
    db=get_db()
    db.execute("INSERT INTO notices (title,content,category,is_important,created_by) VALUES (?,?,?,?,?)",
        (request.form['title'],request.form['content'],request.form.get('category','General'),
         1 if request.form.get('is_important') else 0, session['admin_name']))
    db.commit(); db.close(); flash('✅ Notice added.','success')
    return redirect(url_for('admin_notices'))

@app.route('/admin/notices/delete/<int:nid>')
@admin_required
def delete_notice(nid):
    db=get_db(); db.execute("UPDATE notices SET status='inactive' WHERE id=?", (nid,))
    db.commit(); db.close(); flash('Notice deleted.','success')
    return redirect(url_for('admin_notices'))

# ── STAFF ─────────────────────────────────
@app.route('/admin/staff')
@admin_required
def admin_staff():
    db=get_db(); staff=db.execute("SELECT * FROM staff ORDER BY id").fetchall(); db.close()
    return render_template('admin_staff.html', staff=staff)

@app.route('/admin/staff/add', methods=['POST'])
@admin_required
def add_staff():
    db=get_db()
    try:
        photo = save_upload(request.files.get('photo'), STAFF_UPLOADS, 'staff')
        db.execute('''INSERT INTO staff (emp_id,name,designation,subject,qualification,phone,email,joining_date,profile_image)
                      VALUES (?,?,?,?,?,?,?,?,?)''',
            (request.form['emp_id'],request.form['name'],request.form['designation'],
             request.form.get('subject',''),request.form.get('qualification',''),
             request.form.get('phone',''),request.form.get('email',''),
             request.form.get('joining_date',''), photo or 'default.png'))
        db.commit(); flash('✅ Staff added successfully.','success')
    except Exception as e:
        flash(f'Error: Employee ID may already exist. ({e})','error')
    db.close(); return redirect(url_for('admin_staff'))

@app.route('/admin/staff/delete/<int:sid>')
@admin_required
def delete_staff(sid):
    db=get_db(); db.execute("UPDATE staff SET status='inactive' WHERE id=?",(sid,))
    db.commit(); db.close(); flash('Staff removed.','success')
    return redirect(url_for('admin_staff'))

@app.route('/admin/staff/edit/<int:sid>', methods=['POST'])
@admin_required
def edit_staff(sid):
    db=get_db()
    try:
        photo = save_upload(request.files.get('photo'), STAFF_UPLOADS, 'staff')
        if photo:
            old = db.execute("SELECT profile_image FROM staff WHERE id=?", (sid,)).fetchone()
            if old: delete_old_image(old['profile_image'])
            if old and old['profile_image'] and not USE_CLOUDINARY and not old['profile_image'].startswith('http'):
                old_path = os.path.join(STAFF_UPLOADS, old['profile_image'])
                if os.path.exists(old_path): os.remove(old_path)
            db.execute("""UPDATE staff SET
                name=?, designation=?, subject=?, qualification=?,
                phone=?, email=?, joining_date=?, status=?, profile_image=?
                WHERE id=?""",
                (request.form['name'], request.form['designation'],
                 request.form.get('subject',''), request.form.get('qualification',''),
                 request.form.get('phone',''), request.form.get('email',''),
                 request.form.get('joining_date',''), request.form.get('status','active'),
                 photo, sid))
        else:
            db.execute("""UPDATE staff SET
                name=?, designation=?, subject=?, qualification=?,
                phone=?, email=?, joining_date=?, status=?
                WHERE id=?""",
                (request.form['name'], request.form['designation'],
                 request.form.get('subject',''), request.form.get('qualification',''),
                 request.form.get('phone',''), request.form.get('email',''),
                 request.form.get('joining_date',''), request.form.get('status','active'), sid))
        db.commit(); flash('✅ Staff updated successfully.','success')
    except Exception as e:
        flash(f'Error: {e}','error')
    db.close(); return redirect(url_for('admin_staff'))

# ── STUDENTS ──────────────────────────────
@app.route('/admin/students')
@admin_required
def admin_students():
    db=get_db(); students=db.execute("SELECT * FROM students ORDER BY class_name,roll_no").fetchall(); db.close()
    return render_template('admin_students.html', students=students)

@app.route('/admin/students/add', methods=['POST'])
@admin_required
def add_student():
    db=get_db()
    try:
        photo = save_upload(request.files.get('photo'), STUDENT_UPLOADS, 'students')
        db.execute('''INSERT INTO students
            (roll_no,enrollment_no,name,father_name,mother_name,gender,course,class_name,section,dob,phone,email,password,admission_date,profile_image)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (request.form['roll_no'],request.form.get('enrollment_no',''),request.form['name'],
             request.form.get('father_name',''),request.form.get('mother_name',''),
             request.form.get('gender','Male'),request.form.get('course','General'),
             request.form['class_name'],request.form.get('section','A'),request.form.get('dob',''),
             request.form.get('phone',''),request.form.get('email',''),
             hash_password(request.form.get('password','password123')),
             date.today().isoformat(), photo or 'default.png'))
        db.commit(); flash('✅ Student added. Default password: password123','success')
    except Exception as e:
        flash(f'Error: Roll number may already exist. ({e})','error')
    db.close(); return redirect(url_for('admin_students'))

@app.route('/admin/students/delete/<int:sid>')
@admin_required
def delete_student(sid):
    db=get_db(); db.execute("UPDATE students SET status='inactive' WHERE id=?",(sid,))
    db.commit(); db.close(); flash('Student removed.','success')
    return redirect(url_for('admin_students'))

@app.route('/admin/students/edit/<int:sid>', methods=['POST'])
@admin_required
def edit_student(sid):
    db=get_db()
    try:
        photo    = save_upload(request.files.get('photo'), STUDENT_UPLOADS, 'students')
        pw_field = request.form.get('password','').strip()
        if photo:
            old = db.execute("SELECT profile_image FROM students WHERE id=?", (sid,)).fetchone()
            if old: delete_old_image(old['profile_image'])
            if old and old['profile_image'] and not USE_CLOUDINARY and not old['profile_image'].startswith('http'):
                old_path = os.path.join(STUDENT_UPLOADS, old['profile_image'])
                if os.path.exists(old_path): os.remove(old_path)
        fields = [
            "name=?","enrollment_no=?","father_name=?","mother_name=?",
            "gender=?","course=?","class_name=?","section=?","dob=?",
            "phone=?","email=?","address=?","status=?"
        ]
        values = [
            request.form['name'], request.form.get('enrollment_no',''),
            request.form.get('father_name',''), request.form.get('mother_name',''),
            request.form.get('gender','Male'), request.form.get('course','General'),
            request.form['class_name'], request.form.get('section','A'),
            request.form.get('dob',''), request.form.get('phone',''),
            request.form.get('email',''), request.form.get('address',''),
            request.form.get('status','active')
        ]
        if pw_field:
            fields.append("password=?"); values.append(hash_password(pw_field))
        if photo:
            fields.append("profile_image=?"); values.append(photo)
        values.append(sid)
        db.execute(f"UPDATE students SET {', '.join(fields)} WHERE id=?", values)
        db.commit(); flash('✅ Student updated successfully.','success')
    except Exception as e:
        flash(f'Error: {e}','error')
    db.close(); return redirect(url_for('admin_students'))

# ── MARKS ─────────────────────────────────
@app.route('/admin/marks')
@admin_required
def admin_marks():
    db=get_db()
    marks    = db.execute("SELECT * FROM marks ORDER BY roll_no,semester,subject_name").fetchall()
    students = db.execute("SELECT roll_no,enrollment_no,name,class_name,section FROM students WHERE status='active' ORDER BY class_name,section,roll_no").fetchall()
    classes  = db.execute("SELECT DISTINCT class_name FROM students WHERE status='active' ORDER BY class_name").fetchall()
    sections = db.execute("SELECT DISTINCT section FROM students WHERE status='active' ORDER BY section").fetchall()
    db.close()
    return render_template('admin_marks.html', marks=marks, students=students, classes=classes, sections=sections)

@app.route('/admin/marks/add', methods=['POST'])
@admin_required
def add_mark():
    db=get_db()
    obtained=int(request.form['marks_obtained']); total=int(request.form.get('total_marks',100))
    grade=calculate_grade(obtained,total)
    pub_date = request.form.get('publication_date', '').strip() or date.today().isoformat()
    is_pub   = 1 if request.form.get('is_published') else 0
    db.execute('''INSERT INTO marks
        (roll_no,student_name,class_name,subject_code,subject_name,credits,marks_obtained,total_marks,
         grade,semester,exam_type,session,publication_date,is_published)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (request.form['roll_no'],request.form['student_name'],request.form['class_name'],
         request.form.get('subject_code',''),request.form['subject_name'],
         int(request.form.get('credits',4)),obtained,total,grade,
         int(request.form['class_no']),request.form['exam_type'],request.form['session'],
         pub_date, is_pub))
    db.commit(); db.close(); flash('✅ Marks added successfully.','success')
    return redirect(url_for('admin_marks'))

@app.route('/admin/marks/delete/<int:mid>')
@admin_required
def delete_mark(mid):
    db=get_db(); db.execute("DELETE FROM marks WHERE id=?",(mid,))
    db.commit(); db.close(); flash('Mark deleted.','success')
    return redirect(url_for('admin_marks'))

@app.route('/admin/marks/toggle/<int:mid>')
@admin_required
def toggle_mark_publish(mid):
    db=get_db()
    current = db.execute("SELECT is_published FROM marks WHERE id=?", (mid,)).fetchone()
    if current:
        new_status = 0 if current['is_published'] else 1
        pub_date   = date.today().isoformat() if new_status else None
        if new_status:
            db.execute("UPDATE marks SET is_published=?, publication_date=? WHERE id=?", (new_status, pub_date, mid))
        else:
            db.execute("UPDATE marks SET is_published=? WHERE id=?", (new_status, mid))
        db.commit()
        flash(f"✅ Marks {'published' if new_status else 'set to draft'}.", 'success')
    db.close()
    return redirect(url_for('admin_marks'))

@app.route('/admin/marks/add-bulk', methods=['POST'])
@admin_required
def add_marks_bulk():
    db      = get_db()
    roll_no = request.form['roll_no']
    student_name = request.form['student_name']
    class_name   = request.form['class_name']
    class_no     = int(request.form['class_no'])
    exam_type    = request.form['exam_type']
    session_yr   = request.form['session']
    pub_date     = request.form.get('publication_date','').strip() or date.today().isoformat()
    is_pub       = 1 if request.form.get('is_published') else 0
    subjects     = request.form.getlist('subject_name[]')
    codes        = request.form.getlist('subject_code[]')
    credits_list = request.form.getlist('credits[]')
    obtained_list= request.form.getlist('marks_obtained[]')
    total_list   = request.form.getlist('total_marks[]')
    count = 0
    for i, subj in enumerate(subjects):
        if not subj.strip(): continue
        obt   = int(obtained_list[i]) if i < len(obtained_list) and obtained_list[i] else 0
        tot   = int(total_list[i])    if i < len(total_list)    and total_list[i]    else 100
        cred  = int(credits_list[i])  if i < len(credits_list)  and credits_list[i]  else 4
        code  = codes[i]              if i < len(codes)                               else ''
        grade = calculate_grade(obt, tot)
        db.execute('''INSERT INTO marks
            (roll_no,student_name,class_name,subject_code,subject_name,credits,marks_obtained,total_marks,
             grade,semester,exam_type,session,publication_date,is_published)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (roll_no, student_name, class_name, code, subj, cred, obt, tot,
             grade, class_no, exam_type, session_yr, pub_date, is_pub))
        count += 1
    db.commit(); db.close()
    flash(f'✅ {count} subject(s) marks saved for {student_name}.', 'success')
    return redirect(url_for('admin_marks'))

# ── OLD RESULTS (public checker) ──────────
@app.route('/admin/results')
@admin_required
def admin_results():
    db=get_db()
    results  = db.execute("SELECT * FROM results ORDER BY roll_no,exam_type,subject").fetchall()
    students = db.execute("SELECT roll_no,name,class_name FROM students WHERE status='active' ORDER BY class_name,roll_no").fetchall()
    db.close()
    return render_template('admin_results.html', results=results, students=students)

@app.route('/admin/results/add', methods=['POST'])
@admin_required
def add_result():
    db=get_db()
    obtained=int(request.form['obtained_marks']); max_m=int(request.form.get('max_marks',100))
    pct=(obtained/max_m)*100
    grade='A+' if pct>=90 else 'A' if pct>=80 else 'B+' if pct>=70 else 'B' if pct>=60 else 'C' if pct>=50 else 'F'
    db.execute('''INSERT INTO results
        (roll_no,student_name,class_name,exam_type,session,subject,max_marks,obtained_marks,grade)
        VALUES (?,?,?,?,?,?,?,?,?)''',
        (request.form['roll_no'],request.form['student_name'],request.form['class_name'],
         request.form['exam_type'],request.form['session'],request.form['subject'],max_m,obtained,grade))
    db.commit(); db.close(); flash('✅ Result added.','success')
    return redirect(url_for('admin_results'))

@app.route('/admin/results/delete/<int:rid>')
@admin_required
def delete_result(rid):
    db=get_db(); db.execute("DELETE FROM results WHERE id=?",(rid,))
    db.commit(); db.close(); flash('Result deleted.','success')
    return redirect(url_for('admin_results'))

# ── BACKLOGS (admin) ──────────────────────
@app.route('/admin/backlogs')
@admin_required
def admin_backlogs():
    db=get_db()
    backlogs = db.execute("""
        SELECT b.*, s.class_name FROM backlogs b
        LEFT JOIN students s ON b.roll_no=s.roll_no
        ORDER BY b.status, b.roll_no""").fetchall()
    students = db.execute("SELECT roll_no,name,class_name FROM students WHERE status='active' ORDER BY class_name").fetchall()
    db.close()
    return render_template('admin_backlogs.html', backlogs=backlogs, students=students)

@app.route('/admin/backlogs/add', methods=['POST'])
@admin_required
def add_backlog():
    db=get_db()
    db.execute('''INSERT INTO backlogs (roll_no,student_name,subject_code,subject_name,semester,status)
                  VALUES (?,?,?,?,?,'Pending')''',
        (request.form['roll_no'],request.form['student_name'],
         request.form.get('subject_code',''),request.form['subject_name'],int(request.form['class_no'])))
    db.commit(); db.close(); flash('✅ Backlog added.','success')
    return redirect(url_for('admin_backlogs'))

@app.route('/admin/backlogs/update/<int:bid>/<status>')
@admin_required
def update_backlog(bid, status):
    db=get_db()
    if status=='Cleared':
        db.execute("UPDATE backlogs SET status='Cleared',cleared_date=? WHERE id=?",(date.today().isoformat(),bid))
    else:
        db.execute("UPDATE backlogs SET status=? WHERE id=?",(status,bid))
    db.commit(); db.close(); flash(f'Backlog updated to {status}.','success')
    return redirect(url_for('admin_backlogs'))

@app.route('/admin/backlogs/delete/<int:bid>')
@admin_required
def delete_backlog(bid):
    db=get_db(); db.execute("DELETE FROM backlogs WHERE id=?",(bid,))
    db.commit(); db.close(); flash('Backlog deleted.','success')
    return redirect(url_for('admin_backlogs'))

# ── MESSAGES ──────────────────────────────
@app.route('/admin/messages')
@admin_required
def admin_messages():
    db=get_db()
    messages=db.execute("SELECT * FROM contacts ORDER BY received_at DESC").fetchall()
    db.execute("UPDATE contacts SET status='read' WHERE status='unread'")
    db.commit(); db.close()
    return render_template('admin_messages.html', messages=messages)

@app.route('/admin/messages/delete/<int:mid>')
@admin_required
def delete_message(mid):
    db=get_db(); db.execute("DELETE FROM contacts WHERE id=?",(mid,))
    db.commit(); db.close(); flash('Message deleted.','success')
    return redirect(url_for('admin_messages'))

# ── ADMISSIONS ────────────────────────────
@app.route('/admin/admissions')
@admin_required
def admin_admissions():
    db=get_db(); admissions=db.execute("SELECT * FROM admissions ORDER BY received_at DESC").fetchall(); db.close()
    return render_template('admin_admissions.html', admissions=admissions)

@app.route('/admin/admissions/update/<int:aid>/<status>')
@admin_required
def update_admission(aid, status):
    db=get_db(); db.execute("UPDATE admissions SET status=? WHERE id=?",(status,aid))
    db.commit(); db.close(); flash(f'Admission updated to {status}.','success')
    return redirect(url_for('admin_admissions'))

# ── GALLERY ───────────────────────────────
@app.route('/admin/gallery')
@admin_required
def admin_gallery():
    db=get_db(); gallery=db.execute("SELECT * FROM gallery ORDER BY id").fetchall(); db.close()
    return render_template('admin_gallery.html', gallery=gallery)

@app.route('/admin/gallery/add', methods=['POST'])
@admin_required
def add_gallery():
    db=get_db()
    photo = save_upload(request.files.get('photo'), GALLERY_UPLOADS, 'gallery')
    db.execute("INSERT INTO gallery (title,description,image,category) VALUES (?,?,?,?)",
        (request.form['title'], request.form.get('description',''),
         photo, request.form.get('category','General')))
    db.commit(); db.close(); flash('✅ Gallery photo added.','success')
    return redirect(url_for('admin_gallery'))

@app.route('/admin/gallery/edit/<int:gid>', methods=['POST'])
@admin_required
def edit_gallery(gid):
    db=get_db()
    photo = save_upload(request.files.get('photo'), GALLERY_UPLOADS, 'gallery')
    if photo:
        old = db.execute("SELECT image FROM gallery WHERE id=?", (gid,)).fetchone()
        if old and old['image']:
            delete_old_image(old['image'])
            if old and old['image'] and not USE_CLOUDINARY and not old['image'].startswith('http'):
                old_path = os.path.join(GALLERY_UPLOADS, old['image'])
                if os.path.exists(old_path): os.remove(old_path)
        db.execute("UPDATE gallery SET title=?,description=?,category=?,image=? WHERE id=?",
                   (request.form['title'], request.form.get('description',''),
                    request.form.get('category','General'), photo, gid))
    else:
        db.execute("UPDATE gallery SET title=?,description=?,category=? WHERE id=?",
                   (request.form['title'], request.form.get('description',''),
                    request.form.get('category','General'), gid))
    db.commit(); db.close(); flash('✅ Gallery item updated.','success')
    return redirect(url_for('admin_gallery'))

@app.route('/admin/gallery/delete/<int:gid>')
@admin_required
def delete_gallery(gid):
    db=get_db()
    old = db.execute("SELECT image FROM gallery WHERE id=?", (gid,)).fetchone()
    if old and old['image']:
        delete_old_image(old['image'])
        if old and old['image'] and not USE_CLOUDINARY and not old['image'].startswith('http'):
            old_path = os.path.join(GALLERY_UPLOADS, old['image'])
            if os.path.exists(old_path): os.remove(old_path)
    db.execute("DELETE FROM gallery WHERE id=?",(gid,))
    db.commit(); db.close(); flash('Deleted.','success')
    return redirect(url_for('admin_gallery'))

# ── SERVE UPLOADED FILES ─────────────────
from flask import send_from_directory

@app.route('/static/uploads/students/<filename>')
def serve_student_photo(filename):
    return send_from_directory(STUDENT_UPLOADS, filename)

@app.route('/static/uploads/staff/<filename>')
def serve_staff_photo(filename):
    return send_from_directory(STAFF_UPLOADS, filename)

@app.route('/static/uploads/gallery/<filename>')
def serve_gallery_photo(filename):
    return send_from_directory(GALLERY_UPLOADS, filename)

# ─────────────────────────────────────────

init_db()

if __name__ == '__main__':
    app.run(debug=True, port=5000)