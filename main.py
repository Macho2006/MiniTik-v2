from flask import Flask, render_template, request, redirect, session, url_for, flash, jsonify
import os
import time
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
from psycopg2.extras import RealDictCursor
from flask_session import Session
import cloudinary, cloudinary.uploader

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024 # 100MB max
app.secret_key = os.environ.get('SECRET_KEY', 'minitik_secret_key_2026_change_this')
app.config['SESSION_TYPE'] = 'filesystem'
Session(app)

cloudinary.config(
  cloud_name = os.environ.get('CLOUD_NAME'),
  api_key = os.environ.get('CLOUD_API_KEY'),
  api_secret = os.environ.get('CLOUD_API_SECRET')
)
import psycopg2

DATABASE_URL = os.environ.get('DATABASE_URL')

def create_tables():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY, 
            username VARCHAR(50) UNIQUE, 
            password_hash VARCHAR(200)
        );
        CREATE TABLE IF NOT EXISTS videos (
            id SERIAL PRIMARY KEY, 
            user_id INT REFERENCES users(id), 
            video_url TEXT, 
            caption TEXT, 
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    conn.commit()
    cur.close()
    conn.close()
    print("Tables created/checked ✅")

create_tables()

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
    c.execute('''CREATE TABLE IF NOT EXISTS users(
        id SERIAL PRIMARY KEY, username TEXT UNIQUE, password TEXT, email TEXT UNIQUE,
        dob TEXT, region TEXT, bio TEXT DEFAULT '', banned INTEGER DEFAULT 0,
        verified INTEGER DEFAULT 0, pro_mode INTEGER DEFAULT 0,
        followers INTEGER DEFAULT 0, total_likes INTEGER DEFAULT 0, is_admin BOOLEAN DEFAULT FALSE
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS videos(id SERIAL PRIMARY KEY, username TEXT, video TEXT, caption TEXT, likes INTEGER DEFAULT 0, timestamp REAL, type TEXT DEFAULT 'video', filter TEXT DEFAULT 'None')''')
    c.execute('''CREATE TABLE IF NOT EXISTS likes(video_id INTEGER, username TEXT, PRIMARY KEY(video_id, username))''')
    c.execute('''CREATE TABLE IF NOT EXISTS following(follower TEXT, following TEXT, PRIMARY KEY(follower, following))''')
    c.execute('''CREATE TABLE IF NOT EXISTS comments(id SERIAL PRIMARY KEY, video_id INTEGER, username TEXT, comment TEXT, timestamp REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS stories(id SERIAL PRIMARY KEY, username TEXT, video TEXT, timestamp REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS pages(id SERIAL PRIMARY KEY, owner TEXT, page_name TEXT, followers INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS support_tickets(id SERIAL PRIMARY KEY, username TEXT, issue TEXT, timestamp REAL, status TEXT DEFAULT 'Open')''')
    c.execute('''CREATE TABLE IF NOT EXISTS messages(id SERIAL PRIMARY KEY, sender TEXT, receiver TEXT, message TEXT, timestamp REAL, read INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS friends(user1 TEXT, user2 TEXT, PRIMARY KEY(user1, user2))''')
    conn.commit()
    conn.close()

init_db()

def current_user(): return session.get('username')

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
            return redirect('/')
        flash('Invalid login')
    return render_template('login.html')

@app.route('/logout')
def logout(): session.clear(); return redirect('/login')

# ========== MAIN FEEDS ==========
@app.route('/')
def index():
    if 'username' not in session: return redirect('/login')
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM videos ORDER BY timestamp DESC"); videos = c.fetchall()
    c.execute("SELECT following FROM following WHERE follower=%s", (current_user(),)); following = [r['following'] for r in c.fetchall()]
    conn.close()
    return render_template('index.html', videos=videos, current_user=current_user(), following=following, tab='foryou')

@app.route('/following')
def following_feed():
    if 'username' not in session: return redirect('/login')
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT following FROM following WHERE follower=%s", (current_user(),)); following = [r['following'] for r in c.fetchall()]
    videos = []
    if following:
        placeholders = ','.join(['%s'] * len(following))
        c.execute(f"SELECT * FROM videos WHERE username IN ({placeholders}) ORDER BY timestamp DESC", tuple(following)); videos = c.fetchall()
    conn.close()
    return render_template('index.html', videos=videos, current_user=current_user(), following=following, tab='following')

@app.route('/trending')
def trending():
    if 'username' not in session: return redirect('/login')
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM videos ORDER BY likes DESC, timestamp DESC LIMIT 20"); videos = c.fetchall()
    c.execute("SELECT following FROM following WHERE follower=%s", (current_user(),)); following = [r['following'] for r in c.fetchall()]
    conn.close()
    return render_template('index.html', videos=videos, current_user=current_user(), following=following, tab='trending')

# ========== PROFILE + DASHBOARD ==========
@app.route('/profile/<username>')
def profile(username):
    if 'username' not in session: return redirect('/login')
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username=%s", (username,)); user = c.fetchone()
    c.execute("SELECT * FROM videos WHERE username=%s ORDER BY timestamp DESC", (username,)); videos = c.fetchall()
    c.execute("SELECT COUNT(*) FROM following WHERE follower=%s", (username,)); following_count = c.fetchone()['count']
    c.execute("SELECT 1 FROM following WHERE follower=%s AND following=%s", (current_user(), username)); is_following = c.fetchone()
    conn.close()
    return render_template('profile.html', user=user, videos=videos, is_following=is_following, following=following_count, current_user=current_user())

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
    conn.commit(); conn.close(); return redirect(f'/profile/{username}')

# ========== COMMENTS ==========
@app.route('/comments/<int:video_id>', methods=['GET', 'POST'])
def comments(video_id):
    if 'username' not in session: return redirect('/login')
    conn = get_db(); c = conn.cursor()
    if request.method == 'POST':
        c.execute("INSERT INTO comments (video_id, username, comment, timestamp) VALUES (%s,%s,%s,%s)",
                  (video_id, current_user(), request.form['comment'], time.time())); conn.commit()
    c.execute("SELECT * FROM comments WHERE video_id=%s ORDER BY timestamp DESC", (video_id,)); comments = c.fetchall()
    conn.close()
    return render_template('comments.html', comments=comments, video_id=video_id)

# ========== UPLOAD WITH CLOUDINARY - FIXED ==========
@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if 'username' not in session: return redirect('/login')
    if request.method == 'POST':
        file = request.files['file']
        caption = request.form['caption']
        filter_type = request.form['filter']
        
        if file and allowed_file(file.filename):
            # Upload using file.stream so Render doesn't crash
            upload_result = cloudinary.uploader.upload(
                file.stream, 
                resource_type="auto",
                chunk_size=6000000 # 6MB chunks for big videos
            )
            file_url = upload_result['secure_url']
            ext = file.filename.rsplit('.', 1)[1].lower()
            file_type = 'image' if ext in ['jpg', 'jpeg', 'png', 'gif'] else 'video'

            conn = get_db()
            c = conn.cursor()
            # 6 columns = 6 %s. Use time.time() because timestamp is REAL
            c.execute("INSERT INTO videos (username, video, caption, timestamp, type, filter) VALUES (%s,%s,%s,%s,%s,%s)",
                      (current_user(), file_url, caption, time.time(), file_type, filter_type))
            conn.commit()
            conn.close()
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
    conn.commit(); conn.close(); return redirect(request.referrer or '/')

# ========== NOTIFICATIONS ==========
@app.route('/notifications')
def notifications():
    if 'username' not in session: return redirect('/login')
    conn = get_db(); c = conn.cursor()
    notifications_list = []
    c.execute("SELECT id FROM videos WHERE username=%s", (current_user(),)); my_videos = c.fetchall()
    my_video_ids = [v['id'] for v in my_videos]
    if my_video_ids:
        placeholders = ','.join(['%s'] * len(my_video_ids))
        c.execute(f"SELECT username FROM likes WHERE video_id IN ({placeholders})", tuple(my_video_ids)); likes = c.fetchall()
        for like in likes:
            if like['username']!= current_user():
                notifications_list.append({'from': like['username'], 'text': 'liked your video'})
    c.execute("SELECT follower FROM following WHERE following=%s", (current_user(),)); followers = c.fetchall()
    for f in followers:
        notifications_list.append({'from': f['follower'], 'text': 'started following you'})
    conn.close()
    return render_template('notifications.html', notifications=notifications_list, current_user=current_user())

# ========== DM INBOX ==========
@app.route('/dm')
def dm_inbox():
    if 'username' not in session: return redirect('/login')
    conn = get_db(); c = conn.cursor()
    c.execute("""SELECT DISTINCT receiver as user FROM messages WHERE sender=%s
                 UNION
                 SELECT DISTINCT sender as user FROM messages WHERE receiver=%s""", (current_user(), current_user())); chats = c.fetchall()
    conn.close()
    return render_template('dm_inbox.html', chats=chats, current_user=current_user())

# ========== DM CHAT ==========
@app.route('/dm/<username>', methods=['GET', 'POST'])
def dm_chat(username):
    if 'username' not in session: return redirect('/login')
    conn = get_db(); c = conn.cursor()
    if request.method == 'POST':
        c.execute("INSERT INTO messages (sender, receiver, message, timestamp) VALUES (%s,%s,%s,%s)",
            (current_user(), username, request.form['message'], time.time())); conn.commit()
    c.execute("""SELECT * FROM messages WHERE (sender=%s AND receiver=%s) OR (sender=%s AND receiver=%s) ORDER BY timestamp ASC""",
        (current_user(), username, username, current_user())); messages = c.fetchall()
    conn.close()
    return render_template('dm_chat.html', messages=messages, chat_with=username, current_user=current_user())

# ========== FRIENDS / DISCOVER PAGE ==========
@app.route('/friends')
def friends():
    if 'username' not in session: return redirect('/login')
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username!=%s", (current_user(),)); users = c.fetchall()
    c.execute("SELECT following FROM following WHERE follower=%s", (current_user(),)); following = [r['following'] for r in c.fetchall()]
    conn.close()
    return render_template('friends.html', users=users, following=following, current_user=current_user())

# ========== SEARCH ==========
@app.route('/search')
def search():
    if 'username' not in session: return redirect('/login')
    query = request.args.get('q', '').strip()
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username LIKE %s OR bio LIKE %s", (f'%{query}%', f'%{query}%')); users = c.fetchall()
    c.execute("SELECT * FROM videos WHERE caption LIKE %s ORDER BY timestamp DESC", (f'%{query}%',)); videos = c.fetchall()
    c.execute("SELECT following FROM following WHERE follower=%s", (current_user(),)); following = [r['following'] for r in c.fetchall()]
    conn.close()
    return render_template('search_results.html', query=query, users=users, videos=videos, current_user=current_user(), following=following)

# ========== ADMIN + USER DELETE ==========
@app.route('/delete/<int:post_id>')
def delete_post(post_id):
    if 'username' not in session: 
        return redirect('/login')
    
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT username FROM videos WHERE id=%s", (post_id,))
    video = c.fetchone()
    
    if not video:
        conn.close()
        return "Post not found"
    
    # Allow if user is admin OR if user owns the post
    if not session.get('is_admin') and video['username']!= current_user():
        conn.close()
        return "No access bro"
    
    c.execute("DELETE FROM videos WHERE id=%s", (post_id,))
    conn.commit(); conn.close()
    return redirect(request.referrer or '/')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
