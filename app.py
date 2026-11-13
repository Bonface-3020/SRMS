import os
import secrets
import sqlite3
from functools import wraps
from pathlib import Path
from flask import Flask, render_template, request, session, redirect, url_for, flash, g, abort
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.config['DATABASE'] = str(Path(__file__).with_name('school.db'))


def db():
    if 'db' not in g:
        g.db = sqlite3.connect(app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(error=None):
    connection = g.pop('db', None)
    if connection is not None:
        connection.close()


def init_db():
    db().executescript('''
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, username TEXT UNIQUE, password TEXT, role TEXT);
    CREATE TABLE IF NOT EXISTS resources(id INTEGER PRIMARY KEY, title TEXT, subject TEXT, description TEXT, quantity INTEGER CHECK(quantity >= 0));
    CREATE TABLE IF NOT EXISTS loans(id INTEGER PRIMARY KEY, student_id INTEGER, resource_id INTEGER, status TEXT DEFAULT 'Pending', date TEXT DEFAULT CURRENT_TIMESTAMP);
    ''')
    if not db().execute('SELECT id FROM users').fetchone():
        for name, username, password, role in [('Alex Student', 'student', 'student123', 'student'), ('Ms. Taylor', 'teacher', 'teacher123', 'teacher')]:
            db().execute('INSERT INTO users(name,username,password,role) VALUES(?,?,?,?)', (name, username, generate_password_hash(password), role))
        db().executemany('INSERT INTO resources(title,subject,description,quantity) VALUES(?,?,?,?)', [
            ('Mathematics textbook', 'Mathematics', 'Grade 10 practice questions and worked examples.', 12),
            ('Science lab kit', 'Science', 'Equipment for supervised classroom experiments.', 5),
            ('World atlas', 'Geography', 'Maps and reference material for geography lessons.', 8),
            ('English reader', 'English', 'Short stories and reading activities.', 15)])
    db().commit()


@app.before_request
def prepare_request():
    g.user = db().execute('SELECT * FROM users WHERE id=?', (session.get('user_id'),)).fetchone()
    session.setdefault('token', secrets.token_hex(24))
    if request.method == 'POST' and not secrets.compare_digest(session['token'], request.form.get('token', '')):
        abort(400)


def require(role=None):
    def decorate(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not g.user:
                return redirect(url_for('login'))
            if role and g.user['role'] != role:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorate


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = db().execute('SELECT * FROM users WHERE username=?', (request.form.get('username', '').strip(),)).fetchone()
        if user and check_password_hash(user['password'], request.form.get('password', '')):
            session.clear()
            session['user_id'] = user['id']
            return redirect(url_for('home'))
        flash('Incorrect username or password.', 'danger')
    return render_template('login.html')


@app.post('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.get('/')
@require()
def home():
    resources = db().execute('SELECT * FROM resources ORDER BY title').fetchall()
    sql = 'SELECT loans.*, users.name, resources.title FROM loans JOIN users ON users.id=loans.student_id JOIN resources ON resources.id=loans.resource_id'
    loans = db().execute(sql + ' ORDER BY loans.id DESC').fetchall() if g.user['role'] == 'teacher' else db().execute(sql + ' WHERE student_id=? ORDER BY loans.id DESC', (g.user['id'],)).fetchall()
    return render_template('index.html', resources=resources, loans=loans, available=sum(r['quantity'] for r in resources), pending=sum(r['status'] == 'Pending' for r in loans))


@app.post('/resources/add')
@require('teacher')
def add_resource():
    title = request.form.get('title', '').strip()
    subject = request.form.get('subject', '').strip()
    description = request.form.get('description', '').strip()
    try:
        quantity = int(request.form.get('quantity', ''))
    except ValueError:
        quantity = -1
    if not (0 < len(title) <= 100 and 0 < len(subject) <= 50 and 0 < len(description) <= 500 and 0 <= quantity <= 1000):
        flash('Enter all details and a quantity between 0 and 1000.', 'danger')
    else:
        db().execute('INSERT INTO resources(title,subject,description,quantity) VALUES(?,?,?,?)', (title, subject, description, quantity))
        db().commit()
        flash('Resource added.', 'success')
    return redirect(url_for('home'))


@app.post('/resources/<int:resource_id>/request')
@require('student')
def borrow(resource_id):
    resource = db().execute('SELECT * FROM resources WHERE id=?', (resource_id,)).fetchone()
    if resource is None:
        abort(404)
    existing = db().execute("SELECT id FROM loans WHERE student_id=? AND resource_id=? AND status IN ('Pending','Approved')", (g.user['id'], resource_id)).fetchone()
    if existing or resource['quantity'] == 0:
        flash('Item unavailable or you already have an active request.', 'warning')
    else:
        db().execute('INSERT INTO loans(student_id,resource_id) VALUES(?,?)', (g.user['id'], resource_id))
        db().commit()
        flash('Request sent to your teacher.', 'success')
    return redirect(url_for('home'))


@app.post('/loans/<int:loan_id>/<action>')
@require('teacher')
def update_loan(loan_id, action):
    db().execute('BEGIN IMMEDIATE')
    loan = db().execute('SELECT * FROM loans WHERE id=?', (loan_id,)).fetchone()
    if loan is None:
        abort(404)
    if action == 'approve' and loan['status'] == 'Pending':
        changed = db().execute('UPDATE resources SET quantity=quantity-1 WHERE id=? AND quantity>0', (loan['resource_id'],)).rowcount
        if not changed:
            db().rollback()
            flash('No copies available.', 'warning')
            return redirect(url_for('home'))
        status = 'Approved'
    elif action == 'decline' and loan['status'] == 'Pending':
        status = 'Declined'
    elif action == 'return' and loan['status'] == 'Approved':
        db().execute('UPDATE resources SET quantity=quantity+1 WHERE id=?', (loan['resource_id'],))
        status = 'Returned'
    else:
        abort(400)
    db().execute('UPDATE loans SET status=? WHERE id=?', (status, loan_id))
    db().commit()
    flash('Request updated.', 'success')
    return redirect(url_for('home'))


with app.app_context():
    init_db()

if __name__ == '__main__':
    app.run(debug=True)
