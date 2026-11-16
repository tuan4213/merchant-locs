# discord_scraper.py (bản sạch - chỉ 3 cột: ID, Timestamp, Content)
import discord
from discord.ext import commands
import pandas as pd
import os
import asyncio
import io
import re
import requests
from datetime import datetime, timedelta, timezone
from github import Github, Auth

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0"))
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO", "tuan4213/merchant-locs")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")
CSV_FILE = "data.csv"
REQUIRED_COLUMNS = ['ID', 'Timestamp', 'Content']
LOOKBACK_DAYS = 7

def is_merchant_message(content):
    if not content or len(content) > 2000:
        return False
    pairs = re.findall(r'\b\d{1,2}-\d{1,2}\b', content)
    return len(pairs) >= 3

async def fetch_latest_message():
    client = commands.Bot(command_prefix="!", self_bot=True)
    found = []
    vn_tz = timezone(timedelta(hours=7))
    target_dt = datetime.now(vn_tz) - timedelta(days=LOOKBACK_DAYS)

    @client.event
    async def on_ready():
        try:
            channel = client.get_channel(CHANNEL_ID)
            if not channel: await client.close(); return
            async for message in channel.history(limit=5000):
                msg_vn = message.created_at.astimezone(vn_tz)
                if msg_vn < target_dt: break
                if not message.content: continue
                if not is_merchant_message(message.content): continue
                found.append({
                    'ID': str(message.id),
                    'Timestamp': msg_vn.strftime('%m/%d/%Y %H:%M:%S'),
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
        
        df_old = pd.DataFrame(columns=REQUIRED_COLUMNS)
        try:
            contents = repo.get_contents(CSV_FILE, ref=GITHUB_BRANCH)
            if contents.size > 1000000:
                raw = requests.get(contents.download_url); raw.raise_for_status()
                df_old = pd.read_csv(io.BytesIO(raw.content), dtype=str)
            else:
                df_old = pd.read_csv(io.StringIO(contents.decoded_content.decode("utf-8")), dtype=str)
            df_old = df_old.reindex(columns=REQUIRED_COLUMNS, fill_value="")
        except: pass

        existing_ids = set(df_old['ID'].astype(str))
        df_new['ID'] = df_new['ID'].astype(str)
        df_new_only = df_new[~df_new['ID'].isin(existing_ids)]
        if df_new_only.empty:
            print("No new messages")
            return

        df_final = pd.concat([df_old, df_new_only], ignore_index=True)
        df_final = df_final.reindex(columns=REQUIRED_COLUMNS, fill_value="")
        df_final['_ts'] = pd.to_datetime(df_final['Timestamp'], format='%m/%d/%Y %H:%M:%S', errors='coerce')
        df_final = df_final.sort_values('_ts').drop(columns='_ts').reset_index(drop=True)
        
        csv_str = df_final.to_csv(index=False)
        try:
            existing = repo.get_contents(CSV_FILE, ref=GITHUB_BRANCH)
            repo.update_file(CSV_FILE, f"Auto: +{len(df_new_only)} msgs (3 cols)",
                            csv_str, existing.sha, branch=GITHUB_BRANCH)
        except:
            repo.create_file(CSV_FILE, "Create data.csv", csv_str, branch=GITHUB_BRANCH)
        print(f"Pushed: {len(df_final)} msgs")
    except Exception as e: print(f"Push Error: {e}")

if __name__ == "__main__":
    messages = asyncio.run(fetch_latest_message())
    if messages: push_to_github(pd.DataFrame(messages))
