# Set up the Clipper Discord bot

The bot runs the review flow (buttons on clips), campaign cards, agent questions, alerts, and the `#control` chat with the Director (PLAN §7). It only runs on your PC, inside Clipper.

## 1. Make a private server
1. In Discord: **+ (Add a server) → Create my own → For me and my friends**. Name it **Clipper HQ**.
2. Create a role **Clipper** (Server settings → Roles) and give it to yourself and anyone else allowed to review. Only this role can press the bot's buttons.

The bot can create the channels itself during first-run setup (`#control`, `#campaigns`, `#clip-review` as a **forum**, `#published`, `#alerts`). If you'd rather create them by hand, use those exact names and make `#clip-review` a **Forum** channel.

## 2. Create the bot application
1. Go to **discord.com/developers/applications** → **New Application** → name it **Clipper**.
2. **Bot** tab:
   - Click **Reset Token** and copy the token. **Don't paste it into chat, a file or the repo.** Clipper's setup wizard asks for it and stores it in Windows Credential Manager.
   - Turn **Public Bot** off.
   - Under **Privileged Gateway Intents**, turn on **Message Content Intent** (needed so the Director can read what you type in `#control`). Leave Presence and Server Members off.
3. **Installation** tab (or OAuth2 → URL Generator):
   - Scopes: `bot`, `applications.commands`
   - Bot permissions: View Channels, Send Messages, Send Messages in Threads, Create Public Threads, Manage Threads, Embed Links, Attach Files, Read Message History, Add Reactions, Pin Messages (or Manage Messages), Use Application Commands, and **Manage Channels** only if you want the bot to create the channels for you (you can remove it afterwards).
4. Open the generated install link, choose **Clipper HQ**, and authorize.

## 3. Note the IDs (setup asks for them)
Turn on **User settings → Advanced → Developer Mode**, then right-click → **Copy ID** on:
- the server (Clipper HQ)
- the **Clipper** role
- each channel, if you created them yourself

IDs aren't secret; they go in Clipper's settings.

## 4. File size limit for previews
Bots can upload files up to **10 MB** on a server without boosts. Clipper encodes review previews to about 9.5 MB to fit (PLAN §7), so you don't need Nitro or boosts.

## 5. Check it works (after the bot is built)
In `#control`, type `/clipper status`. The bot should reply with the agent and switch status. Clicking a button without the Clipper role should be refused.
