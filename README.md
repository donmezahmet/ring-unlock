# Ring Intercom One-Touch Unlock Server

A simple server that lets you unlock your Ring Intercom with a single tap from your iPhone.

## 🚀 Quick Setup (10-15 minutes)

### Step 1: Generate Your Secret API Key

Run this on your Mac terminal to generate a secure random key:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

**Copy this key and save it somewhere safe!** You'll need it in the next steps.

---

### Step 2: Deploy to Render

#### Option A: Deploy from GitHub (Recommended)

1. Push this code to a GitHub repository
2. Go to [render.com](https://render.com) and log in
3. Click **New** → **Web Service**
4. Connect your GitHub repo
5. Use these settings:
   - **Name:** `ring-unlock` (or whatever you prefer)
   - **Environment:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app`
6. Add a **Disk** (required for token storage):
   - **Mount Path:** `/data`
   - **Size:** 1 GB (smallest option)
7. Add **Environment Variables:**
   - `API_KEY` = your generated key from Step 1
8. Click **Create Web Service**

#### Option B: Manual Deploy

If you prefer not to use GitHub, you can zip the files and upload manually.

---

### Step 3: Complete Ring Authentication

1. Wait for Render to finish deploying (2-3 minutes)
2. Visit your app URL: `https://your-app-name.onrender.com/`
3. Click **Complete Setup**
4. Enter your Ring email and password
5. Enter the 2FA code sent to your phone
6. You'll see "All Set!" when complete

---

### Step 4: Create iOS Shortcut

1. Open the **Shortcuts** app on your iPhone
2. Tap **+** to create a new shortcut
3. Add action: **Get Contents of URL**
4. Configure:
   - **URL:** `https://your-app-name.onrender.com/unlock`
   - **Method:** `POST`
   - Tap **Add New Header:**
     - **Key:** `X-API-Key`
     - **Value:** Your API key from Step 1
5. Rename the shortcut to "Unlock Door" (or whatever you like)
6. Tap **Add to Home Screen** to create a one-tap icon

---

## 🔐 Security Notes

- **Your API key is your password.** Never share it.
- The server stores a Ring authentication token, not your password.
- You can delete the Render service anytime to revoke access.
- Consider using a unique password for Ring if you're concerned about token storage.

---

## 📱 Usage

After setup, just tap the shortcut icon on your iPhone home screen → door unlocks!

You can also use Siri: "Hey Siri, Unlock Door" (if you named your shortcut that).

---

## 🛠 Troubleshooting

### "Not authenticated" error
Visit `/setup` on your server to re-authenticate with Ring.

### "No intercom found" error
Make sure your Ring Intercom is properly set up in the Ring app first.

### Shortcut returns an error
1. Check your API key is correct
2. Make sure the URL is correct (including `https://`)
3. Try visiting your server URL in a browser to check it's running

---

## 💡 How It Works

1. You tap the shortcut on your iPhone
2. iPhone sends a request to your Render server
3. Server authenticates with Ring using the saved token
4. Server sends "unlock" command to your Ring Intercom
5. Your door unlocks!

All of this happens in about 1-2 seconds.

---

## 📝 License

MIT - Do whatever you want with this code.
