import discord
import hmac
import hashlib
from discord.ext import commands
import pandas as pd
import os
import subprocess
import asyncio
import io
import requests
from datetime import datetime, timedelta, timezone
from github import Github, Auth


def hash_user(username):
    """HMAC-SHA256(username, key từ hash_key.txt)."""
    if not username:
        return 'u_unknown'
    key = open("hash_key.txt", encoding='utf-8').read().strip()
    msg = username.lower().strip().encode('utf-8')
    h = hmac.new(key.encode('utf-8'), msg, hashlib.sha256).hexdigest()[:12]
    return f'u_{h}'

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
    target_dt = now_vn - timedelta(days=30)

    @client.event
    async def on_ready():
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Đã kết nối Discord: {client.user}")
        print(f"🎯 Quét ngược 30 ngày về mốc: {target_dt.strftime('%Y-%m-%d %H:%M:%S')} VN")
        try:
            channel = client.get_channel(CHANNEL_ID)
            if not channel:
                print(f"❌ Không tìm thấy kênh ID={CHANNEL_ID}")
                await client.close()
                return
            async for message in channel.history(limit=10000):
                msg_vn = message.created_at.astimezone(vn_tz)
                if msg_vn < target_dt:
                    print(f"✅ Đã quét lùi tới mốc 30 ngày. Dừng quét.")
                    break
                if not message.content or not message.content.strip():
                    continue
                time_str = msg_vn.strftime('%m/%d/%Y %H:%M:%S')
                author = message.author
                found.append({
                    'ID': str(message.id),
                    'Timestamp': time_str,
                    'Username': hash_user(author.name),
                    'Content': message.content,
                    'Forwarded Content': '',
                    'Attachments': len(message.attachments),
                    'Embeds': len(message.embeds),
                    'Reactions': sum(r.count for r in message.reactions)
                })
            print(f"\n📦 Tổng cộng lấy được: {len(found)} tin nhắn.")
        except Exception as e:
            print(f"❌ Lỗi khi lấy tin nhắn: {e}")
        finally:
            await client.close()

    try:
        await client.start(DISCORD_TOKEN)
    except Exception as e:
        print(f"❌ Lỗi kết nối Discord: {e}")
    return found

def push_to_github(df_new):
    if df_new.empty:
        print("⚠️ Không có dữ liệu mới để push.")
        return
    try:
        g = Github(auth=Auth.Token(GITHUB_TOKEN))
        repo = g.get_repo(GITHUB_REPO)

        try:
            contents = repo.get_contents(CSV_FILE, ref=GITHUB_BRANCH)
            file_exists_on_github = True
            if contents.size and contents.size > 1000000:
                print(f"[SAFE] File is {contents.size:,} bytes (>1MB). Using download_url...")
                raw_resp = requests.get(contents.download_url)
                raw_resp.raise_for_status()
                df_old = pd.read_csv(io.BytesIO(raw_resp.content), dtype=str)
            else:
                df_old = pd.read_csv(io.StringIO(contents.decoded_content.decode("utf-8")), dtype=str)
            print(f"[SAFE] Loaded old data: {len(df_old):,} rows")
        except Exception as e:
            err_msg = str(e)
            if "404" in err_msg or "Not Found" in err_msg:
                print(f"[SAFE] File {CSV_FILE} not found (first run)")
                df_old = pd.DataFrame()
                file_exists_on_github = False
            else:
                print(f"[SAFE] ERROR get_contents: {type(e).__name__}: {err_msg[:200]}")
                file_exists_on_github = True 
                df_old = pd.DataFrame()

        if file_exists_on_github and df_old.empty:
            print(f"[SAFE] ABORT: {CSV_FILE} exists on GitHub but read FAILED!")
            print(f"[SAFE] Not overwriting to preserve data.")
            return

        existing_ids = set()
        if not df_old.empty and 'ID' in df_old.columns:
            existing_ids = set(df_old['ID'].astype(str).str.strip())

        if 'ID' in df_new.columns:
            df_new['ID'] = df_new['ID'].astype(str).str.strip()
            df_has_id = df_new[~df_new['ID'].isin(existing_ids)].copy()
            df_no_id = df_new[df_new['ID'] == ''].copy()
        else:
            df_has_id = df_new.copy()
            df_no_id = pd.DataFrame()

        df_final = pd.concat([df_old, df_has_id, df_no_id], ignore_index=True)

        if len(df_old) > 0 and len(df_final) < len(df_old) * 0.9:
            print(f"[SAFE] ABORT: data new ({len(df_final)}) < 90% old ({len(df_old)})!")
            return

        def make_sort_key(row):
            id_str = str(row.get('ID', '')).strip()
            if id_str and 'E' not in id_str.upper() and id_str.isdigit():
                return int(id_str)
            try:
                dt = pd.to_datetime(row['Timestamp'], format='mixed')
                return int(dt.timestamp() * 1000)
            except:
                return 0

        df_final['_sort_key'] = df_final.apply(make_sort_key, axis=1)
        df_final = df_final.sort_values('_sort_key', ascending=False).drop(columns=['_sort_key']).reset_index(drop=True)

        if len(df_final) == len(df_old):
            print("⚠️ Không có dòng mới nào.")
            return

        csv_string = df_final.to_csv(index=False)
        with open(CSV_FILE, "w", encoding="utf-8") as f:
            f.write(csv_string)

        subprocess.run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], check=True)
        subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)

        last_info = subprocess.run(["git", "log", "-1", "--format=%s|%ad", "--date=short"], capture_output=True, text=True).stdout.strip()
        if "|" not in last_info:
            print(f"⚠️ Không đọc được last commit: {last_info}")
            return
        last_msg, last_date = last_info.split("|", 1)

        subprocess.run(["git", "add", CSV_FILE], check=True)
        diff_check = subprocess.run(["git", "diff", "--cached", "--quiet"])
        if diff_check.returncode == 0:
            print("⚠️ Không có thay đổi staged — skip.")
            return

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        msg = f"🤖 Auto-add merchant posts ({today})"
        is_amend = "🤖 Auto-add" in last_msg and last_date == today

        if is_amend:
            try:
                subprocess.run(["git", "commit", "--amend", "-m", msg], check=True)
                subprocess.run(["git", "fetch", "origin", GITHUB_BRANCH], check=True, capture_output=True)
                subprocess.run(["git", "push", "--force-with-lease", "origin", f"HEAD:{GITHUB_BRANCH}"], check=True)
                print(f"✅ Amended same-day commit — total {len(df_final):,} rows")
                return
            except subprocess.CalledProcessError as e:
                print(f"⚠️ Amend path failed: {e}. Fallback to normal commit.")

        subprocess.run(["git", "commit", "-m", msg], check=True)
        subprocess.run(["git", "push", "origin", f"HEAD:{GITHUB_BRANCH}"], check=True)
        print(f"✅ New commit — total {len(df_final):,} rows")

    except Exception as e:
        print(f"❌ Lỗi khi push: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print("🚀 Bắt đầu Scraper (Quét 30 ngày)...")
    messages = asyncio.run(fetch_latest_message())
    if messages:
        push_to_github(pd.DataFrame(messages))
    else:
        print("Không có dữ liệu mới, kết thúc tiến trình.")
