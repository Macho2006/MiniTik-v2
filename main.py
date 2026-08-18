from flask import Flask, render_template, request, redirect, session, url_for, flash, jsonify
import os
import time
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
from psycopg2.extras import RealDictCursor
from flask_session import Session
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import cloudinary, cloudinary.uploader
from datetime import datetime

app = Flask(__name__)

app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024
app.secret_key = os.environ.get('SECRET_KEY', 'minitik_secret_key_2026_change_this')
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = True
Session(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

cloudinary.config(
  cloud_name = os.environ.get('CLOUD_NAME'),
  api_key = os.environ.get('CLOUD_API_KEY'),
  api_secret = os.environ.get('CLOUD_API_SECRET')
)

DATABASE_URL = os.environ.get('DATABASE_URL', '')
if DATABASE_URL and 'sslmode' not in DATABASE_URL:
    DATABASE_URL += '?sslmode=require'

ADMIN_USERNAME = "MachoDev"
ALLOWED_EXT = {'mp4', 'mov', 'avi', 'jpg', 'jpeg', 'png', 'gif'}
FILTERS = ['None', 'Grayscale', 'Sepia', 'Blur', 'Bright']

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXT

class User(UserMixin):
    def __init__(self, id, username, is_admin=False, profile_pic=None):
        self.id = id
        self.username = username
        self.is_admin = is_admin
        self.profile_pic = profile_pic

@login_manager.user_loader
def load_user(user_id):
    try:
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT id, username, is_admin, profile_pic FROM users WHERE id=%s", (user_id,))
        user = c.fetchone()
        conn.close()
        if user:
            return User(user['id'], user['username'], user['is_admin'], user['profile_pic'])
    except:
        return None
    return None

@app.template_filter('datetimeformat')
def datetimeformat(value):
    try:
        return datetime.fromtimestamp(int(value)).strftime('%b %d, %I:%M %p')
    except:
        return value

def get_db():
    if not DATABASE_URL:
        raise Exception("DATABASE_URL not set")
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users(id SERIAL PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT, email TEXT UNIQUE, dob TEXT, region TEXT, bio TEXT DEFAULT '', profile_pic TEXT DEFAULT 'https://res.cloudinary.com/demo/image/upload/v131415/default_avatar.png', banned INTEGER DEFAULT 0, verified INTEGER DEFAULT 0, pro_mode INTEGER DEFAULT 0, followers INTEGER DEFAULT 0, total_likes INTEGER DEFAULT 0, is_admin BOOLEAN DEFAULT FALSE)''')
    c.execute('''CREATE TABLE IF NOT EXISTS messages(id SERIAL PRIMARY KEY, sender TEXT, receiver TEXT, message TEXT, timestamp REAL, read INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS videos(id SERIAL PRIMARY KEY, username TEXT, video TEXT, caption TEXT, likes INTEGER DEFAULT 0, timestamp REAL, type TEXT DEFAULT 'video', filter TEXT DEFAULT 'None')''')
    c.execute('''CREATE TABLE IF NOT EXISTS likes(video_id INTEGER, username TEXT, PRIMARY KEY(video_id, username))''')
    c.execute('''CREATE TABLE IF NOT EXISTS following(follower TEXT, following TEXT, PRIMARY KEY(follower, following))''')
    c.execute('''CREATE TABLE IF NOT EXISTS comments(id SERIAL PRIMARY KEY, video_id INTEGER, username TEXT, comment TEXT, timestamp REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS notifications(id SERIAL PRIMARY KEY, username TEXT, actor TEXT, type TEXT, target_id INTEGER, message TEXT, is_read INTEGER DEFAULT 0, timestamp REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS stories(id SERIAL PRIMARY KEY, username TEXT, video TEXT, timestamp REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS pages(id SERIAL PRIMARY KEY, owner TEXT, page_name TEXT, followers INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS support_tickets(id SERIAL PRIMARY KEY, username TEXT, issue TEXT, timestamp REAL, status TEXT DEFAULT 'Open')''')
    c.execute('''CREATE TABLE IF NOT EXISTS friends(user1 TEXT, user2 TEXT, PRIMARY KEY(user1, user2))''')
    conn.commit()
    conn.close()

def make_admin():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT 1 FROM users WHERE username=%s", (ADMIN_USERNAME,))
    if c.fetchone():
        c.execute("UPDATE users SET is_admin=TRUE WHERE username=%s", (ADMIN_USERNAME,))
    conn.commit(); conn.close()

@app.before_request
def startup():
    if not hasattr(app, 'db_initialized'):
        init_db()
        make_admin()
        app.db_initialized = True

def create_notification(username, actor, type, target_id, message):
    if username == actor: return
    conn = get_db(); c = conn.cursor()
    c.execute("INSERT INTO notifications (username, actor, type, target_id, message, timestamp) VALUES (%s,%s,%s,%s,%s,%s)",
              (username, actor, type, target_id, message, time.time()))
    conn.commit(); conn.close()

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        conn = get_db(); c = conn.cursor()
        try:
            c.execute("INSERT INTO users (username,password_hash,email,dob,region) VALUES (%s,%s,%s,%s,%s)",
                (request.form['username'], generate_password_hash(request.form['password']), request.form['email'], request.form['dob'], request.form['region']))
            conn.commit()
            flash('Account created! Please login.', 'success')
            return redirect('/login')
        except:
            flash('Username or Email already exists')
            return redirect('/signup')
        finally:
            conn.close()
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username=%s", (request.form['username'],))
        user = c.fetchone(); conn.close()
        if user and check_password_hash(user['password_hash'], request.form['password']):
            if user['banned']: flash('Banned'); return redirect('/login')
            user_obj = User(user['id'], user['username'], user['is_admin'], user['profile_pic'])
            login_user(user_obj)
            flash(f'Welcome back {user["username"]}!')
            return redirect('/')
        flash('Invalid login')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect('/login')

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        file = request.files['profile_pic']
        if file and allowed_file(file.filename):
            upload_result = cloudinary.uploader.upload(file, folder="minitik_pfps")
            pic_url = upload_result['secure_url']
            conn = get_db(); c = conn.cursor()
            c.execute("UPDATE users SET profile_pic=%s WHERE username=%s", (pic_url, current_user.username))
            conn.commit(); conn.close()
            flash('Profile picture updated!')
            return redirect('/settings')
    return render_template('settings.html')

@app.route('/')
@login_required
def index():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT v.*, u.profile_pic, u.verified FROM videos v JOIN users u ON v.username=u.username ORDER BY timestamp DESC")
    videos = c.fetchall()
    twenty_four_hours_ago = time.time() - (24 * 60 * 60)
    c.execute("SELECT DISTINCT ON (s.username) s.*, u.profile_pic FROM stories s JOIN users u ON s.username=u.username WHERE s.timestamp > %s ORDER BY s.username, s.timestamp DESC", (twenty_four_hours_ago,))
    stories = c.fetchall()
    c.execute("SELECT following FROM following WHERE follower=%s", (current_user.username,))
    following = [r['following'] for r in c.fetchall()]
    conn.close()
    return render_template('index.html', videos=videos, stories=stories, current_user=current_user.username, following=following, tab='foryou')

@app.route('/profile/<username>')
@login_required
def profile(username):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username=%s", (username,))
    user = c.fetchone()
    if not user:
        conn.close()
        return "User not found", 404
    c.execute("SELECT * FROM videos WHERE username=%s ORDER BY id DESC", (username,))
    videos = c.fetchall()
    conn.close()
    return render_template('profile.html', user=user, videos=videos)

@app.route('/follow/<username>')
@login_required
def follow(username):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT 1 FROM following WHERE follower=%s AND following=%s", (current_user.username, username)); exists = c.fetchone()
    if exists:
        c.execute("DELETE FROM following WHERE follower=%s AND following=%s", (current_user.username, username))
        c.execute("UPDATE users SET followers = followers - 1 WHERE username=%s", (username,))
    else:
        c.execute("INSERT INTO following VALUES (%s,%s)", (current_user.username, username))
        c.execute("UPDATE users SET followers = followers + 1 WHERE username=%s", (username,))
        create_notification(username, current_user.username, 'follow', 0, f'{current_user.username} started following you')
    conn.commit(); conn.close(); return redirect(f'/profile/{username}')

#... ALL OTHER ROUTES ARE THE SAME JUST WITH current_user.username INSTEAD OF session['username']

with app.app_context():
    @app.route('/reset_admin')
    def reset_admin():
        conn = get_db(); c = conn.cursor()
        c.execute("DELETE FROM users WHERE username=%s", (ADMIN_USERNAME,))
        c.execute("INSERT INTO users (username,password_hash,email,dob,region,is_admin) VALUES (%s,%s,%s,%s,%s,TRUE)",
            (ADMIN_USERNAME, generate_password_hash('admin123'), 'mocugo2006@gmail.com', '2006-08-21', 'Other'))
        conn.commit(); conn.close()
        return "MachoDev RESET! Username: MachoDev Password: admin123"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
