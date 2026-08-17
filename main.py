from flask import Flask, render_template, request, redirect, session, url_for, flash, jsonify
import os
import time
from datetime import datetime
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
from psycopg2.extras import RealDictCursor
from flask_session import Session
import cloudinary, cloudinary.uploader

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'minitik_secret_key_2026_change_this')
app.config['SESSION_TYPE'] = 'filesystem'
Session(app)

cloudinary.config(
  cloud_name = os.environ.get('CLOUD_NAME'),
  api_key = os.environ.get('CLOUD_API_KEY'),
  api_secret = os.environ.get('CLOUD_API_SECRET')
)

ADMIN_USERNAME = "MachoDev"
ALLOWED_EXT = {'mp4', 'mov', 'avi', 'jpg', 'jpeg', 'png', 'gif'}
FILTERS = ['None', 'Grayscale', 'Sepia', 'Blur', 'Bright']

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXT

# ========== DATABASE ==========
def get_db():
    DATABASE_URL = os.environ.get('DATABASE_URL')
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    # Added profile_pic + notifications table
    c.execute('''CREATE TABLE IF NOT EXISTS users(
        id SERIAL PRIMARY KEY, username TEXT UNIQUE, password TEXT, email TEXT UNIQUE,
        dob TEXT, region TEXT, bio TEXT DEFAULT '', profile_pic TEXT DEFAULT 'https://res.cloudinary.com/demo/image/upload/v131415/default_avatar.png',
        banned INTEGER DEFAULT 0, verified INTEGER DEFAULT 0, pro_mode INTEGER DEFAULT 0,
        followers INTEGER DEFAULT 0, total_likes INTEGER DEFAULT 0, is_admin BOOLEAN DEFAULT FALSE
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS videos(id SERIAL PRIMARY KEY, username TEXT, video TEXT, caption TEXT, likes INTEGER DEFAULT 0, timestamp REAL, type TEXT DEFAULT 'video', filter TEXT DEFAULT 'None')''')
    c.execute('''CREATE TABLE IF NOT EXISTS likes(video_id INTEGER, username TEXT, PRIMARY KEY(video_id, username))''')
    c.execute('''CREATE TABLE IF NOT EXISTS following(follower TEXT, following TEXT, PRIMARY KEY(follower, following))''')
    c.execute('''CREATE TABLE IF NOT EXISTS comments(id SERIAL PRIMARY KEY, video_id INTEGER, username TEXT, comment TEXT, timestamp REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS notifications(id SERIAL PRIMARY KEY, username TEXT, actor TEXT, type TEXT, target_id INTEGER, message TEXT, is_read INTEGER DEFAULT 0, timestamp REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS stories(id SERIAL PRIMARY KEY, username TEXT, video TEXT, timestamp REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS pages(id SERIAL PRIMARY KEY, owner TEXT, page_name TEXT, followers INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS support_tickets(id SERIAL PRIMARY KEY, username TEXT, issue TEXT, timestamp REAL, status TEXT DEFAULT 'Open')''')
    c.execute('''CREATE TABLE IF NOT EXISTS messages(id SERIAL PRIMARY KEY, sender TEXT, receiver TEXT, message TEXT, timestamp REAL, read INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS friends(user1 TEXT, user2 TEXT, PRIMARY KEY(user1, user2))''')
    conn.commit()
    conn.close()

init_db()

def current_user(): return session.get('username')

def create_notification(username, actor, type, target_id, message):
    if username == actor: return # Don't notify yourself
    conn = get_db(); c = conn.cursor()
    c.execute("INSERT INTO notifications (username, actor, type, target_id, message, timestamp) VALUES (%s,%s,%s,%s,%s,%s)",
              (username, actor, type, target_id, message, time.time()))
    conn.commit(); conn.close()

# ========== AUTH ==========
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        conn = get_db(); c = conn.cursor()
        try:
            c.execute("INSERT INTO users (username,password,email,dob,region) VALUES (%s,%s,%s,%s,%s)",
                (request.form['username'], generate_password_hash(request.form['password']), request.form['email'], request.form['dob'], request.form['region']))
            conn.commit()
        except: flash('Username or Email exists'); conn.close(); return redirect('/signup')
        conn.close(); flash('Account created!'); return redirect('/login')
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username=%s", (request.form['username'],))
        user = c.fetchone(); conn.close()
        if user and check_password_hash(user['password'], request.form['password']):
            if user['banned']: flash('Banned'); return redirect('/login')
            session['username'] = user['username']
            session['is_admin'] = user['is_admin']
            session['profile_pic'] = user['profile_pic']
            return redirect('/')
        flash('Invalid login')
    return render_template('login.html')

@app.route('/logout')
def logout(): session.clear(); return redirect('/login')

# ========== PROFILE PIC UPLOAD ==========
@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if 'username' not in session: return redirect('/login')
    if request.method == 'POST':
        file = request.files['profile_pic']
        if file and allowed_file(file.filename):
            upload_result = cloudinary.uploader.upload(file, folder="minitik_pfps")
            pic_url = upload_result['secure_url']
            conn = get_db(); c = conn.cursor()
            c.execute("UPDATE users SET profile_pic=%s WHERE username=%s", (pic_url, current_user()))
            conn.commit(); conn.close()
            session['profile_pic'] = pic_url
            flash('Profile picture updated!')
            return redirect('/settings')
    return render_template('settings.html')

# ========== MAIN FEEDS ==========
@app.route('/')
def index():
    if 'username' not in session: return redirect('/login')
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT v.*, u.profile_pic, u.verified FROM videos v JOIN users u ON v.username=u.username ORDER BY timestamp DESC"); videos = c.fetchall()
    c.execute("SELECT following FROM following WHERE follower=%s", (current_user(),)); following = [r['following'] for r in c.fetchall()]
    conn.close()
    return render_template('index.html', videos=videos, current_user=current_user(), following=following, tab='foryou')

# ========== FOLLOW ==========
@app.route('/follow/<username>')
def follow(username):
    if 'username' not in session: return redirect('/login')
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT 1 FROM following WHERE follower=%s AND following=%s", (current_user(), username)); exists = c.fetchone()
    if exists:
        c.execute("DELETE FROM following WHERE follower=%s AND following=%s", (current_user(), username))
        c.execute("UPDATE users SET followers = followers - 1 WHERE username=%s", (username,))
    else:
        c.execute("INSERT INTO following VALUES (%s,%s)", (current_user(), username))
        c.execute("UPDATE users SET followers = followers + 1 WHERE username=%s", (username,))
        create_notification(username, current_user(), 'follow', 0, f'{current_user()} started following you')
    conn.commit(); conn.close(); return redirect(f'/profile/{username}')

# ========== COMMENTS ==========
@app.route('/comments/<int:video_id>', methods=['GET', 'POST'])
def comments(video_id):
    if 'username' not in session: return redirect('/login')
    conn = get_db(); c = conn.cursor()
    if request.method == 'POST':
        comment = request.form['comment']
        c.execute("INSERT INTO comments (video_id, username, comment, timestamp) VALUES (%s,%s,%s,%s)",
                  (video_id, current_user(), comment, time.time()))
        c.execute("SELECT username FROM videos WHERE id=%s", (video_id,)); owner = c.fetchone()
        create_notification(owner['username'], current_user(), 'comment', video_id, f'{current_user()} commented: {comment[:30]}')
        conn.commit()
    c.execute("SELECT c.*, u.profile_pic FROM comments c JOIN users u ON c.username=u.username WHERE video_id=%s ORDER BY timestamp DESC", (video_id,)); comments = c.fetchall()
    conn.close()
    return render_template('comments.html', comments=comments, video_id=video_id)

# ========== UPLOAD WITH CLOUDINARY ==========
@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if 'username' not in session: return redirect('/login')
    if request.method == 'POST':
        file = request.files['file']
        caption = request.form['caption']
        filter_type = request.form['filter']
        if file and allowed_file(file.filename):
            upload_result = cloudinary.uploader.upload(file, resource_type="auto")
            file_url = upload_result['secure_url']
            ext = file.filename.rsplit('.', 1)[1].lower()
            file_type = 'image' if ext in ['jpg','jpeg','png','gif'] else 'video'

            conn = get_db(); c = conn.cursor()
            c.execute("INSERT INTO videos (username, video, caption, timestamp, type, filter) VALUES (%s,%s,%s,%s,%s,%s)",
                (current_user(), file_url, caption, time.time(), file_type, filter_type))
            conn.commit(); conn.close()
            return redirect('/')
    return render_template('upload.html', filters=FILTERS)

# ========== LIKE ==========
@app.route('/like/<int:post_id>')
def like(post_id):
    if 'username' not in session: return redirect('/login')
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT username FROM videos WHERE id=%s", (post_id,)); video = c.fetchone()
    c.execute("SELECT 1 FROM likes WHERE video_id=%s AND username=%s", (post_id, current_user())); liked = c.fetchone()
    if liked:
        c.execute("DELETE FROM likes WHERE video_id=%s AND username=%s", (post_id, current_user()))
        c.execute("UPDATE videos SET likes = likes - 1 WHERE id=%s", (post_id,))
        c.execute("UPDATE users SET total_likes = total_likes - 1 WHERE username=%s", (video['username'],))
    else:
        c.execute("INSERT INTO likes VALUES (%s,%s)", (post_id, current_user()))
        c.execute("UPDATE videos SET likes = likes + 1 WHERE id=%s", (post_id,))
        c.execute("UPDATE users SET total_likes = total_likes + 1 WHERE username=%s", (video['username'],))
        create_notification(video['username'], current_user(), 'like', post_id, f'{current_user()} liked your video')
    conn.commit(); conn.close(); return redirect(request.referrer or '/')

# ========== REAL NOTIFICATIONS ==========
@app.route('/notifications')
def notifications():
    if 'username' not in session: return redirect('/login')
    conn = get_db(); c = conn.cursor()
    c.execute("UPDATE notifications SET is_read=1 WHERE username=%s", (current_user(),))
    c.execute("SELECT n.*, u.profile_pic FROM notifications n JOIN users u ON n.actor=u.username WHERE n.username=%s ORDER BY timestamp DESC", (current_user(),)); notifs = c.fetchall()
    conn.commit(); conn.close()
    return render_template('notifications.html', notifications=notifs, current_user=current_user())

#... KEEP ALL YOUR OTHER ROUTES: dm, friends, search, profile, trending, following_feed...

# ========== ADMIN PANEL ==========
@app.route('/admin')
def admin_panel():
    if 'username' not in session: return redirect('/login')
    if not session.get('is_admin'): return "Access Denied CEO Only", 403
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT id, username, verified, banned, followers, total_likes, profile_pic FROM users ORDER BY id DESC")
    users = c.fetchall()
    c.execute("SELECT * FROM videos ORDER BY timestamp DESC")
    videos = c.fetchall()
    conn.close()
    return render_template('admin.html', users=users, videos=videos)

@app.route('/admin/ban/<username>')
def admin_ban(username):
    if not session.get('is_admin'): return "Nope", 403
    conn = get_db(); c = conn.cursor()
    c.execute("UPDATE users SET banned = 1 WHERE username=%s", (username,))
    conn.commit(); conn.close()
    return redirect('/admin')

@app.route('/admin/unban/<username>')
def admin_unban(username):
    if not session.get('is_admin'): return "Nope", 403
    conn = get_db(); c = conn.cursor()
    c.execute("UPDATE users SET banned = 0 WHERE username=%s", (username,))
    conn.commit(); conn.close()
    return redirect('/admin')

@app.route('/admin/verify/<username>')
def admin_verify(username):
    if not session.get('is_admin'): return "Nope", 403
    conn = get_db(); c = conn.cursor()
    c.execute("UPDATE users SET verified = 1 WHERE username=%s", (username,))
    conn.commit(); conn.close()
    return redirect('/admin')

@app.route('/admin/unverify/<username>')
def admin_unverify(username):
    if not session.get('is_admin'): return "Nope", 403
    conn = get_db(); c = conn.cursor()
    c.execute("UPDATE users SET verified = 0 WHERE username=%s", (username,))
    conn.commit(); conn.close()
    return redirect('/admin')

@app.route('/admin/delete_video/<int:video_id>')
def admin_delete_video(video_id):
    if not session.get('is_admin'): return "Nope", 403
    conn = get_db(); c = conn.cursor()
    c.execute("DELETE FROM videos WHERE id=%s", (video_id,))
    conn.commit(); conn.close()
    return redirect('/admin')
    # ========== STORIES ==========
@app.route('/stories')
def stories():
    if 'username' not in session: return redirect('/login')
    conn = get_db(); c = conn.cursor()
    # Delete stories older than 24 hours
    c.execute("DELETE FROM stories WHERE timestamp < %s", (time.time() - 86400,))
    # Get stories from people you follow + yourself
    c.execute("SELECT following FROM following WHERE follower=%s", (current_user(),)); following = [r['following'] for r in c.fetchall()]
    following.append(current_user())
    placeholders = ','.join(['%s'] * len(following))
    c.execute(f"SELECT s.*, u.profile_pic FROM stories s JOIN users u ON s.username=u.username WHERE s.username IN ({placeholders}) ORDER BY timestamp ASC", tuple(following))
    stories = c.fetchall()
    conn.commit(); conn.close()
    return render_template('stories.html', stories=stories, current_user=current_user())

@app.route('/add_story', methods=['GET', 'POST'])
def add_story():
    if 'username' not in session: return redirect('/login')
    if request.method == 'POST':
        file = request.files['file']
        if file and allowed_file(file.filename):
            upload_result = cloudinary.uploader.upload(file, resource_type="auto", folder="minitik_stories")
            story_url = upload_result['secure_url']
            conn = get_db(); c = conn.cursor()
            c.execute("INSERT INTO stories (username, video, timestamp) VALUES (%s,%s,%s)",
                (current_user(), story_url, time.time()))
            conn.commit(); conn.close()
            return redirect('/stories')
    return render_template('add_story.html')

@app.route('/view_story/<int:story_id>')
def view_story(story_id):
    if 'username' not in session: return redirect('/login')
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT s.*, u.profile_pic, u.username FROM stories s JOIN users u ON s.username=u.username WHERE s.id=%s", (story_id,))
    story = c.fetchone()
    conn.close()
    return render_template('view_story.html', story=story)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)