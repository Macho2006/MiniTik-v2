from flask import Flask, render_template, request, redirect, session, url_for, flash, jsonify, make_response
import os
import time
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
from psycopg2.extras import RealDictCursor
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import cloudinary, cloudinary.uploader
from datetime import datetime, timedelta # FIXED: added timedelta
from werkzeug.middleware.proxy_fix import ProxyFix
from functools import wraps
from flask import abort, flash, redirect, url_for

def verified_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('login'))
        if not current_user.is_verified:  # if your column is "verified" change to current_user.verified
            flash('You must be verified to access monetization features', 'error')
            return redirect(url_for('profile', username=current_user.username))
        return f(*args, **kwargs)
    return decorated_function

app = Flask(__name__)
app.config['SESSION_PERMANENT'] = True
app.secret_key = 'your_secret'
app.config['PREFERRED_URL_SCHEME'] = 'https' # FIX 1: Force https urls on Render
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1) # FIX 2: Added x_prefix=1
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'minitik_secret_key_2026_change_this')

# ===== FINAL COOKIE FIX FOR RENDER V5 =====
is_prod = os.environ.get('RENDER') == 'true'

app.config['REMEMBER_COOKIE_DURATION'] = timedelta(days=30)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_DOMAIN'] = None

if is_prod:
    app.config['REMEMBER_COOKIE_NAME'] = 'minitik_remember_v3' # BUMPED TO V3
    app.config['SESSION_COOKIE_NAME'] = 'minitik_session_v3' # BUMPED TO V3
    app.config['REMEMBER_COOKIE_SAMESITE'] = 'None'
    app.config['REMEMBER_COOKIE_SECURE'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_SECURE'] = True
    app.config['SESSION_COOKIE_DOMAIN'] = None
else:
    app.config['REMEMBER_COOKIE_NAME'] = 'minitik_remember_v3' # BUMPED TO V3
    app.config['SESSION_COOKIE_NAME'] = 'minitik_session_v3' # BUMPED TO V3
    app.config['REMEMBER_COOKIE_SAMESITE'] = 'Lax'
    app.config['REMEMBER_COOKIE_SECURE'] = False
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_SECURE'] = False
# ===== END FIX =====
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# ===== NEW: FIX API 302 REDIRECT TO 401 JSON =====
@login_manager.unauthorized_handler
def unauthorized():
    # If it's an API call, return JSON 401 instead of redirecting
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Unauthorized', 'count': 0}), 401
    return redirect(url_for('login'))
# ===== END NEW =====

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

    # ===== NEW: CREATOR FUND TABLES =====
    c.execute('''CREATE TABLE IF NOT EXISTS creator_earnings(
        id SERIAL PRIMARY KEY,
        username TEXT,
        video_id INTEGER,
        views INTEGER DEFAULT 0,
        rpm REAL DEFAULT 0.02,
        earnings REAL DEFAULT 0,
        month TEXT,
        timestamp REAL,
        UNIQUE(username, video_id, month)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS video_views(
        id SERIAL PRIMARY KEY,
        video_id INTEGER,
        viewer_ip TEXT,
        timestamp REAL
    )''')
    # ===== END NEW =====
        # ===== MONETIZATION TABLES =====
    c.execute('''CREATE TABLE IF NOT EXISTS coins(
        id SERIAL PRIMARY KEY,
        username TEXT UNIQUE,
        balance INTEGER DEFAULT 0
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS transactions(
        id SERIAL PRIMARY KEY,
        username TEXT,
        type TEXT, -- 'buy_coins', 'gift_sent', 'withdraw'
        amount REAL,
        currency TEXT, -- 'NGN', 'USD', 'USDT'
        gateway TEXT, -- 'demo', 'paystack', 'stripe'
        reference TEXT,
        status TEXT DEFAULT 'pending',
        timestamp REAL
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS withdrawals(
        id SERIAL PRIMARY KEY,
        username TEXT,
        amount_usd REAL,
        method TEXT, -- 'bank', 'usdt'
        bank_details TEXT,
        usdt_wallet TEXT,
        status TEXT DEFAULT 'pending',
        timestamp REAL
    )''')
    # ===== END MONETIZATION =====

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

# ===== FINAL LOGIN ROUTE FOR RENDER =====
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = clean_username(request.form['username'])
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username=%s", (username,))
        user = c.fetchone(); conn.close()
        if user and check_password_hash(user['password_hash'], request.form['password']):
            if user['banned']: flash('You are banned'); return redirect('/login')
            user_obj = User(user['id'], user['username'], user['is_admin'], user['profile_pic'])
            login_user(user_obj, remember=True, duration=timedelta(days=30)) # KEY: pass duration here
            flash(f'Welcome back {user["username"]}!')
            return redirect('/')
        flash('Invalid login')
    return render_template('login.html')
# ===== END FIXED LOGIN =====

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect('/login')

# ===== NEW: DEBUG ROUTE =====
@app.route('/whoami')
@login_required
def whoami():
    return f"Logged in as: {current_user.username} | ID: {current_user.id} | Session: {session.get('user_id')}"
# ===== END DEBUG ROUTE =====

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        action = request.form.get('action')
        conn = get_db(); c = conn.cursor()

        # FORM 1: UPLOAD PFP
        if action == 'upload_pfp':
            file = request.files.get('profile_pic')
            if file and allowed_file(file.filename):
                upload_result = cloudinary.uploader.upload(file, folder="minitik_pfps")
                pic_url = upload_result['secure_url']
                c.execute("UPDATE users SET profile_pic=%s WHERE username=%s", (pic_url, current_user.username))
                conn.commit(); conn.close()
                flash('Profile picture updated!')
                return redirect('/settings')
            else:
                flash('Invalid file type')

        # FORM 2: UPDATE USERNAME + BIO - NEW
        elif action == 'update_info':
            new_username = clean_username(request.form.get('username'))
            new_bio = request.form.get('bio', '')

            # Check if username is taken
            c.execute("SELECT 1 FROM users WHERE username=%s AND username!=%s", (new_username, current_user.username))
            if c.fetchone():
                flash('Username already taken')
            else:
                c.execute("UPDATE users SET username=%s, bio=%s WHERE username=%s", (new_username, new_bio, current_user.username))
                conn.commit()
                flash('Profile updated!')
                # Need to logout and login again for username change to reflect
                logout_user()
                return redirect('/login')

        conn.close()
        return redirect('/settings')

    # Add bio to current_user so template can use it
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT bio FROM users WHERE username=%s", (current_user.username,))
    user_data = c.fetchone()
    conn.close()
    current_user.bio = user_data['bio'] if user_data else ''

    return render_template('settings.html')
@app.route('/')
@app.route('/foryou')
@login_required
def index():
    conn = get_db(); c = conn.cursor()
    c.execute("""
        SELECT v.*, u.profile_pic, u.verified,
        (SELECT COUNT(*) FROM comments WHERE video_id=v.id) as comment_count
        FROM videos v JOIN users u ON v.username=u.username ORDER BY timestamp DESC
    """)
    videos = c.fetchall()

    # NEW: GET VIDEOS YOU ALREADY LIKED
    c.execute("SELECT video_id FROM likes WHERE username=%s", (current_user.username,))
    liked_video_ids = [r['video_id'] for r in c.fetchall()]

    twenty_four_hours_ago = time.time() - (24 * 60 * 60)
    c.execute("SELECT DISTINCT ON (s.username) s.*, u.profile_pic FROM stories s JOIN users u ON s.username=u.username WHERE s.timestamp > %s ORDER BY s.username, s.timestamp DESC", (twenty_four_hours_ago,))
    stories = c.fetchall()
    c.execute("SELECT following FROM following WHERE follower=%s", (current_user.username,))
    following = [r['following'] for r in c.fetchall()]
    conn.close()
    return render_template('index.html', videos=videos, stories=stories, current_user=current_user.username, following=following, liked_video_ids=liked_video_ids, tab='foryou')

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
    # NEW: GET VIDEOS YOU ALREADY LIKED
    c.execute("SELECT video_id FROM likes WHERE username=%s", (current_user.username,))
    liked_video_ids = [r['video_id'] for r in c.fetchall()]
    # NEW: GET FOLLOWING LIST FOR BUTTON STATE
    c.execute("SELECT following FROM following WHERE follower=%s", (current_user.username,))
    following = [r['following'] for r in c.fetchall()]
    conn.close()
    return render_template('index.html', videos=videos, current_user=current_user.username, following=following, liked_video_ids=liked_video_ids, tab='following')


@app.route('/trending')
def trending():
    conn = get_db(); c = conn.cursor()
    c.execute("""
        SELECT v.*, u.profile_pic, u.verified,
        (SELECT COUNT(*) FROM comments WHERE video_id=v.id) as comment_count
        FROM videos v JOIN users u ON v.username=u.username ORDER BY likes DESC LIMIT 20
    """)
    videos = c.fetchall()
    # NEW: GET VIDEOS YOU ALREADY LIKED
    liked_video_ids = []
    following = []
    if current_user.is_authenticated:
        c.execute("SELECT video_id FROM likes WHERE username=%s", (current_user.username,))
        liked_video_ids = [r['video_id'] for r in c.fetchall()]
        c.execute("SELECT following FROM following WHERE follower=%s", (current_user.username,))
        following = [r['following'] for r in c.fetchall()]
    conn.close()
    return render_template('index.html', videos=videos, current_user=current_user.username if current_user.is_authenticated else '', following=following, liked_video_ids=liked_video_ids, tab='trending')

# ===== PROFILE ROUTES - FIXED FOR DASHBOARD =====
# FIX 1: /profile redirects to logged in user's profile
@app.route('/profile')
@login_required
def my_profile_redirect():
    return redirect(url_for('profile', username=current_user.username))

# FIX 2: /profile/ with slash also redirects
@app.route('/profile/')
@login_required
def my_profile_redirect_slash():
    return redirect(url_for('profile', username=current_user.username))

# THIS IS THE ONLY /profile/<username> ROUTE NOW - PUBLIC
@app.route('/profile/<username>')
def profile(username): # REMOVED @login_required SO OTHERS CAN VIEW
    # CLEAN URL: remove %20 %2C commas and spaces
    username = username.replace('%20', ' ').replace('%2C', '').replace(',', '').strip()
    
    conn = get_db(); c = conn.cursor()
    
    # Get user
    c.execute("SELECT * FROM users WHERE username=%s", (username,))
    user = c.fetchone()
    if not user:
        conn.close()
        return "User not found", 404

    # Get videos
    c.execute("SELECT * FROM videos WHERE username=%s ORDER BY id DESC", (username,))
    videos = c.fetchall()
    
    # Calculate total likes from all videos
    total_likes = sum([v['likes'] for v in videos]) if videos else 0
    user['total_likes'] = total_likes
    
    # Get following count
    c.execute("SELECT COUNT(*) as count FROM following WHERE follower=%s", (username,))
    following_count = c.fetchone()['count']
    
    # Get followers count - real count from DB
    c.execute("SELECT COUNT(*) as count FROM following WHERE following=%s", (username,))
    followers_count = c.fetchone()['count']
    user['followers'] = followers_count
    
    # Check if current user is logged in and following this profile
    current_username = current_user.username if current_user.is_authenticated else None
    is_following = False
    if current_username:
        c.execute("SELECT 1 FROM following WHERE follower=%s AND following=%s", (current_username, username))
        is_following = c.fetchone() is not None
    
    conn.close()
    return render_template('profile.html', 
        user=user, 
        videos=videos, 
        is_following=is_following, 
        following_count=following_count, 
        current_user=current_username # FIXED TYPO: was currennt_user
    )
# ===== END PROFILE ROUTES =====

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

# ===== NEW: AJAX FOLLOW ROUTE FOR BUTTON ON POSTS =====
@app.route('/follow_ajax/<username>')
@login_required
def follow_ajax(username):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT 1 FROM following WHERE follower=%s AND following=%s", (current_user.username, username)); exists = c.fetchone()
    if exists:
        c.execute("DELETE FROM following WHERE follower=%s AND following=%s", (current_user.username, username))
        c.execute("UPDATE users SET followers = followers - 1 WHERE username=%s", (username,))
        status = 'unfollowed'
    else:
        c.execute("INSERT INTO following VALUES (%s,%s)", (current_user.username, username))
        c.execute("UPDATE users SET followers = followers + 1 WHERE username=%s", (username,))
        create_notification(username, current_user.username, 'follow', 0, f'{current_user.username} started following you')
        status = 'followed'
    conn.commit(); conn.close();
    return jsonify({'status': status})
# ===== END NEW =====

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

            upload_result = cloudinary.uploader.upload(
                file,
                resource_type=resource_type,
                folder="minitik_videos",
                quality="auto", # auto compress for speed
                fetch_format="auto" # webp/mp4
            )
            file_url = upload_result['secure_url']

            conn = get_db(); c = conn.cursor()
            c.execute("INSERT INTO videos (username, video, caption, timestamp, filter, type) VALUES (%s,%s,%s,%s,%s,%s)",
                      (current_user.username, file_url, caption, time.time(), filter_choice, resource_type))
            conn.commit(); conn.close()
            flash('Posted!')
            return redirect('/')
        except Exception as e:
            flash(f'Upload failed: {str(e)}')

    return render_template('upload.html', filters=FILTERS)
# ===== END FIXED UPLOAD =====

# ===== FIXED STORY UPLOAD ROUTE WITH ERROR HANDLING =====
@app.route('/story/upload', methods=['GET', 'POST'])
@login_required
def story_upload():
    if request.method == 'POST':
        file = request.files.get('story')
        if not file or not allowed_file(file.filename):
            flash('Invalid file type')
            return render_template('story_upload.html')
        try:
            ext = file.filename.rsplit('.', 1)[1].lower() # ADDED
            resource_type = "video" if ext in ['mp4', 'mov', 'avi'] else "image" # ADDED

            upload_result = cloudinary.uploader.upload(
                file,
                resource_type=resource_type, # FIXED: was hardcoded "video"
                folder="minitik_stories",
                quality="auto", # ADDED FOR SPEED
                fetch_format="auto" # ADDED FOR SPEED
            )
            story_url = upload_result['secure_url']
            conn = get_db(); c = conn.cursor()
            c.execute("INSERT INTO stories (username, video, timestamp) VALUES (%s,%s,%s)",
                      (current_user.username, story_url, time.time()))
            conn.commit(); conn.close()
            flash('Story posted!')
            return redirect('/')
        except Exception as e:
            flash(f'Story upload failed: {str(e)}') # NEW: show real error
            return render_template('story_upload.html')
    return render_template('story_upload.html')
# ===== END FIXED STORY UPLOAD =====

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

# ===== FIXED: AJAX LIKE ROUTE =====
@app.route('/like/<int:video_id>')
@login_required
def like(video_id):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT 1 FROM likes WHERE video_id=%s AND username=%s", (video_id, current_user.username))
    liked = c.fetchone()

    if liked:
        c.execute("DELETE FROM likes WHERE video_id=%s AND username=%s", (video_id, current_user.username))
        c.execute("UPDATE videos SET likes = likes - 1 WHERE id=%s", (video_id,))
        status = 'unliked'
    else:
        c.execute("INSERT INTO likes VALUES (%s,%s)", (video_id, current_user.username))
        c.execute("UPDATE videos SET likes = likes + 1 WHERE id=%s", (video_id,))
        c.execute("SELECT username FROM videos WHERE id=%s", (video_id,))
        owner = c.fetchone()['username']
        create_notification(owner, current_user.username, 'like', video_id, f'{current_user.username} liked your video')
        status = 'liked'

    c.execute("SELECT likes FROM videos WHERE id=%s", (video_id,))
    new_count = c.fetchone()['likes']
    conn.commit(); conn.close()
    return jsonify({'status': status, 'likes': new_count})
# ===== END FIXED LIKE =====

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
    return render_template('search.html', q=q, users=users, videos=videos, tab='search')

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

# ===== NEW: COMBINED INBOX + NOTIFICATIONS ROUTE =====
@app.route('/inbox')
@login_required
def inbox():
    conn = get_db(); c = conn.cursor()

    # GET CHATS
    c.execute("""
        SELECT DISTINCT ON (friend)
        CASE WHEN sender=%s THEN receiver ELSE sender END as friend,
        message, timestamp
        FROM messages WHERE sender=%s OR receiver=%s
        ORDER BY friend, timestamp DESC
    """, (current_user.username, current_user.username, current_user.username))
    chats = c.fetchall()

    # GET NOTIFICATIONS
    c.execute("SELECT * FROM notifications WHERE username=%s ORDER BY timestamp DESC LIMIT 50", (current_user.username,))
    notifications = c.fetchall()
    c.execute("UPDATE notifications SET is_read=1 WHERE username=%s", (current_user.username,))

    conn.commit(); conn.close()
    return render_template('inbox.html', chats=chats, notifications=notifications, tab='inbox')
# ===== END NEW =====

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

@app.route('/following_list') # FIXED: Renamed from /following to avoid conflict
@login_required
def following_list(): # FIXED: Function name was 'following'
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT u.* FROM users u JOIN following f ON u.username=f.following WHERE f.follower=%s", (current_user.username,))
    following = c.fetchall()
    conn.close()
    return render_template('following.html', users=following)

@app.route('/notifications')
@login_required
def notifications():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM notifications WHERE username=%s ORDER BY timestamp DESC LIMIT 50", (current_user.username,))
    notifs = c.fetchall()
    c.execute("UPDATE notifications SET is_read=1 WHERE username=%s", (current_user.username,))
    conn.commit(); conn.close()
    return render_template('notifications.html', notifications=notifs, tab='notif') # ADDED tab

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

# ===== NEW: REAL TIME CHAT API ROUTES =====
@app.route('/dm_send/<username>', methods=['POST'])
@login_required
def dm_send(username):
    username = clean_username(username)
    msg = request.form.get('message', '')
    if msg.strip():
        conn = get_db(); c = conn.cursor()
        c.execute("INSERT INTO messages (sender, receiver, message, timestamp) VALUES (%s,%s,%s,%s)",
                  (current_user.username, username, msg, time.time()))
        create_notification(username, current_user.username, 'message', 0, f'{current_user.username} sent you a message')
        conn.commit(); conn.close()
        return jsonify({'status': 'ok'})
    return jsonify({'status': 'error'})

@app.route('/dm_get/<username>')
@login_required
def dm_get(username):
    username = clean_username(username)
    last_id = request.args.get('last_id', 0, type=int)
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM messages WHERE ((sender=%s AND receiver=%s) OR (sender=%s AND receiver=%s)) AND id > %s ORDER BY timestamp",
              (current_user.username, username, username, current_user.username, last_id))
    messages = c.fetchall()
    conn.close()
    return jsonify(messages)
# ===== END REAL TIME CHAT API =====

# ===== NEW: REAL TIME NOTIFICATIONS API =====
@app.route('/api/notifications_count')
@login_required
def notifications_count():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT COUNT(*) as count FROM notifications WHERE username=%s AND is_read=0", (current_user.username,))
    count = c.fetchone()['count']
    conn.close()
    return jsonify({'count': count})

@app.route('/api/notifications')
@login_required
def api_notifications():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM notifications WHERE username=%s ORDER BY timestamp DESC LIMIT 10", (current_user.username,))
    notifs = c.fetchall()
    conn.close()
    return jsonify(notifs)
# ===== END REAL TIME NOTIFICATIONS API =====

# ===== NEW: REAL TIME FEED API =====
@app.route('/api/feed')
@login_required
def api_feed():
    tab = request.args.get('tab', 'foryou')
    last_id = request.args.get('last_id', 0, type=int)
    conn = get_db(); c = conn.cursor()

    if tab == 'following':
        c.execute("""
            SELECT v.*, u.profile_pic, u.verified,
            (SELECT COUNT(*) FROM comments WHERE video_id=v.id) as comment_count
            FROM videos v JOIN users u ON v.username=u.username
            WHERE v.username IN (SELECT following FROM following WHERE follower=%s) AND v.id > %s
            ORDER BY timestamp DESC LIMIT 10
        """, (current_user.username, last_id))
    elif tab == 'trending':
        c.execute("""
            SELECT v.*, u.profile_pic, u.verified,
            (SELECT COUNT(*) FROM comments WHERE video_id=v.id) as comment_count
            FROM videos v JOIN users u ON v.username=u.username WHERE v.id > %s
            ORDER BY likes DESC LIMIT 10
        """, (last_id,))
    else: # foryou
        c.execute("""
            SELECT v.*, u.profile_pic, u.verified,
            (SELECT COUNT(*) FROM comments WHERE video_id=v.id) as comment_count
            FROM videos v JOIN users u ON v.username=u.username WHERE v.id > %s
            ORDER BY timestamp DESC LIMIT 10
        """, (last_id,))
    videos = c.fetchall()
    conn.close()
    return jsonify(videos)
# ===== END REAL TIME FEED API =====

@app.route('/video/<int:video_id>')
def single_video(video_id):
    viewer_ip = request.remote_addr
    today = time.time() - (24 * 60 * 60)

    conn = get_db(); c = conn.cursor()

    # 1. CHECK IF THIS IP ALREADY VIEWED TODAY
    c.execute("SELECT 1 FROM video_views WHERE video_id=%s AND viewer_ip=%s AND timestamp > %s", (video_id, viewer_ip, today))
    if not c.fetchone():
        # NEW VIEW - ADD IT
        c.execute("INSERT INTO video_views (video_id, viewer_ip, timestamp) VALUES (%s,%s,%s)", (video_id, viewer_ip, time.time()))

        # UPDATE CREATOR EARNINGS
        c.execute("SELECT username FROM videos WHERE id=%s", (video_id,))
        owner = c.fetchone()
        if owner:
            month = datetime.now().strftime('%Y-%m')
            c.execute("INSERT INTO creator_earnings (username, video_id, views, month, timestamp) VALUES (%s,%s,1,%s,%s) ON CONFLICT DO NOTHING", (owner['username'], video_id, month, time.time()))
            c.execute("UPDATE creator_earnings SET views = views + 1, earnings = views * rpm WHERE video_id=%s AND month=%s", (video_id, month))

    # 2. GET VIDEO DATA
    c.execute("""
        SELECT v.*, u.profile_pic, u.verified,
        (SELECT COUNT(*) FROM comments WHERE video_id=v.id) as comment_count
        FROM videos v JOIN users u ON v.username=u.username WHERE v.id=%s
    """, (video_id,))
    video = c.fetchone()
    conn.commit(); conn.close()
    return render_template('index.html', videos=[video])

@app.route('/monetization')
@verified_required
def monetization():
    conn = get_db(); c = conn.cursor()
    
    # 1. Get this month earnings
    month = datetime.now().strftime('%Y-%m')
    c.execute("SELECT SUM(earnings) as earnings FROM creator_earnings WHERE username=%s AND month=%s", (current_user.username, month))
    stats = c.fetchone()
    total_earnings = round(stats['earnings'] if stats['earnings'] else 0, 2)

    # 2. Get coin balance
    c.execute("SELECT balance FROM coins WHERE username=%s", (current_user.username,))
    coins = c.fetchone()
    balance = coins['balance'] if coins else 0

    # 3. Get pending withdrawals
    c.execute("SELECT * FROM withdrawals WHERE username=%s ORDER BY timestamp DESC LIMIT 5", (current_user.username,))
    withdrawals = c.fetchall()
    
    conn.close()
    return render_template('monetization.html', total_earnings=total_earnings, balance=balance, withdrawals=withdrawals)

# ===== COINS + WITHDRAW - DEMO MODE =====
@app.route('/coins')
@login_required
def coins():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT balance FROM coins WHERE username=%s", (current_user.username,))
    coins = c.fetchone()
    balance = coins['balance'] if coins else 0
    conn.close()
    return render_template('coins.html', balance=balance)

@app.route('/buy_coins', methods=['POST'])
@login_required
def buy_coins():
    coins = int(request.form['coins'])
    
    # DEMO MODE: Just add coins directly
    conn = get_db(); c = conn.cursor()
    c.execute("INSERT INTO coins (username, balance) VALUES (%s,%s) ON CONFLICT (username) DO UPDATE SET balance = coins.balance + %s", 
              (current_user.username, coins, coins))
    c.execute("INSERT INTO transactions (username, type, amount, currency, gateway, status, timestamp) VALUES (%s,'buy_coins',%s,'NGN','demo','success',%s)",
              (current_user.username, coins, time.time()))
    conn.commit(); conn.close()
    flash(f'{coins} coins added! DEMO MODE - No real payment yet', 'success')
    return redirect('/coins')

@app.route('/withdraw', methods=['GET', 'POST'])
@verified_required
def withdraw():
    if request.method == 'POST':
        amount = float(request.form['amount'])
        method = request.form['method']
        
        if amount < 10:
            flash('Minimum withdrawal is $10')
            return redirect('/withdraw')
            
        conn = get_db(); c = conn.cursor()
        c.execute("INSERT INTO withdrawals (username, amount_usd, method, bank_details, usdt_wallet, timestamp) VALUES (%s,%s,%s,%s,%s,%s)",
                  (current_user.username, amount, method, request.form.get('bank'), request.form.get('usdt'), time.time()))
        conn.commit(); conn.close()
        flash('Withdrawal request submitted! We will pay manually for now', 'success')
        return redirect('/withdraw')
    
    # Get total earnings for display
    conn = get_db(); c = conn.cursor()
    month = datetime.now().strftime('%Y-%m')
    c.execute("SELECT SUM(earnings) as earnings FROM creator_earnings WHERE username=%s AND month=%s", (current_user.username, month))
    stats = c.fetchone()
    total_earnings = round(stats['earnings'] if stats['earnings'] else 0, 2)
    conn.close()
    return render_template('withdraw.html', total_earnings=total_earnings)
# ===== END MONETIZATION ROUTES =====

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
