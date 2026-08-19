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

app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024 # Lowered to 50MB for speed
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

def clean_username(name): # NEW: stops " User" vs "User" bug
    return name.strip()

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

def delete_old_stories():
    conn = get_db(); c = conn.cursor()
    twenty_four_hours_ago = time.time() - (24 * 60 * 60)
    c.execute("DELETE FROM stories WHERE timestamp < %s", (twenty_four_hours_ago,))
    conn.commit(); conn.close()

@app.before_request
def startup():
    if not hasattr(app, 'db_initialized'):
        init_db()
        make_admin()
        delete_old_stories()
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
        username = clean_username(request.form['username']) # FIXED
        conn = get_db(); c = conn.cursor()
        try:
            c.execute("INSERT INTO users (username,password_hash,email,dob,region) VALUES (%s,%s,%s,%s,%s)",
                (username, generate_password_hash(request.form['password']), request.form['email'], request.form['dob'], request.form['region']))
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
        username = clean_username(request.form['username']) # FIXED
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username=%s", (username,))
        user = c.fetchone(); conn.close()
        if user and check_password_hash(user['password_hash'], request.form['password']):
            if user['banned']: flash('You are banned'); return redirect('/login')
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
    c.execute("""
        SELECT v.*, u.profile_pic, u.verified,
        (SELECT COUNT(*) FROM comments WHERE video_id=v.id) as comment_count
        FROM videos v JOIN users u ON v.username=u.username ORDER BY timestamp DESC
    """)
    videos = c.fetchall()
    twenty_four_hours_ago = time.time() - (24 * 60 * 60)
    c.execute("SELECT DISTINCT ON (s.username) s.*, u.profile_pic FROM stories s JOIN users u ON s.username=u.username WHERE s.timestamp > %s ORDER BY s.username, s.timestamp DESC", (twenty_four_hours_ago,))
    stories = c.fetchall()
    c.execute("SELECT following FROM following WHERE follower=%s", (current_user.username,))
    following = [r['following'] for r in c.fetchall()]
    conn.close()
    return render_template('index.html', videos=videos, stories=stories, current_user=current_user.username, following=following, tab='foryou') # ADDED tab

@app.route('/following')
@login_required
def following_feed(): # Renamed to avoid conflict with /following users list
    conn = get_db(); c = conn.cursor()
    c.execute("""
        SELECT v.*, u.profile_pic, u.verified,
        (SELECT COUNT(*) FROM comments WHERE video_id=v.id) as comment_count
        FROM videos v JOIN users u ON v.username=u.username 
        WHERE v.username IN (SELECT following FROM following WHERE follower=%s)
        ORDER BY timestamp DESC
    """, (current_user.username,))
    videos = c.fetchall()
    conn.close()
    return render_template('index.html', videos=videos, current_user=current_user.username, tab='following') # ADDED tab

@app.route('/trending')
def trending():
    conn = get_db(); c = conn.cursor()
    c.execute("""
        SELECT v.*, u.profile_pic, u.verified,
        (SELECT COUNT(*) FROM comments WHERE video_id=v.id) as comment_count
        FROM videos v JOIN users u ON v.username=u.username ORDER BY likes DESC LIMIT 20
    """)
    videos = c.fetchall()
    conn.close()
    return render_template('index.html', videos=videos, tab='trending') # ADDED tab

@app.route('/')
@login_required
def index():
    conn = get_db(); c = conn.cursor()
    # UPDATED: Added comment_count
    c.execute("""
        SELECT v.*, u.profile_pic, u.verified,
        (SELECT COUNT(*) FROM comments WHERE video_id=v.id) as comment_count
        FROM videos v JOIN users u ON v.username=u.username ORDER BY timestamp DESC
    """)
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
    c.execute("SELECT 1 FROM following WHERE follower=%s AND following=%s", (current_user.username, username))
    is_following = c.fetchone()
    conn.close()
    return render_template('profile.html', user=user, videos=videos, is_following=is_following)

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

# ===== FIXED UPLOAD ROUTE =====
@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        file = request.files.get('video')
        caption = request.form.get('caption', '')
        filter_choice = request.form.get('filter', 'None')

        if not file or not allowed_file(file.filename):
            flash('Invalid file type')
            return render_template('upload.html', filters=FILTERS)

        try:
            ext = file.filename.rsplit('.', 1)[1].lower()
            resource_type = "video" if ext in ['mp4', 'mov', 'avi'] else "image"

            upload_result = cloudinary.uploader.upload(file, resource_type=resource_type, folder="minitik_videos")
            file_url = upload_result['secure_url']

            conn = get_db(); c = conn.cursor()
            c.execute("INSERT INTO videos (username, video, caption, timestamp, filter, type) VALUES (%s,%s,%s,%s,%s,%s)",
                      (current_user.username, file_url, caption, time.time(), filter_choice, resource_type))
            conn.commit(); conn.close()
            flash('Posted!')
            return redirect('/')
        except Exception as e:
            flash(f'Upload failed: {str(e)}')

    return render_template('upload.html', filters=FILTERS) # THIS FIXES 500
# ===== END FIXED UPLOAD =====

@app.route('/story/upload', methods=['GET', 'POST'])
@login_required
def story_upload():
    if request.method == 'POST':
        file = request.files.get('story')
        if file and allowed_file(file.filename):
            upload_result = cloudinary.uploader.upload(file, resource_type="video", folder="minitik_stories")
            story_url = upload_result['secure_url']
            conn = get_db(); c = conn.cursor()
            c.execute("INSERT INTO stories (username, video, timestamp) VALUES (%s,%s,%s)",
                      (current_user.username, story_url, time.time()))
            conn.commit(); conn.close()
            flash('Story posted!')
            return redirect('/')
    return render_template('story_upload.html')

@app.route('/story/<int:story_id>')
@login_required
def view_story(story_id):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT s.*, u.profile_pic FROM stories s JOIN users u ON s.username=u.username WHERE s.id=%s", (story_id,))
    story = c.fetchone()
    c.execute("SELECT id FROM stories WHERE id > %s ORDER BY id ASC LIMIT 1", (story_id,))
    next_id = c.fetchone()
    c.execute("SELECT id FROM stories WHERE id < %s ORDER BY id DESC LIMIT 1", (story_id,))
    prev_id = c.fetchone()
    conn.close()
    return render_template('story_view.html', story=story, next_id=next_id['id'] if next_id else None, prev_id=prev_id['id'] if prev_id else None)

@app.route('/like/<int:video_id>')
@login_required
def like(video_id):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT 1 FROM likes WHERE video_id=%s AND username=%s", (video_id, current_user.username))
    liked = c.fetchone()

    if liked:
        c.execute("DELETE FROM likes WHERE video_id=%s AND username=%s", (video_id, current_user.username))
        c.execute("UPDATE videos SET likes = likes - 1 WHERE id=%s", (video_id,))
    else:
        c.execute("INSERT INTO likes VALUES (%s,%s)", (video_id, current_user.username))
        c.execute("UPDATE videos SET likes = likes + 1 WHERE id=%s", (video_id,))
        c.execute("SELECT username FROM videos WHERE id=%s", (video_id,))
        owner = c.fetchone()['username']
        create_notification(owner, current_user.username, 'like', video_id, f'{current_user.username} liked your video')

    conn.commit(); conn.close()
    return redirect(request.referrer or '/')

@app.route('/comment/<int:video_id>', methods=['POST'])
@login_required
def comment(video_id):
    text = request.form['comment']
    if text.strip():
        conn = get_db(); c = conn.cursor()
        c.execute("INSERT INTO comments (video_id, username, comment, timestamp) VALUES (%s,%s,%s,%s)",
                  (video_id, current_user.username, text, time.time()))
        c.execute("SELECT username FROM videos WHERE id=%s", (video_id,))
        owner = c.fetchone()['username']
        create_notification(owner, current_user.username, 'comment', video_id, f'{current_user.username} commented on your video')
        conn.commit(); conn.close()
    return redirect(request.referrer or '/')

# ===== NEW: COMMENTS PAGE =====
@app.route('/comments_page/<int:video_id>')
@login_required
def comments_page(video_id):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM comments WHERE video_id=%s ORDER BY timestamp DESC", (video_id,))
    comments = c.fetchall()
    c.execute("SELECT * FROM videos WHERE id=%s", (video_id,))
    video = c.fetchone()
    conn.close()
    return render_template('comments.html', comments=comments, video=video)
# ===== END NEW =====

# ===== NEW: SINGLE VIDEO VIEW FOR SHARE =====
@app.route('/video/<int:video_id>')
def single_video(video_id):
    conn = get_db(); c = conn.cursor()
    c.execute("""
        SELECT v.*, u.profile_pic, u.verified,
        (SELECT COUNT(*) FROM comments WHERE video_id=v.id) as comment_count
        FROM videos v JOIN users u ON v.username=u.username WHERE v.id=%s
    """, (video_id,))
    video = c.fetchone()
    conn.close()
    return render_template('index.html', videos=[video])
# ===== END NEW =====

@app.route('/search')
@login_required
def search():
    q = request.args.get('q', '')
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username ILIKE %s LIMIT 10", (f'%{q}%',))
    users = c.fetchall()
    c.execute("SELECT * FROM videos WHERE caption ILIKE %s ORDER BY likes DESC LIMIT 20", (f'%{q}%',))
    videos = c.fetchall()
    conn.close()
    return render_template('search.html', q=q, users=users, videos=videos)

@app.route('/dm_inbox')
@login_required
def dm_inbox():
    conn = get_db(); c = conn.cursor()
    c.execute("""
        SELECT DISTINCT ON (friend)
        CASE WHEN sender=%s THEN receiver ELSE sender END as friend,
        message, timestamp
        FROM messages WHERE sender=%s OR receiver=%s
        ORDER BY friend, timestamp DESC
    """, (current_user.username, current_user.username, current_user.username))
    chats = c.fetchall()
    conn.close()
    return render_template('dm_inbox.html', chats=chats)

@app.route('/dm/<username>', methods=['GET', 'POST'])
@login_required
def dm_chat(username):
    username = clean_username(username) # FIXED
    if request.method == 'POST':
        msg = request.form['message']
        if msg.strip():
            conn = get_db(); c = conn.cursor()
            c.execute("INSERT INTO messages (sender, receiver, message, timestamp) VALUES (%s,%s,%s,%s)",
                      (current_user.username, username, msg, time.time()))
            create_notification(username, current_user.username, 'message', 0, f'{current_user.username} sent you a message')
            conn.commit(); conn.close()
        return redirect(f'/dm/{username}')

    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM messages WHERE (sender=%s AND receiver=%s) OR (sender=%s AND receiver=%s) ORDER BY timestamp",
              (current_user.username, username, username, current_user.username))
    messages = c.fetchall()
    conn.close()
    return render_template('dm_chat.html', messages=messages, friend=username)

@app.route('/friends')
@login_required
def friends():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT user2 as friend FROM friends WHERE user1=%s UNION SELECT user1 as friend FROM friends WHERE user2=%s",
              (current_user.username, current_user.username))
    friends = c.fetchall()
    conn.close()
    return render_template('friends.html', friends=friends)

@app.route('/following')
@login_required
def following():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT u.* FROM users u JOIN following f ON u.username=f.following WHERE f.follower=%s", (current_user.username,))
    following = c.fetchall()
    conn.close()
    return render_template('following.html', users=following)

@app.route('/trending')
def trending():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT v.*, u.profile_pic, u.verified FROM videos v JOIN users u ON v.username=u.username ORDER BY likes DESC LIMIT 20")
    videos = c.fetchall()
    conn.close()
    return render_template('trending.html', videos=videos)

@app.route('/notifications')
@login_required
def notifications():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM notifications WHERE username=%s ORDER BY timestamp DESC LIMIT 50", (current_user.username,))
    notifs = c.fetchall()
    c.execute("UPDATE notifications SET is_read=1 WHERE username=%s", (current_user.username,))
    conn.commit(); conn.close()
    return render_template('notifications.html', notifications=notifs)

@app.route('/admin')
@login_required
def admin():
    if not current_user.is_admin:
        return "Access Denied", 403
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM users ORDER BY id DESC")
    users = c.fetchall()
    c.execute("SELECT * FROM videos ORDER BY id DESC LIMIT 50")
    videos = c.fetchall()
    c.execute("SELECT * FROM support_tickets ORDER BY timestamp DESC")
    tickets = c.fetchall()
    conn.close()
    return render_template('admin.html', users=users, videos=videos, tickets=tickets)

@app.route('/admin/ban/<username>')
@login_required
def ban_user(username):
    if not current_user.is_admin: return "Access Denied", 403
    conn = get_db(); c = conn.cursor()
    c.execute("UPDATE users SET banned=1 WHERE username=%s", (username,))
    conn.commit(); conn.close()
    return redirect('/admin')

@app.route('/admin/verify/<username>')
@login_required
def verify_user(username):
    if not current_user.is_admin: return "Access Denied", 403
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT verified FROM users WHERE username=%s", (username,))
    current = c.fetchone()['verified']
    new_status = 0 if current else 1
    c.execute("UPDATE users SET verified=%s WHERE username=%s", (new_status, username))
    conn.commit(); conn.close()
    flash(f'{"Verified" if new_status else "Unverified"} {username}')
    return redirect('/admin')

@app.route('/admin/delete_video/<int:video_id>')
@login_required
def delete_video(video_id):
    if not current_user.is_admin: return "Access Denied", 403
    conn = get_db(); c = conn.cursor()
    c.execute("DELETE FROM videos WHERE id=%s", (video_id,))
    conn.commit(); conn.close()
    return redirect('/admin')

@app.route('/support', methods=['GET', 'POST'])
@login_required
def support():
    if request.method == 'POST':
        issue = request.form['issue']
        conn = get_db(); c = conn.cursor()
        c.execute("INSERT INTO support_tickets (username, issue, timestamp) VALUES (%s,%s,%s)",
                  (current_user.username, issue, time.time()))
        conn.commit(); conn.close()
        flash('Ticket submitted!')
        return redirect('/support')
    return render_template('support.html')

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
