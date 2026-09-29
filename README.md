# ShiftFlow — Fixed Real Backend

## Windows setup

Open this folder in VS Code, then Terminal → New Terminal.

Run these commands one at a time:

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python app.py
```

Then open:

http://127.0.0.1:5000

## Deploy online

To keep ShiftFlow available while your computer is off, deploy it to a cloud host. This project includes a Render Blueprint (`render.yaml`) that creates a web service and PostgreSQL database. The always-on web service and database use paid plans; check Render's current pricing before creating them.

1. Push this project to a private GitHub repository. Do not commit passwords or other secrets.
2. In Render, choose **New → Blueprint**, connect that repository, and apply `render.yaml`.
3. When prompted, provide `SHIFT_FLOW_ADMIN_EMAIL` and a unique, strong `SHIFT_FLOW_ADMIN_PASSWORD`. These create the first manager account; they are not demo credentials.
4. Wait for the deploy to finish, then use the `onrender.com` URL shown on the service. Check `/health` to confirm it is responding.

The hosted database starts empty; local SQLite data in `instance/shiftflow.db` is not copied automatically. Email notifications also remain disabled until SMTP settings are added to the hosted service environment.

## Demo accounts

Manager:
- Email: manager@shiftflow.test
- Password: password123

Worker:
- Email: worker@shiftflow.test
- Password: password123

## Email notifications

ShiftFlow sends email notifications for assigned shifts and worker responses when SMTP is configured. Set these environment variables before starting Flask:

```powershell
$env:SHIFT_FLOW_SMTP_HOST = "smtp.example.com"
$env:SHIFT_FLOW_SMTP_PORT = "587"
$env:SHIFT_FLOW_SMTP_USERNAME = "your-email@example.com"
$env:SHIFT_FLOW_SMTP_PASSWORD = "your-email-password-or-app-password"
$env:SHIFT_FLOW_MAIL_FROM = "your-email@example.com"
$env:SHIFT_FLOW_SMTP_USE_TLS = "true"
python app.py
```

For Gmail, use an App Password rather than your normal account password. Email delivery is optional; without these settings, the app continues working and logs that notifications were skipped.

## Mobile app wrapper readiness

The app includes a web manifest, install icon, responsive viewport metadata, and a service worker. On Android Chrome, open the running app, then use the browser menu and choose **Install app** or **Add to Home screen**. On iPhone Safari, use **Share → Add to Home Screen**.

For a Play Store or App Store package, use the deployed HTTPS URL as the wrapper's start URL with a tool such as Capacitor. The Flask server must remain deployed and reachable; the wrapper does not replace the backend.

## If you previously used an older ShiftFlow database

You do NOT need to manually delete the database with this fixed version.
The application now checks for the demo accounts every time it starts and resets their demo password to `password123`.

If you want a completely fresh database, stop the server with Ctrl+C and delete:

`instance/shiftflow.db`

Then run:

```powershell
python app.py
```

## Test

1. Open `/health`. It should say: `ShiftFlow is running correctly.`
2. Go to the home page.
3. Login as the manager.
4. Logout.
5. Login as the worker.

Do not open `app.py` directly in Chrome. Flask must be running in the terminal.
