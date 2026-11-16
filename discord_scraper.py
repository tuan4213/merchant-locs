import discord
from discord.ext import commands
import pandas as pd
import os
import subprocess
import asyncio
import io
import requests
from datetime import datetime, timedelta, timezone
from github import Github, Auth

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0"))
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")
CSV_FILE = "data.csv"

async def fetch_latest_message():
    client = commands.Bot(command_prefix="!", self_bot=True)
    found = []
    vn_tz = timezone(timedelta(hours=7))
    now_vn = datetime.now(vn_tz)
    target_dt = now_vn - timedelta(days=7)

    @client.event
    async def on_ready():
        try:
            channel = client.get_channel(CHANNEL_ID)
            if not channel: await client.close(); return
            async for message in channel.history(limit=2000):
                msg_vn = message.created_at.astimezone(vn_tz)
                if msg_vn < target_dt: break
                if not message.content: continue
                time_str = msg_vn.strftime('%m/%d/%Y %H:%M:%S')
                author = message.author
                found.append({
                    'ID': str(message.id), 'Timestamp': time_str, 'Username': author.name,
                    'Content': message.content
                })
        except Exception as e: print(f"Error: {e}")
        finally: await client.close()

    try: await client.start(DISCORD_TOKEN)
    except Exception as e: print(f"Error: {e}")
    return found

def push_to_github(df_new):
    if df_new.empty: return
    try:
        g = Github(auth=Auth.Token(GITHUB_TOKEN))
        repo = g.get_repo(GITHUB_REPO)
        
        df_old = pd.DataFrame()
        try:
            contents = repo.get_contents(CSV_FILE, ref=GITHUB_BRANCH)
            if contents.size > 1000000:
                raw_resp = requests.get(contents.download_url); raw_resp.raise_for_status()
                df_old = pd.read_csv(io.BytesIO(raw_resp.content), dtype=str)
            else:
                df_old = pd.read_csv(io.StringIO(contents.decoded_content.decode("utf-8")), dtype=str)
        except: pass

        existing_ids = set(df_old['ID'].astype(str)) if not df_old.empty and 'ID' in df_old.columns else set()
        df_new['ID'] = df_new['ID'].astype(str)
        df_has_id = df_new[~df_new['ID'].isin(existing_ids)]
        
        df_final = pd.concat([df_old, df_has_id], ignore_index=True)
        
        if not df_old.empty and len(df_final) < len(df_old) * 0.9: return # Safety
        
        df_final.to_csv(CSV_FILE, index=False)
        
        subprocess.run(["git", "config", "user.email", "bot@bot.com"], check=True)
        subprocess.run(["git", "config", "user.name", "bot"], check=True)
        subprocess.run(["git", "add", CSV_FILE], check=True)
        subprocess.run(["git", "commit", "-m", "Auto-update"], check=True)
        subprocess.run(["git", "push", "origin", GITHUB_BRANCH], check=True)
    except Exception as e: print(f"Push Error: {e}")

if __name__ == "__main__":
    messages = asyncio.run(fetch_latest_message())
    if messages: push_to_github(pd.DataFrame(messages))
