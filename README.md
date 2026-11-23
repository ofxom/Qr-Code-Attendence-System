# QR Code Attendance System

A beginner-friendly attendance website built with Python, Flask, HTML, CSS, and JavaScript. Students register and sign in with a roll number. Faculty sign in, open a subject session, and show a QR code that rotates every 30 seconds. Attendance is stored in JSON files.

## Project structure

```text
qr_attendance/
├── app.py
├── requirements.txt
├── README.md
├── data/
│   ├── students.json
│   ├── faculty.json
│   ├── sessions.json
│   └── attendance.json
├── templates/
│   ├── login.html
│   ├── register.html
│   ├── faculty_register.html
│   ├── faculty_dashboard.html
│   ├── student_dashboard.html
│   ├── qr_display.html
│   ├── scan_qr.html
│   └── attendance.html
└── static/
    ├── style.css
    └── script.js
```

## How it works

1. Students and faculty can create their own accounts. Passwords are saved as secure hashes, not as plain text.
2. Faculty sign in and start a subject session. The server makes a random token and encodes it in a QR image.
3. The displayed QR is refreshed every 30 seconds. Every student can use the current code; scanning it does not consume it.
4. The student logs in on their own phone and scans the QR. The server gets the student's roll number from the login session, checks that the token belongs to an active session and has not expired, and records attendance.
5. A lock protects JSON read-and-update operations, and a duplicate check is done while that lock is held. Faculty can close a session at any time.

## Install and run

Use Python 3.9 or newer. In PowerShell, open this folder and run:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

If PowerShell blocks activation, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that terminal, then activate the environment again.

The site is at `http://127.0.0.1:5000`. You can create a faculty account using the link on the login page. On first startup, the terminal also prints a one-time faculty username and password if no faculty account exists. To set that initial account before the first run, set `FACULTY_USERNAME` and `FACULTY_PASSWORD` environment variables. Set `FLASK_SECRET_KEY` to a long random value for a stable session key; without it, a new development key is generated at each start.

For example, set these in PowerShell before the first run:

```powershell
$env:FACULTY_USERNAME = "teacher"
$env:FACULTY_PASSWORD = "Choose-a-unique-password"
$env:FLASK_SECRET_KEY = (python -c "import secrets; print(secrets.token_hex(32))")
python app.py
```

## Test with a phone camera

1. Connect the computer and smartphone to the same Wi-Fi.
2. Find the computer's local IP address using `ipconfig` on Windows.
3. For camera access from another device, use an HTTPS address. Mobile browsers generally block camera access on ordinary `http://192.168...` addresses. For a classroom demo, use a trusted HTTPS tunnel to the computer's port 5000 or configure local HTTPS. Do not expose a debug server to the public internet.
4. Sign in as faculty on the computer, start a session, and display its QR.
5. Create a student account and log in on the phone using the HTTPS site address. Open **Scan attendance QR**, allow camera access, and point the camera at the faculty screen.
6. Scan again as the same student to see the duplicate warning. Wait for a new code or close the session to test expired/closed code rejection.

The scanner uses the `html5-qrcode` browser library from a CDN, so the phone needs internet access to load that script. It also needs a modern browser with camera support and an HTTPS/localhost page.

## Notes and limitations

- Student and faculty registration are both open for this mini-project. Anyone who can reach the site can create a faculty account, so add an approval or invite-code step before using it beyond a trusted demo.
- QR tokens are random, change every 30 seconds, and remain usable by all students until that period expires. A token never becomes invalid just because one student used it.
- The server ignores any roll number in an attendance request and uses the authenticated student's identity instead. This, login requirements, expiry checks, duplicate checks, and session closing reduce misuse. They cannot completely prevent proxy attendance if students share accounts or scan remotely.
- JSON is suitable for a small classroom demo, not a busy production system. The in-process lock prevents concurrent updates among threads in one app process, and atomic replacement reduces the chance of a partially written file. It does not coordinate multiple server processes or computers, and a process crash between separate JSON-file updates can still leave data out of sync. Run one Flask process and back up the `data` folder. A real multi-user deployment should use a transactional database.
- Flask's built-in development server is for local projects and demos, not production hosting.
